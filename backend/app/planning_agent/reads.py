"""Planning's read module (IB-2): the only thing other agents may import from the Planning Agent. Read-only; plain
data. Warehouse uses it for its daily routine (which kits to issue, what to ship)."""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.core.owner_tables import differences, ledger_sums
from app.planning_agent.models import (Case, CustomerDemand, MachineHoursLedger, ProductionOrder, WorkCenter,
                                       WorkCenterDay)


def _order(o: ProductionOrder) -> dict:
    return {"id": str(o.id), "item_id": o.item_id, "quantity": str(o.quantity), "start_day": o.start_day.isoformat(),
            "end_day": o.end_day.isoformat(), "status": o.status, "for_kind": o.for_kind, "for_ref": o.for_ref,
            "demand_id": str(o.demand_id), "quantity_completed": str(o.quantity_completed),
            "work_centers": sorted({step["work_center"] for step in o.steps})}


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
            "sales_inquiry_id": demand.sales_inquiry_id,
            "item_id": demand.item_id, "quantity": str(demand.quantity), "requested_day": demand.requested_day.isoformat(),
            "status": demand.status,
            "committed_quantity": str(demand.committed_quantity) if demand.committed_quantity is not None else None,
            "committed_day": demand.committed_day.isoformat() if demand.committed_day else None,
            "production_orders": [_order(o) for o in orders]}


def demands(db: DbSession, limit: int = 500) -> list[dict]:
    """Every customer demand Planning knows, newest first (the observer's order list)."""
    return [{"demand_id": str(d.id), "request_ref": d.request_ref, "order_number": d.sales_order_number,
             "sales_inquiry_id": d.sales_inquiry_id, "item_id": d.item_id, "quantity": str(d.quantity),
             "requested_day": d.requested_day.isoformat(), "status": d.status,
             "committed_quantity": str(d.committed_quantity) if d.committed_quantity is not None else None,
             "committed_day": d.committed_day.isoformat() if d.committed_day else None,
             "quantity_shipped": str(d.quantity_shipped), "created_at": d.created_at.isoformat()}
            for d in db.scalars(select(CustomerDemand).order_by(CustomerDemand.created_at.desc()).limit(limit))]


FINISHED_DEMANDS = ("COMPLETED", "CANCELLED", "EXPIRED", "COMMIT_FAILED", "NOT_FEASIBLE", "WITHDRAWN")


def open_demand_count(db: DbSession) -> int:
    """Customer demands still in progress (not completed, cancelled, expired or failed)."""
    return db.scalar(select(func.count()).select_from(CustomerDemand)
                     .where(CustomerDemand.status.not_in(FINISHED_DEMANDS))) or 0


def cases_for(db: DbSession, demand_id: str) -> list[dict]:
    """The cases Planning opened for a demand (each holds its negotiation sessions)."""
    return [{"case_id": c.id, "kind": c.kind, "status": c.status, "sessions": c.sessions, "depth": c.depth,
             "created_at": c.created_at.isoformat() if c.created_at else None}
            for c in db.scalars(select(Case).where(Case.demand_id == uuid.UUID(demand_id)).order_by(Case.created_at))]


def work_centers(db: DbSession) -> list[str]:
    return [w.code for w in db.scalars(select(WorkCenter).order_by(WorkCenter.code))]


def machine_hours_free(db: DbSession, work_center: str, day: date) -> str:
    """Free machine-hours of a work center on a day (capacity - committed - held)."""
    from app.planning_agent.plan import machine_free

    return str(machine_free(db, work_center, day))


def reconcile(db: DbSession) -> list[str]:
    """Committed and held machine-hours of every work center and day equal the sum of their ledger rows."""
    expected = {f"{ref} {day} {bucket}": total
                for (ref, day, bucket), total in ledger_sums(db, MachineHoursLedger).items()}
    actual = {}
    for row in db.scalars(select(WorkCenterDay)):
        actual[f"{row.work_center} {row.day} COMMITTED"] = row.committed_hours
        actual[f"{row.work_center} {row.day} HELD"] = row.held_hours
    return [f"planning {d}" for d in differences(expected, actual)]


def decisions(db: DbSession, after=None, at=None, limit: int | None = None) -> list[dict]:
    """This agent's recorded decisions (QD-3) as timeline rows, for the observer."""
    from app.agent_decisions.record import rows
    from app.planning_agent.models import AuditLog

    return rows(db, AuditLog, after=after, at=at, limit=limit)
