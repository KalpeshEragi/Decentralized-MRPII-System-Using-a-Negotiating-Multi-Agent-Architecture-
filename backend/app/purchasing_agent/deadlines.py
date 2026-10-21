"""Response deadlines (dev_docs/purchasing_agent/purchasing_agent_architecture.md §7.1). Each message awaiting a
supplier reply sets the Leg's deadline in its Engine session (`negotiation.py`, `service.py`). There is no scheduler:
the deadline is checked when the request or one of its Legs is next read or acted on, by calling `expire_overdue`
first.

A check only records (ADR-003): every PENDING Leg past its deadline is told, its Engine session TIMED_OUT (`timeout`)
and the Leg FAILED `timeout`, which releases its hold; one RESPONSE_DEADLINE audit each. The request stays NEGOTIATING
and, when its open Legs no longer cover the shortage, shows `re_sourcing_needed`. A read never creates Legs or sends
offers: re-sourcing runs on the next write for the request (`negotiation.re_source`). All changes run in one
transaction.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent import messages
from app.purchasing_agent.models import (DecisionAudit, LegReason, LegStatus, ProcurementRequest,
                                         PurchaseRequisition, RequestStatus)
from app.purchasing_agent.negotiation import re_sourcing_needed
from app.purchasing_agent.service import AGENT_CODE


def expire_overdue(db: Session, request_id: uuid.UUID, now: datetime) -> bool:
    """Record every overdue Leg of the request as timed out. Returns True when it did (and committed). Call it before
    any other change in the transaction: it commits or rolls back."""
    if not _overdue(db, request_id, now):  # the common case: no lock taken
        return False
    # Lock the request, then its Legs (the order every writer uses), and check again: a reply may have come first.
    request = db.get(ProcurementRequest, request_id, with_for_update=True, populate_existing=True)
    overdue = _overdue(db, request_id, now, lock=True)
    if request.status != RequestStatus.NEGOTIATING or not overdue:
        db.rollback()
        return False
    for leg, _ in overdue:
        offer = negotiation_engine.current_offer(db, leg.negotiation_session_id)
        cause = offer.message_id if offer else None  # the offer left unanswered
        negotiation_engine.append_message(
            db, leg.negotiation_session_id, message_id=uuid.uuid4(), sender_type="AGENT", sender_ref=AGENT_CODE,
            message_type="CONFIRMATION", text=messages.TIMEOUT_TEXT, causation_id=cause,
        )
        negotiation_engine.close_session(db, leg.negotiation_session_id, "TIMED_OUT", LegReason.TIMEOUT, now)
        leg.status, leg.status_reason = LegStatus.FAILED, LegReason.TIMEOUT
    db.flush()
    needed = re_sourcing_needed(db, request)
    for leg, deadline in overdue:
        db.add(DecisionAudit(
            procurement_request_id=request.id, decision_type="RESPONSE_DEADLINE",
            context={"leg_id": str(leg.id), "supplier_id": str(leg.supplier_id),
                     "response_deadline": deadline.isoformat(), "checked_at": now.isoformat()},
            decision={"outcome": "FAILED", "reason": LegReason.TIMEOUT, "request_status": request.status,
                      "re_sourcing_needed": needed},
            reasoning_summary="the supplier did not reply by the response deadline: the Leg failed; the request is "
                              "re-sourced on its next write",
        ))
    db.commit()
    return True


def expire_overdue_for_leg(db: Session, leg_id: uuid.UUID, now: datetime) -> bool:
    leg = db.get(PurchaseRequisition, leg_id)
    return leg is not None and expire_overdue(db, leg.procurement_request_id, now)


def expire_all_overdue(db: Session, now: datetime) -> None:
    """Every request with a PENDING Leg (the supplier chat's conversation list)."""
    request_ids = db.scalars(select(PurchaseRequisition.procurement_request_id)
                             .where(PurchaseRequisition.status == LegStatus.PENDING).distinct()).all()
    for request_id in request_ids:
        expire_overdue(db, request_id, now)


def expire_holds_on_item(db: Session, item_id: uuid.UUID, now: datetime,
                         except_request_id: uuid.UUID | None = None) -> None:
    """Every other request for the item with a PENDING Leg: its overdue Legs are timed out, releasing their holds on
    the item's supplier-items. Call it before availability is calculated for a selection or reallocation (§7.1)."""
    query = (select(PurchaseRequisition.procurement_request_id)
             .join(ProcurementRequest, ProcurementRequest.id == PurchaseRequisition.procurement_request_id)
             .where(ProcurementRequest.item_id == item_id, ProcurementRequest.status == RequestStatus.NEGOTIATING,
                    PurchaseRequisition.status == LegStatus.PENDING)
             .distinct())
    if except_request_id is not None:
        query = query.where(PurchaseRequisition.procurement_request_id != except_request_id)
    for request_id in db.scalars(query).all():
        expire_overdue(db, request_id, now)
    db.rollback()  # end the read-only transaction: the caller starts clean


def expire_holds_for_request(db: Session, request_id: uuid.UUID, now: datetime) -> None:
    """`expire_holds_on_item` for the request's item, other than that request."""
    request = db.get(ProcurementRequest, request_id)
    if request is not None:
        expire_holds_on_item(db, request.item_id, now, except_request_id=request.id)


def expire_holds_for_leg(db: Session, leg_id: uuid.UUID, now: datetime) -> None:
    """`expire_holds_on_item` for the item of the Leg's request, other than that request."""
    request = db.scalar(select(ProcurementRequest)
                        .join(PurchaseRequisition, PurchaseRequisition.procurement_request_id == ProcurementRequest.id)
                        .where(PurchaseRequisition.id == leg_id))
    if request is not None:
        expire_holds_on_item(db, request.item_id, now, except_request_id=request.id)


def _overdue(db: Session, request_id: uuid.UUID, now: datetime,
             lock: bool = False) -> list[tuple[PurchaseRequisition, datetime]]:
    """The request's PENDING Legs past their deadline, oldest Leg first, each with its deadline."""
    query = (select(PurchaseRequisition)
             .where(PurchaseRequisition.procurement_request_id == request_id, PurchaseRequisition.status == LegStatus.PENDING)
             .order_by(PurchaseRequisition.created_at, PurchaseRequisition.id)
             .execution_options(populate_existing=True))
    legs = db.scalars(query.with_for_update() if lock else query).all()
    found = [(leg, negotiation_engine.missed_deadline(db, leg.negotiation_session_id, now)) for leg in legs]
    return [(leg, deadline) for leg, deadline in found if deadline is not None]
