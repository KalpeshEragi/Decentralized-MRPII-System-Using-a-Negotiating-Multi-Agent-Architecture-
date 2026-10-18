"""What the Purchasing read API shows. Changes nothing."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent.messages import quantity_text
from app.purchasing_agent.models import (DecisionAudit, LegStatus, ProcurementRequest, PurchaseRequisition,
                                         RequestStatus)
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
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
        "legs": [_leg_view(db, leg, suppliers.get(leg.supplier_id)) for leg in legs],
        "selection": {
            "options": selection.context["options"], "combinations": selection.context.get("combinations", []),
            "decision": selection.decision,
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


def audit_view(db: Session, request_id: uuid.UUID) -> list[dict]:
    """Every decision recorded for the request, oldest first."""
    if db.get(ProcurementRequest, request_id) is None:
        raise AppError(ErrorCode.NOT_FOUND, "procurement request not found")
    records = db.scalars(select(DecisionAudit).where(DecisionAudit.procurement_request_id == request_id)
                         .order_by(DecisionAudit.created_at, DecisionAudit.id))
    return [
        {
            "id": str(r.id), "decision_type": r.decision_type, "context": r.context, "decision": r.decision,
            "reasoning_summary": r.reasoning_summary, "llm_explanation": r.llm_explanation,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


def scheduled_receipts(db: Session, item_id: uuid.UUID | None = None) -> list[dict]:
    """One receipt per committed Leg, earliest delivery first. An AGREED Leg that is not committed never appears."""
    query = (select(PurchaseRequisition, ProcurementRequest)
             .join(ProcurementRequest, PurchaseRequisition.procurement_request_id == ProcurementRequest.id)
             .where(PurchaseRequisition.status == LegStatus.COMMITTED,
                    ProcurementRequest.status == RequestStatus.COMMITTED)
             .order_by(PurchaseRequisition.agreed_delivery_date, PurchaseRequisition.id))
    if item_id is not None:
        query = query.where(ProcurementRequest.item_id == item_id)
    rows = db.execute(query).all()
    suppliers = supplier_service.get_suppliers(db, [leg.supplier_id for leg, _ in rows])
    items = {i: supplier_service.get_item(db, i) for i in {r.item_id for _, r in rows}}
    return [_receipt(leg, request, suppliers.get(leg.supplier_id), items[request.item_id]) for leg, request in rows]


def _receipt(leg: PurchaseRequisition, request: ProcurementRequest, supplier, item) -> dict:
    return {
        "leg_id": str(leg.id),
        "procurement_request_id": str(request.id),
        "request_ref": request.request_ref,
        "supplier": {"id": str(leg.supplier_id), "name": supplier.name if supplier else None},
        "item": {"id": str(request.item_id), "sku": item.sku if item else None, "name": item.name if item else None},
        "quantity": _number(leg.agreed_quantity),
        "delivery_date": leg.agreed_delivery_date.isoformat(),
    }


# -- supplier chat (test channel): what the supplier may see, never a price ------------------------------------------


def conversations(db: Session) -> list[dict]:
    """One conversation per Leg, newest first."""
    rows = db.execute(select(PurchaseRequisition, ProcurementRequest)
                      .join(ProcurementRequest, PurchaseRequisition.procurement_request_id == ProcurementRequest.id)
                      .order_by(PurchaseRequisition.created_at.desc(), PurchaseRequisition.id)).all()
    suppliers = supplier_service.get_suppliers(db, [leg.supplier_id for leg, _ in rows])
    items = {item_id: supplier_service.get_item(db, item_id) for item_id in {r.item_id for _, r in rows}}
    return [_conversation_header(db, leg, request, suppliers.get(leg.supplier_id), items[request.item_id])
            for leg, request in rows]


def conversation(db: Session, leg_id: uuid.UUID) -> dict:
    leg = db.get(PurchaseRequisition, leg_id)
    if leg is None:
        raise AppError(ErrorCode.NOT_FOUND, "leg not found")
    request = db.get(ProcurementRequest, leg.procurement_request_id)
    header = _conversation_header(db, leg, request, supplier_service.get_supplier(db, leg.supplier_id),
                                  supplier_service.get_item(db, request.item_id))
    session = negotiation_engine.session_view(db, leg.negotiation_session_id)
    return header | {
        "messages": [
            {k: m[k] for k in ("message_id", "sender_type", "message_type", "round_number", "text", "terms")}
            for m in session["messages"]
        ],
    }


def _conversation_header(db: Session, leg: PurchaseRequisition, request: ProcurementRequest, supplier, item) -> dict:
    session = negotiation_engine.session_state(db, leg.negotiation_session_id)
    return {
        "leg_id": str(leg.id),
        "request_ref": request.request_ref,
        "supplier": {"id": str(leg.supplier_id), "name": supplier.name if supplier else None},
        "item": {"sku": item.sku if item else None, "name": item.name if item else None},
        "quantity": _number(leg.allocated_quantity),
        "required_date": request.required_date.isoformat(),
        "round_count": session.round_count,
        "max_rounds": session.max_rounds,
        "leg_status": leg.status,
        "negotiation_status": session.status,
    }
