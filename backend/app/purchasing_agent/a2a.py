"""The adapter that connects the Purchasing Agent to the six-agent platform (PI-1 to PI-6).

Purchasing gets an inbox on the negotiation layer, like every owner. Planning asks for SUPPLY; the adapter turns it into
a Procurement Request and follows it with Purchasing's own functions (selection, supplier negotiation, approval).
Purchasing's rules and tables are unchanged.

Purchasing's functions commit their own transactions and may call the language model, so they never run inside the
inbox transaction: the inbox only records what Planning said, and the work runs as queued jobs (long mode):

  SUBMIT         Planning's REQUEST -> a Procurement Request (on the simulated clock; item matched by SKU)
  CHECK          follow the request: agreed -> OFFER to Planning; failed -> REJECT; still negotiating -> suppliers' turn
  SUPPLIER_TURN  simulated suppliers answer (PI-1; `app/simulation/suppliers.py`)
  COMMIT         Planning's COMMIT is the approval (PI-2) -> ACCEPT + `ProcurementCommitted`
  ABORT          Planning no longer needs it -> Purchasing rejects / aborts the request

Session with Planning:  REQUEST -> (supplier negotiation) -> OFFER -> ACCEPT -> AGREEMENT_PROPOSED (the hold is the
request's AGREED Legs, which Purchasing already counts against the suppliers) -> COMMIT -> ACCEPT.
"""

import logging
import math
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.work_runner import Registration, enqueue
from app.events import channel
from app.events.models import Event
from app.llm.client import LLMClient, OllamaClient
from app.negotiation import layer
from app.negotiation.envelope import Envelope, Hold, MessageType as M, ReasonCode, ResourceType, Terms
from app.negotiation.models import Session
from app.purchasing_agent import abort as abort_module, approval, reads, service
from app.purchasing_agent.link_models import AdapterWork, PlanningLink
from app.purchasing_agent.models import LegStatus, ProcurementRequest, PurchaseRequisition, RequestStatus
from app.simulation.clock import today
from app.simulation.settings import setting

logger = logging.getLogger(__name__)
AGENT = "PURCHASING"
OPEN_LINKS = ("REQUESTED", "NEGOTIATING", "OFFERED", "HELD")


def llm_client() -> LLMClient:
    """The model Purchasing uses for wording and reading replies (never required). Tests replace it."""
    return OllamaClient.from_settings()


def simulated_now(db: DbSession) -> datetime:
    """Purchasing runs on the simulated clock (PI-6): noon of the simulated day, in Purchasing's timezone."""
    return datetime.combine(today(db), time(12), tzinfo=ZoneInfo(get_settings().purchasing_timezone))


def _queue(db: DbSession, link: PlanningLink, kind: str) -> None:
    enqueue(db, AdapterWork, scope_key=link.session_id, kind=kind, payload={"session_id": link.session_id})


def _say(db: DbSession, link: PlanningLink, kind: M, **fields) -> None:
    """Answer Planning's latest message in this session."""
    layer.send(db, layer.reply_to(Envelope.model_validate(link.last_message), kind, **fields))


# -- inbox (short: only records and queues) -------------------------------------------------------------------------------


def handle_message(db: DbSession, message: Envelope, session: Session) -> None:
    link = db.get(PlanningLink, str(session.id), with_for_update=True)
    kind = message.message_type
    if kind == M.REQUEST and link is None:
        terms = message.terms
        if terms.resource_type != ResourceType.SUPPLY or terms.needed_by is None:
            layer.send(db, layer.reply_to(message, M.REJECT, reason_code=ReasonCode.INVALID_REQUEST,
                                          text="Purchasing answers SUPPLY requests with a needed-by date"))
            return
        link = PlanningLink(session_id=str(session.id), case_id=message.case_id, item_id=terms.resource_ref,
                            quantity=terms.quantity, needed_by=terms.needed_by,
                            for_kind=terms.extra.get("for_kind", "PRODUCTION_ORDER"),
                            for_ref=terms.order_id or message.case_id, status="REQUESTED",
                            last_message=message.model_dump(mode="json"))
        db.add(link)
        db.flush()
        _queue(db, link, "SUBMIT")
        return
    if link is None:
        return
    link.last_message = message.model_dump(mode="json")
    if kind == M.ACCEPT and link.status == "OFFERED":
        expires = datetime.now(timezone.utc) + timedelta(days=30)  # Purchasing's holds do not expire by time
        _say(db, link, M.AGREEMENT_PROPOSED, terms=_supply_terms(db, link),
             hold=Hold(hold_id=str(link.procurement_request_id), expires_at=expires), text="supply held with the suppliers")
        link.status = "HELD"
    elif kind == M.COMMIT and link.status == "HELD":
        _queue(db, link, "COMMIT")
    elif kind in (M.ABORT, M.REJECT) and link.status in OPEN_LINKS:
        _queue(db, link, "ABORT")


