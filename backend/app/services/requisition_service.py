"""Purchase requisitions (`purchasing.purchase_requisitions`). Procurement belongs to the Purchasing Agent, so only it
may create or update them. No price/cost; purchase orders are out of scope for the 25%.

One requisition per negotiation session. Its id is derived from the session id (uuid5), so the two are linked without
an extra column. Status values are working values, not yet in a contract: OPEN, AGREEMENT_PROPOSED, REJECTED, FAILED
(they follow the session; COMMIT and what follows it belong to the approval workflow, C8).
"""

import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.purchasing import PurchaseRequisition
from app.schemas.domain import Shortage
from app.services import audit_service
from app.services.audit_service import AGENT_PURCHASING, DecisionType

OPEN = "OPEN"
STATUSES = frozenset({OPEN, "AGREEMENT_PROPOSED", "REJECTED", "FAILED"})


def requisition_id(negotiation_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(negotiation_id, "purchase-requisition")


def _owner_only(agent_code: str) -> None:
    if agent_code != AGENT_PURCHASING:
        raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, "purchase requisitions belong to the Purchasing Agent")


def create(db: Session, negotiation_id: uuid.UUID, shortage: Shortage, agent_code: str) -> PurchaseRequisition:
    """The requisition for the session's shortage (idempotent). Flushed, not committed; audited as REQUISITION_CREATED."""
    _owner_only(agent_code)
    existing = db.get(PurchaseRequisition, requisition_id(negotiation_id))
    if existing is not None:
        return existing
    row = PurchaseRequisition(
        id=requisition_id(negotiation_id),
        item_id=uuid.UUID(shortage.item_id),
        quantity_required=shortage.shortage_quantity,
        required_by=shortage.required_by,
        priority=shortage.priority,
        status=OPEN,
        created_by_agent=audit_service.agent_uuid(db, agent_code),
    )
    db.add(row)
    db.flush()
    audit_service.record(
        db,
        agent_code,
        DecisionType.REQUISITION_CREATED,
        {"order_id": shortage.order_id, "item_id": shortage.item_id, "negotiation_id": str(negotiation_id)},
        {"requisition_id": str(row.id), "quantity_required": shortage.shortage_quantity,
         "required_by": shortage.required_by, "priority": shortage.priority},
        f"Requisition for {shortage.shortage_quantity} of item {shortage.item_id} by {shortage.required_by}.",
    )
    return row


def set_status(db: Session, negotiation_id: uuid.UUID, status: str, agent_code: str) -> None:
    _owner_only(agent_code)
    if status not in STATUSES:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"unknown requisition status {status}")
    row = db.get(PurchaseRequisition, requisition_id(negotiation_id))
    if row is not None:
        row.status = status
        db.flush()


def get(db: Session, negotiation_id: uuid.UUID) -> dict | None:
    row = db.get(PurchaseRequisition, requisition_id(negotiation_id), populate_existing=True)
    if row is None:
        return None
    return {
        "id": str(row.id),
        "item_id": str(row.item_id),
        "quantity_required": row.quantity_required,
        "required_by": row.required_by,
        "priority": row.priority,
        "status": row.status,
        "created_by_agent": str(row.created_by_agent) if row.created_by_agent else None,
    }
