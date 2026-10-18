"""Planning's read module (IB-2): the only thing other agents may import from the Planning Agent. Read-only; plain
data. Warehouse uses it for its daily routine (which kits to issue, what to ship)."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.planning_agent.models import CustomerDemand, ProductionOrder


def _order(o: ProductionOrder) -> dict:
    return {"id": str(o.id), "item_id": o.item_id, "quantity": str(o.quantity), "start_day": o.start_day.isoformat(),
            "end_day": o.end_day.isoformat(), "status": o.status, "for_kind": o.for_kind, "for_ref": o.for_ref,
            "demand_id": str(o.demand_id), "quantity_completed": str(o.quantity_completed)}


def production_orders_starting(db: DbSession, day: date) -> list[dict]:
    """Released orders that start on `day` (their kits are issued that morning, WB-3)."""
    return [_order(o) for o in db.scalars(select(ProductionOrder).where(
        ProductionOrder.status == "RELEASED", ProductionOrder.start_day == day).order_by(ProductionOrder.id))]


def production_orders(db: DbSession, status: str | None = None) -> list[dict]:
    query = select(ProductionOrder).order_by(ProductionOrder.start_day, ProductionOrder.id)
    if status:
        query = query.where(ProductionOrder.status == status)
    return [_order(o) for o in db.scalars(query)]


def shipments_due(db: DbSession, day: date) -> list[dict]:
    """Committed customer demands due for delivery on or before `day` and not shipped yet."""
    return [{"order_ref": str(d.id), "item_id": d.item_id, "quantity": str(d.committed_quantity - d.quantity_shipped),
             "delivery_day": d.committed_day.isoformat()}
            for d in db.scalars(select(CustomerDemand).where(CustomerDemand.status == "COMMITTED",
                                                             CustomerDemand.committed_day <= day)
                                .order_by(CustomerDemand.committed_day, CustomerDemand.id))]


def get_order_plan(db: DbSession, order_ref: str) -> dict | None:
    """The plan of one customer demand, by Planning's demand id, Sales request_ref or Sales order number."""
    demand = db.scalar(select(CustomerDemand).where(
        (CustomerDemand.request_ref == order_ref) | (CustomerDemand.sales_order_number == order_ref)))
    if demand is None:
        try:
            demand = db.get(CustomerDemand, uuid.UUID(order_ref))
        except ValueError:
            return None
    if demand is None:
        return None
    orders = db.scalars(select(ProductionOrder).where(ProductionOrder.demand_id == demand.id,
                                                      ProductionOrder.status != "CANCELLED")).all()
    return {"demand_id": str(demand.id), "request_ref": demand.request_ref, "order_number": demand.sales_order_number,
            "item_id": demand.item_id, "quantity": str(demand.quantity), "requested_day": demand.requested_day.isoformat(),
            "status": demand.status,
            "committed_quantity": str(demand.committed_quantity) if demand.committed_quantity is not None else None,
            "committed_day": demand.committed_day.isoformat() if demand.committed_day else None,
            "production_orders": [_order(o) for o in orders]}
