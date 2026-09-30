"""Orders API. Thin: validation and rules live in `order_service` and the C1 domain shapes."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.domain import CustomerOrder
from app.services import order_service
from app.services.order_service import OrderCreate

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", status_code=201, response_model=CustomerOrder)
def create_order(data: OrderCreate, db: Session = Depends(get_db)):
    return order_service.create_order(db, data)


@router.get("", response_model=list[CustomerOrder])
def list_orders(db: Session = Depends(get_db)):
    return order_service.list_orders(db)


@router.get("/{order_id}", response_model=CustomerOrder)
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    return order_service.get_order(db, order_id)
