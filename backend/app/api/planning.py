"""Plans API: run the deterministic plan for an order, read the persisted plan and its shortages, and the human
approval of plan attempts (C8): list attempts, approve (COMMIT, D8) or reject (replan, at most 2 attempts)."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.domain import PlanSnapshot
from app.agents import workflow
from app.services import approval_service, order_service, planning_service, supplier_service

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanRequest(BaseModel):
    order_id: uuid.UUID


class RejectRequest(BaseModel):
    reason: str | None = None


@router.post("", status_code=201, response_model=PlanSnapshot)
def create_plan(data: PlanRequest, db: Session = Depends(get_db)):
    """Finished-goods netting -> MPS -> capacity -> BOM -> MRP; stores the result and returns it."""
    return planning_service.run_plan(db, data.order_id)


@router.get("/{order_id}", response_model=PlanSnapshot)
def get_plan(order_id: uuid.UUID, db: Session = Depends(get_db)):
    return planning_service.get_plan(db, order_id)


@router.get("/{order_id}/shortages")
def get_shortages(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Persisted shortages, each with deterministic supplier-feasibility inputs (no supplier is selected here)."""
    plan = planning_service.get_plan(db, order_id)
    return [
        {"shortage": shortage.model_dump(mode="json"), "suppliers": supplier_service.feasibility(db, shortage, plan.planning_date)}
        for shortage in plan.shortages
    ]


@router.get("/{order_id}/attempts")
def list_attempts(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Planning attempts (C8) with approval_status, approvable, blockers and negotiations."""
    order_service.get_order(db, order_id)  # 404 for an unknown order
    return approval_service.attempts(db, order_id)


@router.post("/{order_id}/attempts/{attempt_number}/approve")
def approve_attempt(order_id: uuid.UUID, attempt_number: int, db: Session = Depends(get_db)):
    """The human approves: COMMIT every agreement, re-plan with the committed receipts, reserve stock (D8)."""
    return workflow.approve_plan(db, order_id, attempt_number)


@router.post("/{order_id}/attempts/{attempt_number}/reject")
def reject_attempt(order_id: uuid.UUID, attempt_number: int, data: RejectRequest | None = None,
                   db: Session = Depends(get_db)):
    """The human rejects: uncommitted agreements are aborted; Planning replans (attempt 2), or after attempt 2 the
    order needs human intervention."""
    return workflow.reject_plan(db, order_id, attempt_number, data.reason if data else None)
