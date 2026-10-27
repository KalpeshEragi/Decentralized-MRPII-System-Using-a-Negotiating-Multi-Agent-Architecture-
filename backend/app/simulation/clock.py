"""The simulated clock (demo.md §6, PB-3, SIM-1). One row; advancing the day publishes `SimulatedDayStarted(date)`.

The clock also has an hour (SIM-1): the working day runs from `shift_start` for `shift_hours`. `current_hour` is the
time the next simulated hour starts at; a new day starts at the shift's start, and the day is over at its end.

"Next day" is here; "Play" (advance only when the factory is quiet) and "Pause" come with the simulator in step 7.
Business dates use this simulated day; real time is only for retries, leases and timeouts.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.events import channel
from app.simulation.models import Clock
from app.simulation.settings import setting

CLOCK_ID = 1


def get_clock(db: Session, lock: bool = False) -> Clock:
    """The clock row, created on first use at the configured start day."""
    clock = db.get(Clock, CLOCK_ID, with_for_update=lock)
    if clock is None:
        clock = Clock(id=CLOCK_ID, current_day=date.fromisoformat(str(setting(db, "simulation_start_day"))),
                      status="PAUSED")
        db.add(clock)
        db.flush()
    return clock


def today(db: Session) -> date:
    return get_clock(db).current_day


def shift(db: Session) -> tuple[int, int]:
    """(first hour, end hour) of the working day, e.g. (8, 16)."""
    start = int(setting(db, "shift_start"))
    return start, start + int(setting(db, "shift_hours"))


def current_hour(db: Session) -> int:
    hour = get_clock(db).current_hour
    return shift(db)[0] if hour is None else hour


def advance_hour(db: Session) -> int:
    """One working hour has passed (caller commits). Returns the new time of day; at the shift's end the day is over
    and the next advance is a new day (`next_day`)."""
    clock = get_clock(db, lock=True)
    start, end = shift(db)
    clock.current_hour = min(end, (start if clock.current_hour is None else clock.current_hour) + 1)
    return clock.current_hour


def next_day(db: Session) -> date:
    """Advance one simulated day and publish `SimulatedDayStarted` in the same transaction (caller commits).
    The clock row is locked, so two advances can never produce the same day twice."""
    clock = get_clock(db, lock=True)
    clock.current_day = clock.current_day + timedelta(days=1)
    clock.current_hour = shift(db)[0]  # SIM-1: a new day starts at the shift's start
    channel.publish(db, event_type="SimulatedDayStarted", publisher=channel.SIMULATOR_CLOCK,
                    entity_type="simulated_day", entity_id="clock", entity_version=clock.current_day.toordinal(),
                    correlation_id=f"day-{clock.current_day.isoformat()}",
                    payload={"date": clock.current_day.isoformat()})
    return clock.current_day
