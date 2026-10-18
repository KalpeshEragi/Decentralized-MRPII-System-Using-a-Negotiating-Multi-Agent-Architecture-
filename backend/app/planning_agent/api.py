"""Planning doors (planning_agent/3, backend_api.md §5): door 1 requests from Sales, door 2 shop-floor reports
(simulator), setup (simulator), and read-only views. Each write door only stores and queues; work runs in the runner."""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.doors import require_door_key
from app.core.errors import AppError, ErrorCode
from app.planning_agent import manager, reads

router = APIRouter(prefix="/planning", tags=["planning"])


class OrderBlock(BaseModel):
    product_id: str
    quantity: Decimal
    requested_date: date
    order_date: date


class PlanningRequest(BaseModel, extra="allow"):  # customer context is accepted and stored, never used to decide
    request_ref: str
    inquiry_id: str
    order: OrderBlock


class ShopFloorReport(BaseModel):
    report_id: str
    production_order_id: str
    kind: Literal["STARTED", "QUANTITY_COMPLETED"]
    quantity: Decimal | None = None


@router.post("/requests", status_code=202, dependencies=[Depends(require_door_key("planning_door_key"))])
def request(body: PlanningRequest, db: Session = Depends(get_db)) -> dict:
    status = manager.accept_request(db, body.model_dump(mode="json"))
    db.commit()
    return {"request_ref": body.request_ref, "status": status}


@router.post("/shop-floor/reports", status_code=202,
             dependencies=[Depends(require_door_key("simulation_door_key"))])
def shop_floor_report(body: ShopFloorReport, db: Session = Depends(get_db)) -> dict:
    if body.kind == "QUANTITY_COMPLETED" and (body.quantity is None or body.quantity <= 0):
        raise AppError(ErrorCode.VALIDATION_ERROR, "QUANTITY_COMPLETED needs a positive quantity")
    try:
        status = manager.record_shop_floor_report(db, body.report_id, body.production_order_id, body.kind,
                                                  body.quantity)
    except ValueError as error:
        raise AppError(ErrorCode.NOT_FOUND, str(error)) from error
    db.commit()
    return {"report_id": body.report_id, "status": status}


@router.post("/setup", dependencies=[Depends(require_door_key("simulation_door_key"))])
def setup(work_centers: dict[str, Decimal], db: Session = Depends(get_db)) -> dict:
    manager.setup(db, work_centers)
    db.commit()
    return {"status": "done", "work_centers": len(work_centers)}


@router.get("/orders/{order_ref}")
def order_plan(order_ref: str, db: Session = Depends(get_db)) -> dict:
    found = reads.get_order_plan(db, order_ref)
    if found is None:
        raise AppError(ErrorCode.NOT_FOUND, "no such order")
    return found


@router.get("/production-orders")
def production_orders(status: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return reads.production_orders(db, status)
