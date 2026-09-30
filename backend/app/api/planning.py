"""Plans API: run the deterministic plan for an order, read the persisted plan and its shortages."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.domain import PlanSnapshot
from app.services import planning_service, supplier_service

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanRequest(BaseModel):
    order_id: uuid.UUID


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
