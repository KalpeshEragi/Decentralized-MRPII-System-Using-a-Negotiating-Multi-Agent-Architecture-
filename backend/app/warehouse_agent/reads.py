"""Warehouse's read module (IB-2): the only thing other agents may import from the Warehouse Agent. Read-only."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.warehouse_agent.manager import free_receiving as _free_receiving, free_space as _free_space
from app.core.owner_tables import differences, ledger_sums
from app.warehouse_agent.models import Hold, SpaceCommitment, SpaceLedger, SpaceMovement


def free_space(db: DbSession, zone: str, start: date, end: date) -> dict[str, str]:
    return {(start + timedelta(days=n)).isoformat(): str(_free_space(db, zone, start + timedelta(days=n)))
            for n in range((end - start).days + 1)}


def free_receiving(db: DbSession, start: date, end: date) -> dict[str, str]:
    return {(start + timedelta(days=n)).isoformat(): str(_free_receiving(db, start + timedelta(days=n)))
            for n in range((end - start).days + 1)}


def commitments_for(db: DbSession, for_ref: str) -> list[dict]:
    return [{"id": str(c.id), "kind": c.kind, "zone": c.zone, "item_id": c.item_id, "quantity": str(c.quantity),
             "space_units": str(c.space_units), "arrival_day": c.arrival_day.isoformat(),
             "until_day": c.until_day.isoformat() if c.until_day else None, "status": c.status}
            for c in db.scalars(select(SpaceCommitment).where(SpaceCommitment.for_ref == for_ref))]


def reconcile(db: DbSession) -> list[str]:
    """Space held by open holds and space of planned arrivals equal their ledger sums, per zone. (Zone occupancy
    starts from a configured estimate that is not in the ledger, so it is not compared.)"""
    sums = defaultdict(Decimal)
    for (ref, _day, bucket), total in ledger_sums(db, SpaceLedger).items():
        if bucket in ("HELD", "PLANNED_ARRIVAL"):
            sums[f"{ref} {bucket}"] += total
    actual = defaultdict(Decimal)
    for hold in db.scalars(select(Hold).where(Hold.status == "ACTIVE")):
        actual[f"{hold.zone} HELD"] += hold.space_units
    for movement in db.scalars(select(SpaceMovement).where(SpaceMovement.kind == "ARRIVAL",
                                                           SpaceMovement.status == "PLANNED")):
        actual[f"{movement.zone} PLANNED_ARRIVAL"] += movement.space_units
    return [f"warehouse {d}" for d in differences(dict(sums), dict(actual))]


def zones(db: DbSession) -> list[dict]:
    from app.warehouse_agent.models import Zone

    return [{"zone": z.zone, "capacity_units": str(z.capacity_units), "occupied_now": str(z.occupied_now)}
            for z in db.scalars(select(Zone).order_by(Zone.zone))]


def deliveries_on(db: DbSession, day: date) -> list[dict]:
    """Supplier deliveries expected or received on a day (inbound dock)."""
    return [{"commitment_id": str(c.id), "item_id": c.item_id, "quantity": str(c.quantity), "status": c.status,
             "arrival_day": c.arrival_day.isoformat(), "for_ref": c.for_ref}
            for c in db.scalars(select(SpaceCommitment).where(SpaceCommitment.kind == "DELIVERY",
                                                              SpaceCommitment.arrival_day == day))]


def decisions(db: DbSession, after=None, at=None, limit: int | None = None) -> list[dict]:
    """This agent's recorded decisions (QD-3) as timeline rows, for the observer."""
    from app.agent_decisions.record import rows
    from app.warehouse_agent.models import AuditLog

    return rows(db, AuditLog, after=after, at=at, limit=limit)
