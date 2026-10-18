"""A human's decision on a proposed Procurement Agreement (dev_docs/purchasing_agent/purchasing_agent_architecture.md
§7.6). All changes for one decision run in one transaction.

- Approve → every Leg COMMITTED and the request COMMITTED; committed Legs are the scheduled receipts.
- Reject → request APPROVAL_REJECTED; every supplier is told, every Leg ABORTED `approval_rejected` and its Engine
  session CANCELLED (like every other aborted Leg, §7.4–7.5), which releases its hold.
Legs dropped on reallocation (`no_longer_needed`) are not part of the agreement and are left as they are.
Either is allowed only while the request is AGREEMENT_PROPOSED and every Leg is AGREED; otherwise the decision is
refused and nothing changes. On approval the Engine sessions stay AGREED.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.purchasing_agent import messages
from app.purchasing_agent.messages import quantity_text
from app.purchasing_agent.models import (DecisionAudit, LegReason, LegStatus, ProcurementRequest,
                                         PurchaseRequisition, RequestStatus)
from app.purchasing_agent.negotiation import cancel_leg


def approve(db: Session, request_id: uuid.UUID, decided_by: str, now: datetime) -> None:
    request, legs = _proposed(db, request_id)
    for leg in legs:
        leg.status = LegStatus.COMMITTED
    request.status = RequestStatus.COMMITTED
    _decide(db, request, legs, decided_by, now, "APPROVED",
            f"approved by {decided_by}; {len(legs)} Leg(s) committed as scheduled receipts")


def reject(db: Session, request_id: uuid.UUID, decided_by: str, now: datetime) -> None:
    request, legs = _proposed(db, request_id)
    for leg in legs:
        cancel_leg(db, leg, messages.APPROVAL_REJECTED_TEXT, LegReason.APPROVAL_REJECTED, now)
    request.status, request.status_reason = RequestStatus.APPROVAL_REJECTED, f"approval rejected by {decided_by}"
    _decide(db, request, legs, decided_by, now, "REJECTED",
            f"rejected by {decided_by}; {len(legs)} Leg(s) aborted and their holds released")


def _proposed(db: Session, request_id: uuid.UUID) -> tuple[ProcurementRequest, list[PurchaseRequisition]]:
    """The request and its Legs, locked (the same order as supplier replies: request, then Legs), if the agreement
    can still be decided."""
    request = db.get(ProcurementRequest, request_id, with_for_update=True)
    if request is None:
        raise AppError(ErrorCode.NOT_FOUND, "procurement request not found")
    if request.status != RequestStatus.AGREEMENT_PROPOSED:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"the request is {request.status}, not AGREEMENT_PROPOSED",
                       [{"field": "status", "issue": f"is {request.status}"}])
    legs = [leg for leg in db.scalars(select(PurchaseRequisition)
                                      .where(PurchaseRequisition.procurement_request_id == request.id)
                                      .order_by(PurchaseRequisition.created_at, PurchaseRequisition.id)
                                      .with_for_update())
            if leg.status_reason != LegReason.NO_LONGER_NEEDED]  # dropped on reallocation: not part of the agreement
    if stale := [leg for leg in legs if leg.status != LegStatus.AGREED]:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, "not every Leg is AGREED",
                       [{"field": f"legs.{leg.id}.status", "issue": f"is {leg.status}"} for leg in stale])
    return request, legs


def _decide(db: Session, request: ProcurementRequest, legs: list[PurchaseRequisition], decided_by: str,
            now: datetime, outcome: str, summary: str) -> None:
    request.decided_at = now
    db.add(DecisionAudit(
        procurement_request_id=request.id, decision_type="APPROVAL",
        context={
            "decided_by": decided_by,
            "legs": [
                {"leg_id": str(leg.id), "supplier_id": str(leg.supplier_id),
                 "quantity": quantity_text(leg.agreed_quantity),
                 "delivery_date": leg.agreed_delivery_date.isoformat()}
                for leg in legs
            ],
        },
        decision={"outcome": outcome, "request_status": request.status},
        reasoning_summary=summary,
    ))
    db.commit()
