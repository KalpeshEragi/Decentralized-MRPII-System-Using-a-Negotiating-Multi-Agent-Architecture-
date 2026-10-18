"""Warehouse's read module (IB-2): the only thing other agents may import from the Warehouse Agent. Read-only."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.warehouse_agent.manager import free_receiving as _free_receiving, free_space as _free_space
from app.warehouse_agent.models import SpaceCommitment


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
