"""Customer orders: create and read. Validation rules are the C1 invariants; everything else is persistence."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import core as core_models
from app.models import sales
from app.schemas import domain
from app.services import audit_service
from app.services.audit_service import DecisionType


class OrderLineIn(BaseModel):
    item_id: uuid.UUID
    quantity: Annotated[Decimal, Field(gt=0)]


class OrderCreate(BaseModel):
    """Either `customer_id` or `customer_name` (found or created). `order_number` is generated when omitted."""

    order_number: Annotated[str, Field(min_length=1)] | None = None
    customer_id: uuid.UUID | None = None
    customer_name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    order_date: date
    due_date: date
    priority: Annotated[int, Field(ge=1, le=5)]  # 1 = highest
    lines: Annotated[list[OrderLineIn], Field(min_length=1)]


def _to_domain(order: sales.CustomerOrder, lines: list[sales.CustomerOrderItem]) -> domain.CustomerOrder:
    return domain.CustomerOrder(
        id=str(order.id),
        order_number=order.order_number,
        customer_id=str(order.customer_id),
        order_date=order.order_date,
        due_date=order.due_date,
        priority=order.priority,
        status=domain.OrderStatus(order.status or domain.OrderStatus.NEW),
        lines=[domain.OrderLine(item_id=str(line.item_id), quantity=line.quantity) for line in lines],
    )


def get_order(db: Session, order_id: uuid.UUID) -> domain.CustomerOrder:
    order = db.get(sales.CustomerOrder, order_id)
    if order is None:
        raise AppError(ErrorCode.NOT_FOUND, "order not found")
    lines = list(
        db.scalars(
            select(sales.CustomerOrderItem).where(sales.CustomerOrderItem.order_id == order_id).order_by(sales.CustomerOrderItem.id)
        )
    )
    return _to_domain(order, lines)


def list_orders(db: Session) -> list[domain.CustomerOrder]:
    ids = db.scalars(select(sales.CustomerOrder.id).order_by(sales.CustomerOrder.order_number))
    return [get_order(db, order_id) for order_id in list(ids)]


def _customer_by_name(db: Session, name: str) -> uuid.UUID:
    customer_id = db.scalar(select(sales.Customer.id).where(sales.Customer.name == name))
    if customer_id is None:
        customer = sales.Customer(id=uuid.uuid4(), name=name, location="", contact_info={})
        db.add(customer)
        db.flush()
        customer_id = customer.id
    return customer_id


def _next_order_number(db: Session) -> str:
    numbers = db.scalars(select(sales.CustomerOrder.order_number).where(sales.CustomerOrder.order_number.like("SO-%")))
    highest = max((int(n[3:]) for n in numbers if n[3:].isdigit()), default=0)
    return f"SO-{highest + 1:04d}"


def overview(db: Session) -> list[dict]:
    """Orders with their customer name, for display (planning priority first, then due date)."""
    customers = dict(db.execute(select(sales.Customer.id, sales.Customer.name)).all())
    orders = sorted(list_orders(db), key=lambda o: (o.priority, o.due_date, o.order_number))
    return [{**o.model_dump(mode="json"), "customer_name": customers.get(uuid.UUID(o.customer_id))} for o in orders]


def create_order(db: Session, data: OrderCreate) -> domain.CustomerOrder:
    if data.due_date < data.order_date:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "due_date must be on or after order_date",
            [{"field": "due_date", "issue": "must be >= order_date"}],
        )
    if data.customer_id is None and data.customer_name is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "customer_id or customer_name is required",
                       [{"field": "customer_name", "issue": "required"}])
    if data.customer_id is None:
        data = data.model_copy(update={"customer_id": _customer_by_name(db, data.customer_name.strip())})
    if db.get(sales.Customer, data.customer_id) is None:
        raise AppError(ErrorCode.NOT_FOUND, "customer not found")
    if data.order_number is None:
        data = data.model_copy(update={"order_number": _next_order_number(db)})
    if db.scalar(select(sales.CustomerOrder.id).where(sales.CustomerOrder.order_number == data.order_number)):
        raise AppError(ErrorCode.CONFLICT, f"order number {data.order_number} already exists")
    for index, line in enumerate(data.lines):
        item = db.get(core_models.Item, line.item_id)
        if item is None:
            raise AppError(ErrorCode.NOT_FOUND, f"item {line.item_id} not found", [{"field": f"lines[{index}].item_id", "issue": "unknown item"}])
        if item.item_type != domain.ItemType.FINISHED_PRODUCT:
            raise AppError(
                ErrorCode.BUSINESS_RULE_VIOLATION,
                "order lines must be finished products",
                [{"field": f"lines[{index}].item_id", "issue": f"{item.sku} is a {item.item_type.value}"}],
            )

    order = sales.CustomerOrder(
        id=uuid.uuid4(),
        customer_id=data.customer_id,
        order_number=data.order_number,
        order_date=data.order_date,
        due_date=data.due_date,
        priority=data.priority,
        status=domain.OrderStatus.NEW.value,
    )
    db.add(order)
    db.flush()
    lines = [sales.CustomerOrderItem(order_id=order.id, item_id=line.item_id, quantity=line.quantity) for line in data.lines]
    db.add_all(lines)
    db.flush()
    try:
        created = _to_domain(order, lines)
    except ValidationError as exc:  # unreachable after the checks above; keeps the C1 invariants authoritative
        raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    audit_service.record(
        db,
        audit_service.AGENT_PLANNING,
        DecisionType.ORDER_RECEIVED,
        {"order_id": created.id},
        {"order_number": created.order_number, "due_date": created.due_date, "priority": created.priority},
        f"Order {created.order_number} received and handed to Production Planning.",
    )
    db.commit()
    return created


def set_status(db: Session, order_id: uuid.UUID, status: domain.OrderStatus) -> None:
    order = db.get(sales.CustomerOrder, order_id)
    if order is None:
        raise AppError(ErrorCode.NOT_FOUND, "order not found")
    order.status = status.value
