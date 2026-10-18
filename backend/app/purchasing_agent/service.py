"""Purchasing orchestration: a Procurement Request in; the selected supplier or split out, with one Leg, one Engine
session and one offer per selected supplier, or FAILED with the Constrained Quantity. The selection for one request is
recorded in one transaction; only the LLM's wording and explanation come after it.

Decisions are made by `selection.py` (pure). This module reads the Supplier Service and the Negotiation Engine only
through their interfaces and writes only the `purchasing_agent` tables.

The LLM only words what was decided (`writer.py`): the offer text (template on failure or a guardrail breach) and the
selection explanation stored in the audit as `llm_explanation`, separate from the deterministic rationale.

Selection uses effective availability (`availability.py`): the item's supplier-items stay locked until the new Legs
are committed, so a competing request waits and then sees their holds. No lock is held while the LLM runs (§9): the
selection, its Legs and their template offers are committed first; the LLM's wording and explanation are applied
afterwards, only where still valid (`wording.py`).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.llm.client import LLMClient
from app.negotiation_engine import service as negotiation_engine
from app.negotiation_engine.service import Participant
from app.purchasing_agent import messages
from app.purchasing_agent.availability import Availability, effective_availability
from app.purchasing_agent.models import (DecisionAudit, LegStatus, ProcurementRequest, PurchaseRequisition,
                                         PurchasingContract, RequestStatus)
from app.purchasing_agent.selection import Contract, Leg, Selection, SupplierOption, price_state, select_suppliers
from app.purchasing_agent.wording import PendingWording, apply_explanation, apply_wordings
from app.purchasing_agent.writer import MessageWriter, selection_facts
from app.supplier_service import service as supplier_service

AGENT_CODE = "PURCHASING"


@dataclass(frozen=True)
class NewProcurementRequest:
    request_ref: str
    item_id: uuid.UUID
    shortage_quantity: Decimal
    required_date: date
    priority: int
    requested_by: str


@dataclass(frozen=True)
class Submitted:
    request_id: uuid.UUID
    created: bool  # False: the request_ref was already known and the existing request is returned


def selection_date(now: datetime, timezone: str) -> date:
    """Today's date in the configured timezone. `now` must carry its timezone: a naive time would silently be read in
    the host's."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(ZoneInfo(timezone)).date()


def _existing(db: Session, new: NewProcurementRequest) -> Submitted | None:
    """The request already stored under this `request_ref`, if any. Reusing the reference for different data is
    refused: silently returning the old request could hide a requester bug."""
    existing = db.scalar(select(ProcurementRequest).where(ProcurementRequest.request_ref == new.request_ref))
    if existing is None:
        return None
    stored = (existing.item_id, existing.shortage_quantity, existing.required_date, existing.priority)
    if stored != (new.item_id, new.shortage_quantity, new.required_date, new.priority):
        raise AppError(ErrorCode.CONFLICT, "request_ref is already used by a request with different data",
                       [{"field": "request_ref", "issue": "already used with a different item, quantity, date or priority"}])
    return Submitted(existing.id, created=False)


def submit_request(db: Session, new: NewProcurementRequest, now: datetime, settings: Settings,
                   llm_client: LLMClient) -> Submitted:
    """Idempotent by `request_ref`: a repeated submission of the same data returns the existing request and changes
    nothing; the same reference with different data is a conflict."""
    if (existing := _existing(db, new)) is not None:
        return existing
    item = supplier_service.get_item(db, new.item_id)
    if item is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "the item is not in the Supplier Service catalogue",
                       [{"field": "item_id", "issue": "unknown item"}])

    request = ProcurementRequest(
        id=uuid.uuid4(), item_id=item.id, shortage_quantity=new.shortage_quantity, required_date=new.required_date,
        priority=new.priority, requested_by=new.requested_by, request_ref=new.request_ref,
        status=RequestStatus.RECEIVED,
    )
    db.add(request)
    try:
        db.flush()
    except IntegrityError:  # the same request_ref arrived at the same time: the other submission won
        db.rollback()
        if (existing := _existing(db, new)) is not None:
            return existing
        raise

    today = selection_date(now, settings.purchasing_timezone)
    availability = list(effective_availability(db, item.id, excluding_request_id=request.id).values())
    selection = select_suppliers(new.shortage_quantity, new.required_date,
                                 _supplier_options(db, item.id, availability, today), today,
                                 saving_threshold=settings.purchasing_cost_saving_split_threshold)
    audit_id, facts = _audit_selection(db, request, today, selection, availability)

    pending: list[PendingWording] = []
    if selection.outcome == "FAILED":
        request.status = RequestStatus.FAILED
        request.status_reason = selection.reasoning_summary
        request.constrained_quantity = selection.constrained_quantity
    else:
        for leg in selection.legs:
            pending.append(_open_leg(db, request, item, leg, now, settings))
        request.status = RequestStatus.NEGOTIATING
        request.split_type = selection.outcome
        request.cost_ranking_available = selection.cost_ranking_available
    names = {a.supplier.supplier_id: a.supplier.supplier_name for a in availability}
    request_id = request.id
    db.commit()  # releases the supplier-item locks before any LLM call

    apply_wordings(db, MessageWriter(llm_client, names), pending)
    apply_explanation(db, llm_client, audit_id, facts)
    return Submitted(request_id, created=True)