# -- queued work (long: Purchasing's functions commit on their own) -------------------------------------------------------


def handle_work(session_factory, item, renew) -> None:
    {"SUBMIT": _submit, "CHECK": _check, "COMMIT": _commit, "ABORT": _abort}[item.kind](
        session_factory, item.payload["session_id"])


def _submit(session_factory, session_id: str) -> None:
    with session_factory() as db:
        link = db.get(PlanningLink, session_id)
        if link.procurement_request_id is not None or link.status != "REQUESTED":
            return
        supplier_item = reads.supplier_item_id(db, link.item_id)
        now = simulated_now(db)
        new = service.NewProcurementRequest(
            request_ref=f"PLANNING-{session_id}", item_id=supplier_item or uuid.uuid4(),
            shortage_quantity=Decimal(math.ceil(link.quantity)), required_date=link.needed_by, priority=3,
            requested_by="PLANNING")
        db.rollback()
        try:
            if supplier_item is None:
                raise AppError(ErrorCode.VALIDATION_ERROR, "no supplier item with this SKU")
            submitted = service.submit_request(db, new, now, get_settings(), llm_client())
        except AppError as error:  # Purchasing refused the request itself: tell Planning, nothing to retry
            db.rollback()
            link = db.get(PlanningLink, session_id, with_for_update=True)
            link.status = "FAILED"
            _say(db, link, M.REJECT, reason_code=ReasonCode.UNAVAILABLE, text=str(error)[:200])
            db.commit()
            return
    with session_factory() as db:
        link = db.get(PlanningLink, session_id, with_for_update=True)
        link.procurement_request_id, link.status = submitted.request_id, "NEGOTIATING"
        _queue(db, link, "CHECK")
        db.commit()


def _check(session_factory, session_id: str) -> None:
    with session_factory() as db:
        link = db.get(PlanningLink, session_id, with_for_update=True)
        if link.procurement_request_id is None or link.status not in OPEN_LINKS:
            return
        request = db.get(ProcurementRequest, link.procurement_request_id)
        if request.status == RequestStatus.AGREEMENT_PROPOSED and link.status == "NEGOTIATING":
            _say(db, link, M.OFFER, text="supply agreed with the suppliers", terms=_supply_terms(db, link))
            link.status = "OFFERED"
        elif request.status in (RequestStatus.FAILED, RequestStatus.APPROVAL_REJECTED):
            link.status = "FAILED"
            _say(db, link, M.REJECT, reason_code=ReasonCode.UNAVAILABLE,
                 text=(request.status_reason or "no supplier can deliver it")[:200])
        elif request.status == RequestStatus.NEGOTIATING and setting(db, "simulated_suppliers"):
            _queue(db, link, "SUPPLIER_TURN")
        db.commit()


def _supply_terms(db: DbSession, link: PlanningLink) -> Terms:
    """What the suppliers agreed (the request's AGREED Legs): total quantity, arriving by the latest Leg's date."""
    legs = db.scalars(select(PurchaseRequisition).where(
        PurchaseRequisition.procurement_request_id == link.procurement_request_id,
        PurchaseRequisition.status == LegStatus.AGREED)).all()
    return Terms(resource_type=ResourceType.SUPPLY, resource_ref=link.item_id,
                 quantity=sum((leg.agreed_quantity for leg in legs), Decimal(0)), needed_by=link.needed_by,
                 available_from=max(leg.agreed_delivery_date for leg in legs), order_id=link.for_ref,
                 extra={"for_kind": link.for_kind})


