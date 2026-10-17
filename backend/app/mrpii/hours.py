"""Hours and capacity per day (RD-2, QA-5, quantity_accounting.md §7). Pure functions, no database.

- A routing step needs `setup + quantity × run time` machine-hours (rounded UP to 0.25 h) and that many hours × crew
  of its skill (worker-hours).
- A step fits a day only if both are free; the usable machine-hours of a day are
  `min(free machine-hours, free worker-hours / crew)`.
- Production is scheduled backward: an item needed on day D must be finished by the end of day D − 1.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

QUARTER = Decimal("0.25")
ZERO = Decimal(0)


def round_hours_up(hours: Decimal) -> Decimal:
    """QA-5: hours are rounded up to steps of 0.25 h (9.1 h -> 9.25 h)."""
    return (Decimal(hours) / QUARTER).to_integral_value(rounding=ROUND_CEILING) * QUARTER


def round_hours_down(hours: Decimal) -> Decimal:
    return (Decimal(hours) / QUARTER).to_integral_value(rounding=ROUND_FLOOR) * QUARTER


def round_space_up(units: Decimal) -> Decimal:
    """QA-5: space units are whole numbers, rounded up."""
    return Decimal(units).to_integral_value(rounding=ROUND_CEILING)


@dataclass(frozen=True)
class RoutingStep:
    step_no: int
    work_center: str
    skill: str
    crew_size: int
    setup_hours: Decimal
    run_hours_per_unit: Decimal


def machine_hours(step: RoutingStep, quantity: Decimal) -> Decimal:
    return round_hours_up(step.setup_hours + Decimal(quantity) * step.run_hours_per_unit)


def worker_hours(step: RoutingStep, quantity: Decimal) -> Decimal:
    return machine_hours(step, quantity) * step.crew_size


def fits_every_day(needed: dict[date, Decimal], free: dict[date, Decimal]) -> bool:
    """The capacity rule of every owner (quantity_accounting.md §7): each day's need fits that day's free capacity."""
    return all(hours <= free.get(day, ZERO) for day, hours in needed.items())


@dataclass(frozen=True)
class StepSchedule:
    step_no: int
    work_center: str
    skill: str
    crew_size: int
    hours_by_day: dict[date, Decimal]  # machine-hours per day; worker-hours = × crew_size

    @property
    def start_day(self) -> date:
        return min(self.hours_by_day)


FreeHours = Callable[[str, date], Decimal]  # (work center or skill, day) -> free hours


def schedule_backward(steps: Iterable[RoutingStep], quantity: Decimal, need_day: date, earliest_day: date,
                      free_machine: FreeHours, free_worker: FreeHours) -> list[StepSchedule] | None:
    """Place every step of a routing backward from `need_day` (last step first, each step ending before the next one
    starts), using only free machine-hours and free worker-hours. Returns the schedule in step order, or None if it
    cannot be done between `earliest_day` and the day before `need_day`."""
    scheduled: list[StepSchedule] = []
    finish_before = need_day
    for step in sorted(steps, key=lambda s: s.step_no, reverse=True):
        remaining = machine_hours(step, quantity)
        hours_by_day: dict[date, Decimal] = {}
        day = finish_before - timedelta(days=1)
        while remaining > 0:
            if day < earliest_day:
                return None
            usable = round_hours_down(min(free_machine(step.work_center, day),
                                          free_worker(step.skill, day) / step.crew_size))
            take = min(usable, remaining)
            if take > 0:
                hours_by_day[day] = take
                remaining -= take
            day -= timedelta(days=1)
        schedule = StepSchedule(step.step_no, step.work_center, step.skill, step.crew_size, hours_by_day)
        scheduled.append(schedule)
        finish_before = schedule.start_day
    return list(reversed(scheduled))