def _supplier_options(db: Session, item_id: uuid.UUID, availability: list[Availability],
                      on: date) -> list[SupplierOption]:
    contracts: dict[uuid.UUID, list[Contract]] = defaultdict(list)
    for c in db.scalars(select(PurchasingContract).where(PurchasingContract.item_id == item_id)):
        contracts[c.supplier_id].append(Contract(c.id, c.unit_price, c.valid_from, c.valid_until, c.is_active))
    return [
        SupplierOption(
            supplier_id=a.supplier.supplier_id, supplier_name=a.supplier.supplier_name,
            is_active=a.supplier.supplier_is_active, lead_time_days=a.supplier.lead_time_days,
            min_order_qty=a.supplier.min_order_qty, available_qty=a.effective,
            price=price_state(contracts[a.supplier.supplier_id], on),
        )
        for a in availability
    ]


def _open_leg(db: Session, request: ProcurementRequest, item: supplier_service.ItemRecord, leg: Leg, now: datetime,
              settings: Settings) -> PendingWording:
    """One Engine session and one PENDING Leg for the supplier, then Purchasing's offer as the template; the LLM may
    word it after the commit."""
    quantity, delivery_date = leg.quantity, request.required_date
    terms = messages.offer_terms(quantity, delivery_date)
    session_id = negotiation_engine.open_session(
        db, session_type="PURCHASING_SUPPLIER", correlation_id=request.id,
        objective={"item_id": str(item.id), "sku": item.sku, **terms},
        participants=[
            Participant("AGENT", AGENT_CODE, "INITIATOR"),
            Participant("SUPPLIER", str(leg.supplier_id), "RESPONDENT"),
        ],
        max_rounds=settings.purchasing_max_rounds,
        response_deadline=now + timedelta(hours=settings.purchasing_response_deadline_hours),
        now=now,
    )
    requisition = PurchaseRequisition(
        id=uuid.uuid4(), procurement_request_id=request.id, supplier_id=leg.supplier_id,
        purchasing_contract_id=leg.contract_id, unit_price_at_selection=leg.unit_price, allocated_quantity=quantity,
        negotiation_session_id=session_id, status=LegStatus.PENDING,
    )
    db.add(requisition)
    message_id = uuid.uuid4()
    text = messages.offer_text(leg.supplier_name, item.name, item.sku, quantity, delivery_date)
    negotiation_engine.append_message(
        db, session_id, message_id=message_id, sender_type="AGENT", sender_ref=AGENT_CODE, message_type="OFFER",
        text=text, terms=terms,
    )
    return PendingWording(requisition.id, session_id, message_id, leg.supplier_id, text, terms)


def _audit_selection(db: Session, request: ProcurementRequest, today: date, selection: Selection,
                     availability: list[Availability]) -> tuple[uuid.UUID, dict]:
    """The SUPPLIER_SELECTION audit, without its LLM explanation yet. Returns its ID and the facts the explanation may
    use."""
    options = [audit_record(o) for o in selection.options]
    decision = audit_record({
        "outcome": selection.outcome,
        "legs": selection.legs,
        "total_cost": selection.total_cost,
        "cost_ranking_available": selection.cost_ranking_available,
        "constrained_quantity": selection.constrained_quantity,
        "best_priced_single": selection.best_priced_single,  # a later reallocation's saving is measured against it
    })
    facts = selection_facts(request.shortage_quantity, request.required_date, today, decision, options,
                            selection.reasoning_summary)
    audit_id = uuid.uuid4()
    db.add(DecisionAudit(
        id=audit_id, procurement_request_id=request.id, decision_type="SUPPLIER_SELECTION",
        context={
            "selection_date": today.isoformat(),
            "shortage_quantity": messages.quantity_text(request.shortage_quantity),
            "required_date": request.required_date.isoformat(),
            # per supplier: the Supplier Service quantity and other requests' holds; options show the difference
            "availability": audit_record({a.supplier.supplier_name: {"available_qty": a.available,
                                                                     "held_quantity": a.held}
                                          for a in availability}),
            "options": options,
            "combinations": [audit_record(c) for c in selection.combinations],
        },
        decision=decision,
        reasoning_summary=selection.reasoning_summary,
        # llm_explanation: added after the commit (`wording.apply_explanation`); explanation only, never evidence
    ))
    return audit_id, facts


def audit_record(value, key: str = ""):
    """A selection value as plain JSON. Not Registered prices and costs stay empty, never zero. Quantities read as 500
    rather than 500.00; a Leg also records its cost."""
    if is_dataclass(value):  # shallow, so nested Legs keep their cost
        record = {f.name: getattr(value, f.name) for f in fields(value)}
        return audit_record(record | {"cost": value.cost} if isinstance(value, Leg) else record)
    if isinstance(value, dict):
        return {k: audit_record(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [audit_record(v, key) for v in value]
    if isinstance(value, Decimal):
        return messages.quantity_text(value) if key.endswith(("_qty", "quantity", "_available")) else str(value)
    if isinstance(value, (uuid.UUID, date)):
        return str(value)
    return value
