"""A tester stops a procurement manually (dev_docs/purchasing_agent/purchasing_agent_architecture.md §7.1), e.g. a stuck
negotiation. All changes run in one transaction.

Allowed only while the request is NEGOTIATING (confirmed 2026-10-18); otherwise refused and nothing changes. A proposed
agreement is rejected through approval instead. The request ends FAILED with the reason given; every PENDING or AGREED
Leg's supplier is told, the Leg ABORTED `manually_aborted` and its Engine session CANCELLED, which releases its hold.
Legs already FAILED or ABORTED stay.
No Constrained Quantity: no supplier limit caused the failure.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.purchasing_agent import messages
from app.purchasing_agent.models import (DecisionAudit, LegReason, LegStatus, ProcurementRequest,
                                         PurchaseRequisition, RequestStatus)
from app.purchasing_agent.negotiation import cancel_leg


def abort(db: Session, request_id: uuid.UUID, aborted_by: str, reason: str, now: datetime) -> None:
    # The same lock order as supplier replies and approval: request, then Legs.
    request = db.get(ProcurementRequest, request_id, with_for_update=True, populate_existing=True)
    if request is None:
        raise AppError(ErrorCode.NOT_FOUND, "procurement request not found")
    if request.status != RequestStatus.NEGOTIATING:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"the request is {request.status} and cannot be aborted",
                       [{"field": "status", "issue": f"is {request.status}"}])
    legs = list(db.scalars(select(PurchaseRequisition)
                           .where(PurchaseRequisition.procurement_request_id == request.id,
                                  PurchaseRequisition.status.in_(LegStatus.OPEN))
                           .order_by(PurchaseRequisition.created_at, PurchaseRequisition.id)
                           .with_for_update()
                           .execution_options(populate_existing=True)))
    for leg in legs:
        cancel_leg(db, leg, messages.MANUALLY_ABORTED_TEXT, LegReason.MANUALLY_ABORTED, now)
    request.status, request.status_reason = RequestStatus.FAILED, f"aborted by {aborted_by}: {reason}"
    db.add(DecisionAudit(
        procurement_request_id=request.id, decision_type="MANUAL_ABORT",
        context={"aborted_by": aborted_by, "reason": reason, "aborted_at": now.isoformat()},
        decision={"outcome": "FAILED", "request_status": request.status,
                  "aborted_legs": [str(leg.id) for leg in legs]},
        reasoning_summary=f"aborted manually by {aborted_by}; {len(legs)} Leg(s) aborted and their holds released",
    ))
    db.commit()
