"""The simulated clock (demo.md §6, PB-3). One row; advancing it publishes `SimulatedDayStarted(date)`.

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


def next_day(db: Session) -> date:
    """Advance one simulated day and publish `SimulatedDayStarted` in the same transaction (caller commits).
    The clock row is locked, so two advances can never produce the same day twice."""
    clock = get_clock(db, lock=True)
    clock.current_day = clock.current_day + timedelta(days=1)
    channel.publish(db, event_type="SimulatedDayStarted", publisher=channel.SIMULATOR_CLOCK,
                    entity_type="simulated_day", entity_id="clock", entity_version=clock.current_day.toordinal(),
                    correlation_id=f"day-{clock.current_day.isoformat()}",
                    payload={"date": clock.current_day.isoformat()})
    return clock.current_day
