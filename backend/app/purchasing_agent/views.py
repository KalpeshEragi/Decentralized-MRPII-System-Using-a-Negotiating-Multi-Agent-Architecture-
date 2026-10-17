"""What the Purchasing read API shows. Changes nothing."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent.messages import quantity_text
from app.purchasing_agent.models import DecisionAudit, ProcurementRequest, PurchaseRequisition
from app.supplier_service import service as supplier_service


def _number(value) -> str | None:
    return quantity_text(value) if value is not None else None


def request_view(db: Session, request_id: uuid.UUID) -> dict:
    request = db.get(ProcurementRequest, request_id)
    if request is None:
        raise AppError(ErrorCode.NOT_FOUND, "procurement request not found")
    item = supplier_service.get_item(db, request.item_id)
    legs = list(db.scalars(select(PurchaseRequisition).where(PurchaseRequisition.procurement_request_id == request.id)
                           .order_by(PurchaseRequisition.created_at, PurchaseRequisition.id)))
    suppliers = supplier_service.get_suppliers(db, [leg.supplier_id for leg in legs])
    selection = db.scalar(select(DecisionAudit).where(
        DecisionAudit.procurement_request_id == request.id, DecisionAudit.decision_type == "SUPPLIER_SELECTION",
    ).order_by(DecisionAudit.created_at.desc()).limit(1))
    return {
        "id": str(request.id),
        "request_ref": request.request_ref,
        "item": {"id": str(request.item_id), "sku": item.sku if item else None, "name": item.name if item else None},
        "shortage_quantity": _number(request.shortage_quantity),
        "required_date": request.required_date.isoformat(),
        "priority": request.priority,
        "requested_by": request.requested_by,
        "status": request.status,
        "status_reason": request.status_reason,
        "split_type": request.split_type,
        "cost_ranking_available": request.cost_ranking_available,
        "constrained_quantity": _number(request.constrained_quantity),
        "legs": [_leg_view(db, leg, suppliers.get(leg.supplier_id)) for leg in legs],
        "selection": {
            "options": selection.context["options"], "decision": selection.decision,
            "reasoning_summary": selection.reasoning_summary,
        } if selection else None,
    }


def _leg_view(db: Session, leg: PurchaseRequisition, supplier) -> dict:
    return {
        "id": str(leg.id),
        "supplier": {"id": str(leg.supplier_id), "name": supplier.name if supplier else None},
        "purchasing_contract_id": str(leg.purchasing_contract_id) if leg.purchasing_contract_id else None,
        "unit_price_at_selection": str(leg.unit_price_at_selection) if leg.unit_price_at_selection is not None else None,
        "allocated_quantity": _number(leg.allocated_quantity),
        "quantity_cap": _number(leg.quantity_cap),
        "agreed_quantity": _number(leg.agreed_quantity),
        "agreed_delivery_date": leg.agreed_delivery_date.isoformat() if leg.agreed_delivery_date else None,
        "status": leg.status,
        "status_reason": leg.status_reason,
        "negotiation": negotiation_engine.session_view(db, leg.negotiation_session_id),
    }
