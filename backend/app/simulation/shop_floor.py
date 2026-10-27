"""The simulated shop floor (demo.md §3, RD-3, SIM-2): an outside-world adapter, not an agent. It reports production
progress to Planning's shop-floor input, the same input as door 2 (`POST /planning/shop-floor/reports`).

Hour by hour (SIM-2): each released production order works the machine-hours Planning scheduled for it per day,
spread evenly over the working shift. Its progress is the share of its scheduled hours already worked; finished units
are reported in batches (`production_batch_size`), so made components exist as soon as a batch is done (SIM-3). The
order completes exactly when its scheduled hours are worked (on its end day, as before).

Deterministic: same state and same hours give the same reports, and report ids are fixed (a repeat changes nothing).
Kits are issued by Warehouse in the morning routine before the first hour. Breakdowns and blocked work: SIM-4, later.
"""

import math
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.planning_agent import manager as planning, reads as plans
from app.simulation.clock import shift
from app.simulation.settings import setting

ZERO = Decimal(0)


def worked_hours(order: dict, day: date, until_hour: int, start: int, end: int) -> Decimal:
    """Machine-hours of `order` worked by `until_hour` on `day`: every earlier scheduled day in full, and today's
    scheduled hours in proportion to the part of the shift that has passed."""
    done = ZERO
    passed = Decimal(min(max(until_hour - start, 0), end - start)) / Decimal(end - start)
    for day_text, hours in order["hours_by_day"].items():
        scheduled = date.fromisoformat(day_text)
        if scheduled < day:
            done += Decimal(hours)
        elif scheduled == day:
            done += Decimal(hours) * passed
    return done


def units_done(order: dict, worked: Decimal, batch: int) -> Decimal:
    """Finished units after `worked` hours: whole batches until the last hour, then the whole quantity."""
    quantity = Decimal(order["quantity"])
    total = sum((Decimal(h) for h in order["hours_by_day"].values()), ZERO)
    if total <= 0 or worked >= total:
        return quantity
    return min(quantity, Decimal(math.floor(quantity * worked / total / batch) * batch))


def work_hours(db: Session, day: date, until_hour: int) -> list[str]:
    """Report everything finished on `day` by `until_hour` (the shift's start + hours passed). Returns report ids."""
    start, end = shift(db)
    batch = max(1, int(setting(db, "production_batch_size")))
    sent = []
    for order in plans.production_orders(db, "RELEASED") + plans.production_orders(db, "STARTED"):
        if date.fromisoformat(order["start_day"]) > day:
            continue
        worked = worked_hours(order, day, until_hour, start, end)
        if order["status"] == "RELEASED" and (worked > 0 or date.fromisoformat(order["end_day"]) < day):
            report_id = f"{order['id']}:STARTED"
            if planning.record_shop_floor_report(db, report_id, order["id"], "STARTED") == "received":
                sent.append(report_id)
        done, completed = units_done(order, worked, batch), Decimal(order["quantity_completed"])
        while completed < done:  # one report per batch, so each batch is stored on its own
            size = min(Decimal(batch), done - completed)
            report_id = f"{order['id']}:BATCH:{int(completed // batch) + 1}"
            if planning.record_shop_floor_report(db, report_id, order["id"], "QUANTITY_COMPLETED", size) == "received":
                sent.append(report_id)
            completed += size
    return sent


def report_day(db: Session, day: date) -> list[str]:
    """Work the whole shift of `day` (Next day, Play by day). Returns the report ids sent."""
    return work_hours(db, day, shift(db)[1])
