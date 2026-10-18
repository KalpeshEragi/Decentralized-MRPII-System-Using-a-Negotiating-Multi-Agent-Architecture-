"""Response deadlines (dev_docs/purchasing_agent/purchasing_agent_architecture.md §7.1). Each message awaiting a
supplier reply sets the Leg's deadline in its Engine session (`negotiation.py`, `service.py`). There is no scheduler:
the deadline is checked when the request or one of its Legs is next read or acted on, by calling `expire_overdue`
first.

A PENDING Leg past its deadline: the supplier is told, the Engine session TIMED_OUT (`timeout`), the Leg FAILED
`timeout`, and with it the procurement (all or nothing, §7.5: `fail_procurement`). If several Legs are overdue, the
first one fails the procurement and the others are aborted with it. All changes run in one transaction.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent import messages
from app.purchasing_agent.models import (DecisionAudit, LegReason, LegStatus, ProcurementRequest,
                                         PurchaseRequisition, RequestStatus)
from app.purchasing_agent.negotiation import fail_procurement
from app.purchasing_agent.service import AGENT_CODE, selection_date


def expire_overdue(db: Session, request_id: uuid.UUID, now: datetime, settings: Settings) -> bool:
    """Time out the request's first overdue Leg, if any. Returns True when it did (and committed). Call it before any
    other change in the transaction: it commits or rolls back."""
    if not _overdue(db, request_id, now):  # the common case: no lock taken
        return False
    # Lock the request, then its Legs (the order every writer uses), and check again: a reply may have come first.
    request = db.get(ProcurementRequest, request_id, with_for_update=True, populate_existing=True)
    overdue = _overdue(db, request_id, now, lock=True)
    if request.status != RequestStatus.NEGOTIATING or not overdue:
        db.rollback()
        return False
    leg, deadline = overdue[0]
    offer = negotiation_engine.current_offer(db, leg.negotiation_session_id)
    cause = offer.message_id if offer else None  # the offer left unanswered
    negotiation_engine.append_message(
        db, leg.negotiation_session_id, message_id=uuid.uuid4(), sender_type="AGENT", sender_ref=AGENT_CODE,
        message_type="CONFIRMATION", text=messages.TIMEOUT_TEXT, causation_id=cause,
    )
    negotiation_engine.close_session(db, leg.negotiation_session_id, "TIMED_OUT", LegReason.TIMEOUT, now)
    leg.status, leg.status_reason = LegStatus.FAILED, LegReason.TIMEOUT
    failure = fail_procurement(db, request, leg, cause, now, selection_date(now, settings.purchasing_timezone))
    db.add(DecisionAudit(
        procurement_request_id=request.id, decision_type="RESPONSE_DEADLINE",
        context={"leg_id": str(leg.id), "supplier_id": str(leg.supplier_id),
                 "response_deadline": deadline.isoformat(), "checked_at": now.isoformat()},
        decision={"outcome": "FAILED", "reason": LegReason.TIMEOUT, "request_status": request.status,
                  "constrained_quantity": messages.quantity_text(failure.constrained_quantity),
                  "aborted_legs": [str(leg_id) for leg_id in failure.aborted_leg_ids]},
        reasoning_summary="the supplier did not reply by the response deadline: the Leg failed and with it the "
                          "procurement",
    ))
    db.commit()
    return True


def expire_overdue_for_leg(db: Session, leg_id: uuid.UUID, now: datetime, settings: Settings) -> bool:
    leg = db.get(PurchaseRequisition, leg_id)
    return leg is not None and expire_overdue(db, leg.procurement_request_id, now, settings)


def expire_all_overdue(db: Session, now: datetime, settings: Settings) -> None:
    """Every request with a PENDING Leg (the supplier chat's conversation list)."""
    request_ids = db.scalars(select(PurchaseRequisition.procurement_request_id)
                             .where(PurchaseRequisition.status == LegStatus.PENDING).distinct()).all()
    for request_id in request_ids:
        expire_overdue(db, request_id, now, settings)


def expire_holds_on_item(db: Session, item_id: uuid.UUID, now: datetime, settings: Settings,
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
        expire_overdue(db, request_id, now, settings)
    db.rollback()  # end the read-only transaction: the caller starts clean


def expire_holds_for_leg(db: Session, leg_id: uuid.UUID, now: datetime, settings: Settings) -> None:
    """`expire_holds_on_item` for the item of the Leg's request, other than that request."""
    request = db.scalar(select(ProcurementRequest)
                        .join(PurchaseRequisition, PurchaseRequisition.procurement_request_id == ProcurementRequest.id)
                        .where(PurchaseRequisition.id == leg_id))
    if request is not None:
        expire_holds_on_item(db, request.item_id, now, settings, except_request_id=request.id)


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
