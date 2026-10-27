"""The batch shop floor's arithmetic (SIM-2), no database: work follows Planning's scheduled hours spread over the
shift, and finished units come in whole batches until the last hour."""

from datetime import date
from decimal import Decimal as D

from app.simulation.shop_floor import units_done, worked_hours

ORDER = {"quantity": "60", "hours_by_day": {"2026-11-06": "2", "2026-11-07": "1"}}  # 3 machine-hours over two days
DAY1, DAY2 = date(2026, 11, 6), date(2026, 11, 7)


def test_scheduled_hours_are_worked_evenly_over_the_shift():
    assert worked_hours(ORDER, DAY1, 8, 8, 16) == 0                # shift just started
    assert worked_hours(ORDER, DAY1, 12, 8, 16) == D("1")          # half the shift: half of day 1's 2 h
    assert worked_hours(ORDER, DAY1, 16, 8, 16) == D("2")          # day 1 done
    assert worked_hours(ORDER, DAY2, 8, 8, 16) == D("2")           # day 1 counts in full on day 2
    assert worked_hours(ORDER, DAY2, 20, 8, 16) == D("3")          # never more than the shift
    assert worked_hours(ORDER, date(2026, 11, 5), 16, 8, 16) == 0  # before it starts


def test_units_come_in_whole_batches_and_the_last_hour_finishes_the_order():
    assert units_done(ORDER, D("0.5"), 25) == 0      # 10 of 60 made: no full batch yet
    assert units_done(ORDER, D("1.5"), 25) == 25     # 30 made: one batch
    assert units_done(ORDER, D("2.6"), 25) == 50     # 52 made: two batches
    assert units_done(ORDER, D("3"), 25) == 60       # all hours worked: the rest (10) is the last batch
    assert units_done({**ORDER, "hours_by_day": {}}, D("0"), 25) == 60  # nothing scheduled: done at once
