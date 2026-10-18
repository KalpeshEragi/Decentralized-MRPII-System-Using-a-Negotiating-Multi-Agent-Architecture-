"""Simulated suppliers (PI-1): they answer Purchasing's offers automatically, so the simulation runs without a person.
A supplier is not an agent; it answers through the same supplier chat path a person would use (Purchasing's
`receive_supplier_message`), in Purchasing's strict reply format. The human supplier chat keeps working.

The rule is deterministic (same state, same answer): a supplier accepts an offer it can meet — the date is at least
its lead time away and the quantity within what it has available — and otherwise counters with what it can do: the
quantity it has, by the earliest date its lead time allows.

Scenario triggers (for example a supplier delay, S2) change simulated facts through Purchasing; they are not here.
"""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.work_runner import Registration, enqueue
from app.negotiation_engine import service as engine
from app.purchasing_agent import a2a
from app.purchasing_agent.link_models import AdapterWork, PlanningLink
from app.purchasing_agent.models import LegStatus, ProcurementRequest, PurchaseRequisition
from app.purchasing_agent.negotiation import receive_supplier_message
from app.simulation.clock import today
from app.supplier_service import service as supplier_service

logger = logging.getLogger(__name__)
REPLY_NAMESPACE = uuid.UUID("5a1e0000-0000-4000-8000-00000000a11e")  # reply ids derive from the offer they answer


def answer(db, leg: PurchaseRequisition, request: ProcurementRequest) -> tuple[uuid.UUID, str] | None:
    """The simulated supplier's reply to the offer it still owes an answer to, or None (nothing to answer)."""
    awaited = engine.awaited_message_id(db, leg.negotiation_session_id)
    if awaited is None or engine.latest_message_id(db, leg.negotiation_session_id) != awaited:
        return None  # nothing asked, or already answered
    offer = engine.current_offer(db, leg.negotiation_session_id)
    if offer is None:
        return None
    terms = next((s for s in supplier_service.supplier_items_for(db, request.item_id)
                  if s.supplier_id == leg.supplier_id), None)
    if terms is None:
        return uuid.uuid5(REPLY_NAMESPACE, str(awaited)), "REJECT"
    quantity, wanted = Decimal(offer.terms["quantity"]), offer.terms["delivery_date"]
    earliest = today(db) + timedelta(days=terms.lead_time_days)
    if quantity <= terms.available_qty and wanted >= earliest.isoformat():
        text = "ACCEPT"
    else:
        text = f"COUNTER {int(min(quantity, terms.available_qty))} {max(wanted, earliest.isoformat())}"
    return uuid.uuid5(REPLY_NAMESPACE, str(awaited)), text


def take_turn(session_factory, item, renew) -> None:
    """Long-mode work item SUPPLIER_TURN: every supplier of this request answers what it owes; then the adapter
    follows the request again (only if something was answered, so the loop always ends)."""
    session_id = item.payload["session_id"]
    with session_factory() as db:
        link = db.get(PlanningLink, session_id)
        if link is None or link.procurement_request_id is None:
            return
        request = db.get(ProcurementRequest, link.procurement_request_id)
        legs = db.scalars(select(PurchaseRequisition).where(
            PurchaseRequisition.procurement_request_id == request.id,
            PurchaseRequisition.status == LegStatus.PENDING).order_by(PurchaseRequisition.id)).all()
        replies = [(leg.id, reply) for leg in legs if (reply := answer(db, leg, request)) is not None]
        now = a2a.simulated_now(db)
        db.rollback()
    answered = 0
    for leg_id, (message_id, text) in replies:
        with session_factory() as db:
            try:
                received = receive_supplier_message(db, leg_id, message_id, text, now, get_settings(), a2a.llm_client())
                answered += 0 if received.duplicate else 1
            except AppError as error:  # the offer moved on meanwhile (e.g. another Leg reallocated): answer later
                db.rollback()
                logger.info("simulated supplier reply on leg %s not applied: %s", leg_id, error)
    if answered:
        with session_factory() as db:
            enqueue(db, AdapterWork, scope_key=session_id, kind="CHECK", payload={"session_id": session_id})
            db.commit()


def register(runner_register) -> None:
    runner_register(Registration(name="simulated-suppliers", model=AdapterWork, handler=take_turn, mode="long",
                                 where=AdapterWork.kind == "SUPPLIER_TURN"))
