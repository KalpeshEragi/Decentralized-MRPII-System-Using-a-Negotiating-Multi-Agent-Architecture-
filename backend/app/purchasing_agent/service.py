"""Purchasing orchestration: a Procurement Request in, a selected supplier, one Leg and one Engine session with an
offer out. All changes for one request run in one transaction.

Decisions are made by `selection.py` (pure). This module reads the Supplier Service and the Negotiation Engine only
through their interfaces and writes only the `purchasing_agent` tables.

Tracer scope (ticket 01): the best priced single supplier only, using the supplier's available quantity (Purchasing's
own holds are not subtracted yet). Splits, the unpriced fallback and the Constrained Quantity come in later tickets.
"""

import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.negotiation_engine import service as negotiation_engine
from app.negotiation_engine.service import Participant
from app.purchasing_agent import messages
from app.purchasing_agent.models import DecisionAudit, ProcurementRequest, PurchaseRequisition, PurchasingContract
from app.purchasing_agent.selection import (
    ConsideredOption, Contract, Selection, SupplierOption, price_state, select_single_supplier,
)
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
    return now.astimezone(ZoneInfo(timezone)).date()


def _existing(db: Session, request_ref: str) -> uuid.UUID | None:
    return db.scalar(select(ProcurementRequest.id).where(ProcurementRequest.request_ref == request_ref))


def submit_request(db: Session, new: NewProcurementRequest, now: datetime, settings: Settings) -> Submitted:
    """Idempotent by `request_ref`: a repeated submission returns the existing request and changes nothing."""
    if (existing := _existing(db, new.request_ref)) is not None:
        return Submitted(existing, created=False)
    item = supplier_service.get_item(db, new.item_id)
    if item is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "the item is not in the Supplier Service catalogue",
                       [{"field": "item_id", "issue": "unknown item"}])

    request = ProcurementRequest(
        id=uuid.uuid4(), item_id=item.id, shortage_quantity=new.shortage_quantity, required_date=new.required_date,
        priority=new.priority, requested_by=new.requested_by, request_ref=new.request_ref, status="RECEIVED",
    )
    db.add(request)
    try:
        db.flush()
    except IntegrityError:  # the same request_ref arrived at the same time: the other submission won
        db.rollback()
        if (existing := _existing(db, new.request_ref)) is not None:
            return Submitted(existing, created=False)
        raise

    today = selection_date(now, settings.purchasing_timezone)
    selection = select_single_supplier(new.shortage_quantity, new.required_date, _supplier_options(db, item.id, today), today)
    _audit_selection(db, request, today, selection)

    if selection.winner is None:
        request.status = "FAILED"
        request.status_reason = selection.reasoning_summary
    else:
        _open_leg(db, request, item, selection.winner, now, settings)
        request.status = "NEGOTIATING"
        request.split_type = "SINGLE"
        request.cost_ranking_available = True
    db.commit()
    return Submitted(request.id, created=True)


def _supplier_options(db: Session, item_id: uuid.UUID, on: date) -> list[SupplierOption]:
    contracts: dict[uuid.UUID, list[Contract]] = defaultdict(list)
    for c in db.scalars(select(PurchasingContract).where(PurchasingContract.item_id == item_id)):
        contracts[c.supplier_id].append(Contract(c.id, c.unit_price, c.valid_from, c.valid_until, c.is_active))
    return [
        SupplierOption(
            supplier_id=s.supplier_id, supplier_name=s.supplier_name, is_active=s.supplier_is_active,
            lead_time_days=s.lead_time_days, min_order_qty=s.min_order_qty, available_qty=s.available_qty,
            price=price_state(contracts[s.supplier_id], on),
        )
        for s in supplier_service.supplier_items_for(db, item_id)
    ]


def _open_leg(db: Session, request: ProcurementRequest, item: supplier_service.ItemRecord, winner: ConsideredOption, now: datetime,
              settings: Settings) -> None:
    """One Engine session and one PENDING Leg for the supplier, then Purchasing's template offer."""
    quantity, delivery_date = winner.order_quantity, request.required_date
    terms = messages.offer_terms(quantity, delivery_date)
    session_id = negotiation_engine.open_session(
        db, session_type="PURCHASING_SUPPLIER", correlation_id=request.id,
        objective={"item_id": str(item.id), "sku": item.sku, **terms},
        participants=[
            Participant("AGENT", AGENT_CODE, "INITIATOR"),
            Participant("SUPPLIER", str(winner.supplier_id), "RESPONDENT"),
        ],
        max_rounds=settings.purchasing_max_rounds,
        response_deadline=now + timedelta(hours=settings.purchasing_response_deadline_hours),
        now=now,
    )
    db.add(PurchaseRequisition(
        procurement_request_id=request.id, supplier_id=winner.supplier_id, purchasing_contract_id=winner.contract_id,
        unit_price_at_selection=winner.unit_price, allocated_quantity=quantity, negotiation_session_id=session_id,
        status="PENDING",
    ))
    negotiation_engine.append_message(
        db, session_id, message_id=uuid.uuid4(), sender_type="AGENT", sender_ref=AGENT_CODE, message_type="OFFER",
        text=messages.offer_text(winner.supplier_name, item.name, item.sku, quantity, delivery_date),
        terms=terms,
    )


def _audit_selection(db: Session, request: ProcurementRequest, today: date, selection: Selection) -> None:
    winner = selection.winner
    db.add(DecisionAudit(
        procurement_request_id=request.id, decision_type="SUPPLIER_SELECTION",
        context={
            "selection_date": today.isoformat(),
            "shortage_quantity": messages.quantity_text(request.shortage_quantity),
            "required_date": request.required_date.isoformat(),
            "options": [option_record(o) for o in selection.options],
        },
        decision={
            "outcome": selection.outcome,
            "supplier_id": str(winner.supplier_id) if winner else None,
            "order_quantity": messages.quantity_text(winner.order_quantity) if winner else None,
            "total_cost": str(winner.total_cost) if winner else None,
        },
        reasoning_summary=selection.reasoning_summary,
    ))


def option_record(option: ConsideredOption) -> dict:
    """An option as plain JSON. Not Registered prices stay empty, never zero."""
    record = asdict(option)
    for key, value in record.items():
        if isinstance(value, Decimal):
            record[key] = messages.quantity_text(value) if key.endswith(("_qty", "_quantity")) else str(value)
        elif isinstance(value, (uuid.UUID, date)):
            record[key] = str(value)
    return record