def _commit(session_factory, session_id: str) -> None:
    """Planning's COMMIT is the approval (PI-2). Safe to repeat: an already committed request is only reported."""
    with session_factory() as db:
        link = db.get(PlanningLink, session_id)
        if link.status != "HELD":
            return
        request = db.get(ProcurementRequest, link.procurement_request_id)
        if request.status == RequestStatus.AGREEMENT_PROPOSED:
            approval.approve(db, request.id, "PLANNING", simulated_now(db))  # commits
    with session_factory() as db:
        link = db.get(PlanningLink, session_id, with_for_update=True)
        request = db.get(ProcurementRequest, link.procurement_request_id)
        if request.status != RequestStatus.COMMITTED:  # the agreement fell through meanwhile
            link.status = "FAILED"
            _say(db, link, M.REJECT, reason_code=ReasonCode.UNAVAILABLE, text="the supplier agreement fell through")
            db.commit()
            return
        legs = db.scalars(select(PurchaseRequisition).where(
            PurchaseRequisition.procurement_request_id == request.id,
            PurchaseRequisition.status == LegStatus.COMMITTED)).all()
        link.status = "COMMITTED"
        _say(db, link, M.ACCEPT, text="supply committed")
        channel.publish(db, event_type="ProcurementCommitted", publisher=AGENT, entity_type="procurement_request",
                        entity_id=str(request.id), entity_version=1, correlation_id=link.case_id,
                        payload={"procurement_request_id": str(request.id), "item_id": link.item_id,
                                 "for_kind": link.for_kind, "for_ref": link.for_ref,
                                 "legs": [{"leg_id": str(leg.id), "quantity": str(leg.agreed_quantity),
                                           "delivery_date": leg.agreed_delivery_date.isoformat()} for leg in legs]})
        db.commit()


def _abort(session_factory, session_id: str) -> None:
    with session_factory() as db:
        link = db.get(PlanningLink, session_id)
        request = db.get(ProcurementRequest, link.procurement_request_id) if link.procurement_request_id else None
        now = simulated_now(db)
        if request is not None and request.status == RequestStatus.AGREEMENT_PROPOSED:
            approval.reject(db, request.id, "PLANNING", now)  # commits
        elif request is not None and request.status == RequestStatus.NEGOTIATING:
            abort_module.abort(db, request.id, "PLANNING", "no longer needed", now)  # commits
    with session_factory() as db:
        link = db.get(PlanningLink, session_id, with_for_update=True)
        if link.status in OPEN_LINKS:
            link.status = "ABORTED"
        db.commit()


# -- facts after commitment -----------------------------------------------------------------------------------------------


def record_supplier_delay(db: DbSession, leg_id: uuid.UUID, new_date) -> dict:
    """A supplier announces that a committed delivery comes later (S2; entered by the simulator or a person).
    Purchasing records the new date on its Leg and publishes `SupplierDeliveryDelayed`. Caller commits."""
    leg = db.get(PurchaseRequisition, leg_id, with_for_update=True)
    if leg is None or leg.status != LegStatus.COMMITTED:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, "only a committed delivery can be delayed")
    if new_date <= leg.agreed_delivery_date:
        raise AppError(ErrorCode.VALIDATION_ERROR, "the new date must be later than the agreed one")
    request = db.get(ProcurementRequest, leg.procurement_request_id)
    link = db.scalar(select(PlanningLink).where(PlanningLink.procurement_request_id == request.id))
    old_date, leg.agreed_delivery_date = leg.agreed_delivery_date, new_date
    payload = {"procurement_request_id": str(request.id), "leg_id": str(leg.id), "quantity": str(leg.agreed_quantity),
               "old_date": old_date.isoformat(), "new_date": new_date.isoformat(),
               "item_id": link.item_id if link else None, "for_kind": link.for_kind if link else None,
               "for_ref": link.for_ref if link else None}
    channel.publish(db, event_type="SupplierDeliveryDelayed", publisher=AGENT, entity_type="delivery",
                    entity_id=str(leg.id), entity_version=new_date.toordinal(),
                    correlation_id=link.case_id if link else str(request.id), payload=payload)
    return payload


# -- following Purchasing (PI-3: no polling loop) -------------------------------------------------------------------------


def after_supplier_reply(db: DbSession, leg_id: uuid.UUID) -> None:
    """Called after a (human) supplier reply was handled: follow that request. Caller commits."""
    leg = db.get(PurchaseRequisition, leg_id)
    link = leg and db.scalar(select(PlanningLink).where(
        PlanningLink.procurement_request_id == leg.procurement_request_id, PlanningLink.status.in_(OPEN_LINKS)))
    if link is not None:
        _queue(db, link, "CHECK")


def on_day_started(db: DbSession, event: Event) -> None:
    """Every simulated morning, follow every open request (response deadlines, late replies)."""
    for link in db.scalars(select(PlanningLink).where(PlanningLink.status.in_(("NEGOTIATING", "OFFERED", "HELD")))):
        _queue(db, link, "CHECK")


def register(runner_register) -> None:
    runner_register(layer.register_inbox(AGENT, handle_message))
    runner_register(Registration(name="purchasing-adapter", model=AdapterWork, handler=handle_work, mode="long",
                                 where=AdapterWork.kind != "SUPPLIER_TURN"))
    channel.subscribe(AGENT, "SimulatedDayStarted", on_day_started)

