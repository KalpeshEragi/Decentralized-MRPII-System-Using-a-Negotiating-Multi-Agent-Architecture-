"""Inventory's read module (IB-2): the only thing other agents may import from the Inventory Agent. Read-only; returns
plain data."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.inventory_agent.manager import profile
from app.core.owner_tables import differences, ledger_sums
from app.inventory_agent.models import Hold, Reservation, StockBalance, StockLedger
from app.mrpii.atp import atp


def stock_position(db: DbSession, item_id: str) -> dict:
    row = db.get(StockBalance, item_id)
    incoming, promises = profile(db, item_id)
    return {
        "item_id": item_id,
        "on_hand": str(row.on_hand) if row else "0",
        "reserved": str(row.reserved) if row else "0",
        "held": str(row.held) if row else "0",
        "safety_stock": str(row.safety_stock) if row else "0",
        "incoming": [{"day": r.day.isoformat(), "quantity": str(r.quantity)} for r in incoming],
        "promises": [{"day": p.day.isoformat(), "quantity": str(p.quantity)} for p in promises],
    }


def atp_by_date(db: DbSession, item_id: str, start: date, end: date) -> dict[str, str]:
    row = db.get(StockBalance, item_id)
    if row is None:
        return {(start + timedelta(days=n)).isoformat(): "0" for n in range((end - start).days + 1)}
    incoming, promises = profile(db, item_id)
    return {(start + timedelta(days=n)).isoformat():
            str(atp(start + timedelta(days=n), row.on_hand, incoming, promises, row.safety_stock))
            for n in range((end - start).days + 1)}


def reservations_for(db: DbSession, for_ref: str) -> list[dict]:
    holds = db.scalars(select(Hold).where(Hold.for_ref == for_ref)).all()
    reservations = db.scalars(select(Reservation).where(Reservation.for_ref == for_ref)).all()
    return ([{"kind": "HOLD", "id": str(h.id), "item_id": h.item_id, "quantity": str(h.quantity),
              "due_day": h.due_day.isoformat(), "status": h.status} for h in holds]
            + [{"kind": "RESERVATION", "id": str(r.id), "item_id": r.item_id, "quantity": str(r.quantity),
                "issued": str(r.quantity_issued), "due_day": r.due_day.isoformat(), "status": r.status}
               for r in reservations])


def reconcile(db: DbSession) -> list[str]:
    """Every balance equals the sum of its ledger rows (QA-1). Empty list = reconciled."""
    columns = {"ON_HAND": "on_hand", "RESERVED": "reserved", "HELD": "held", "INCOMING": "incoming_total",
               "SAFETY_STOCK": "safety_stock", "SAFETY_STOCK_USE": "safety_stock_released"}
    expected = {f"{ref} {bucket}": total for (ref, _day, bucket), total in ledger_sums(db, StockLedger).items()}
    actual = {f"{row.item_id} {bucket}": getattr(row, column) for row in db.scalars(select(StockBalance))
              for bucket, column in columns.items()}
    return [f"inventory {d}" for d in differences(expected, actual)]


def balances(db: DbSession) -> dict[str, dict]:
    """Every item's balance in one query: {item_id: {on_hand, reserved, held, safety_stock}} (for overviews)."""
    return {row.item_id: {"on_hand": str(row.on_hand), "reserved": str(row.reserved), "held": str(row.held),
                          "safety_stock": str(row.safety_stock)} for row in db.scalars(select(StockBalance))}
