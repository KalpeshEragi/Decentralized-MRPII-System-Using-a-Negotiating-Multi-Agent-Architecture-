"""The simulated shop floor (demo.md §3, RD-3): an outside-world adapter, not an agent. It reports production progress
to Planning's shop-floor input, the same input as door 2 (`POST /planning/shop-floor/reports`).

Deterministic (same state, same reports): a released production order starts on its start day, and its whole
quantity is completed on its end day. Kits are issued by Warehouse in the morning routine before this runs (the day
cycle waits until the factory is quiet first). Machine breakdowns and short output are triggers, added later.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.planning_agent import manager as planning, reads as plans


def report_day(db: Session, day: date) -> list[str]:
    """Report today's progress. Returns the report ids sent. Repeating it changes nothing (report ids are fixed)."""
    sent = []
    for order in plans.production_orders(db, "RELEASED"):
        if date.fromisoformat(order["start_day"]) <= day:
            report_id = f"{order['id']}:STARTED"
            if planning.record_shop_floor_report(db, report_id, order["id"], "STARTED") == "received":
                sent.append(report_id)
    for order in plans.production_orders(db, "STARTED"):
        if date.fromisoformat(order["end_day"]) <= day:
            left = Decimal(order["quantity"]) - Decimal(order["quantity_completed"])
            report_id = f"{order['id']}:COMPLETED"
            if left > 0 and planning.record_shop_floor_report(db, report_id, order["id"], "QUANTITY_COMPLETED",
                                                              left) == "received":
                sent.append(report_id)
    return sent
