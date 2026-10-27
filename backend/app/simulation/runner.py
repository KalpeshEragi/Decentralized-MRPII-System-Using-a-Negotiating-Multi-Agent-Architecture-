"""The simulated day cycle and Play / Pause (demo.md §6, DM-1). Infrastructure: it moves time and plays the outside
world; it never decides anything for an agent.

One day:  advance the clock (`SimulatedDayStarted`) and fire the triggers scheduled for that day -> simulated
customers send today's requests -> wait until quiet (holds expired, deliveries received, kits issued, requests
planned, ...) -> customers decide on Planning's answers -> wait until quiet -> the shop floor reports today's
progress -> wait until quiet again.

Quiet = no PENDING or RUNNING item in any work queue (FAILED items do not count; they wait for a person). A day that
does not become quiet within `quiet_limit_seconds` (real time) pauses the run and reports what is still waiting.
Play also pauses by itself when nothing is left to do (`work_left` is empty): no open customer demand, no scheduled
trigger and no simulated customers placing orders. Empty days would only move the clock.
"""

import logging
import threading
import time
from datetime import timedelta
from collections.abc import Callable

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from app.core import work_runner
from app.planning_agent import reads as planning
from app.simulation import customers, shop_floor, triggers
from app.simulation.clock import advance_hour, current_hour, get_clock, next_day, shift, today
from app.simulation.models import TriggerLog
from app.simulation.settings import setting

logger = logging.getLogger(__name__)
POLL_SECONDS = 0.5

Settle = Callable[[], dict[str, int]]  # waits until quiet (or gives up); returns what is still waiting


def queue_models() -> list[type]:
    """Every work queue the background runner serves (events, negotiation inboxes and outbox, agents' queues)."""
    from app.core import workers

    if not workers.runner.registrations:
        workers.register_all()
    return list({r.model: None for r in workers.runner.registrations})


def queue_counts(db: Session, statuses: tuple[str, ...]) -> dict[str, int]:
    """Items per queue in these statuses, in one query (the database may be far away: one round trip, not one per
    queue). Queues with none are left out."""
    models = queue_models()
    parts = [select(literal(i).label("q"), func.count().label("n")).select_from(model)
             .where(model.status.in_(statuses)) for i, model in enumerate(models)]
    return {f"{models[q].__table__.schema}.{models[q].__tablename__}": n
            for q, n in db.execute(union_all(*parts)).all() if n}


def waiting(db: Session) -> dict[str, int]:
    """Unfinished work per queue (PENDING or RUNNING). Empty = the factory is quiet."""
    return queue_counts(db, (work_runner.PENDING, work_runner.RUNNING))


def work_left(db: Session) -> list[str]:
    """What can still happen in the simulated factory. Empty = Play has nothing to wait for."""
    left = []
    if open_demands := planning.open_demand_count(db):
        left.append(f"{open_demands} open customer orders")
    if scheduled := db.scalar(select(func.count()).select_from(TriggerLog).where(TriggerLog.status == "SCHEDULED")):
        left.append(f"{scheduled} scheduled triggers")
    if customers.ordering_on(db, get_clock(db).current_day + timedelta(days=1)):
        left.append("simulated customers place orders tomorrow")
    return left


def wait_until_quiet(session_factory: Callable[[], Session]) -> dict[str, int]:
    """Wait for the background workers to finish all work, up to the quiet limit. Returns what is still waiting."""
    with session_factory() as db:
        limit = float(setting(db, "quiet_limit_seconds"))
    deadline = time.monotonic() + limit
    while True:
        with session_factory() as db:
            left = waiting(db)
        if not left or time.monotonic() >= deadline:
            return left
        time.sleep(POLL_SECONDS)


def run_one_day(session_factory: Callable[[], Session], settle: Settle | None = None) -> dict:
    """Advance one simulated day and play it out. `settle` waits for the work (tests pass their pump).

    Order: clock + due triggers -> new customer requests -> quiet -> customers decide on Planning's answers -> quiet
    -> shop floor works the whole shift -> quiet. Stops early (and reports) when a step does not become quiet."""
    settle = settle or (lambda: wait_until_quiet(session_factory))
    result = _start_day(session_factory, settle)
    if result.get("waiting"):
        return result
    with session_factory() as db:
        result["shop_floor"] = shop_floor.report_day(db, today(db))
        get_clock(db, lock=True).current_hour = shift(db)[1]  # the whole shift has been worked
        db.commit()
    return {**result, "waiting": settle()}


def run_one_hour(session_factory: Callable[[], Session], settle: Settle | None = None) -> dict:
    """Play one working hour (SIM-1). At the end of the shift the next hour starts a new day first (morning
    routines, customers), then its first hour is worked. The shop floor reports every batch finished in that hour."""
    settle = settle or (lambda: wait_until_quiet(session_factory))
    with session_factory() as db:
        day_over = current_hour(db) >= shift(db)[1]
    result = _start_day(session_factory, settle) if day_over else {"customers": [], "decisions": []}
    if result.get("waiting"):
        return result
    with session_factory() as db:
        hour = current_hour(db)
        result["shop_floor"] = shop_floor.work_hours(db, today(db), hour + 1)
        advance_hour(db)
        result.update(day=today(db).isoformat(), hour=f"{hour:02d}:00-{hour + 1:02d}:00")
        db.commit()
    return {**result, "waiting": settle()}


def _start_day(session_factory: Callable[[], Session], settle: Settle) -> dict:
    """A new simulated day up to the start of work: clock + due triggers, customers' requests and decisions."""
    with session_factory() as db:
        day = next_day(db)
        db.commit()
    with session_factory() as db:  # after the new day is committed: a trigger may call an agent's door
        triggers.fire_due(db, day)
        db.commit()
    result = {"day": day.isoformat(), "customers": [], "decisions": [], "shop_floor": []}
    with session_factory() as db:
        result["customers"] = customers.place_orders(db, day)
    if left := settle():
        return {**result, "waiting": left}
    for _ in range(3):  # a chat customer may need a few turns (a letter, then "yes"); structured needs one
        with session_factory() as db:
            decided = customers.answer_options(db)
        result["decisions"] += decided
        if left := settle():
            return {**result, "waiting": left}
        if not decided:
            break
    return result


# -- Play / Pause (one background thread; the clock row holds the status) ----------------------------------------------


_play_thread: threading.Thread | None = None
_lock = threading.Lock()
pause_reason: str | None = None  # why Play last stopped by itself (shown on the panel); None after a person's action


def _set_status(session_factory, status: str, reason: str | None = None) -> None:
    global pause_reason
    pause_reason = reason
    with session_factory() as db:
        clock = get_clock(db, lock=True)
        clock.status = status
        db.commit()
    if reason:
        logger.info("simulation paused: %s", reason)


def _playing(session_factory) -> bool:
    with session_factory() as db:
        return get_clock(db).status == "RUNNING"


def _nothing_left(session_factory) -> bool:
    with session_factory() as db:
        return not work_left(db)


def _play_loop(session_factory) -> None:
    """One simulated hour per tick (SIM-1), waiting `seconds_per_sim_hour` between hours (0 = as fast as possible)."""
    while _playing(session_factory):
        if _nothing_left(session_factory):
            _set_status(session_factory, "PAUSED", "nothing left to do: no open orders, triggers or new customers")
            return
        step = run_one_hour(session_factory)
        if step["waiting"]:
            _set_status(session_factory, "PAUSED", f"{step.get('day')} {step.get('hour', '')} did not become quiet: "
                                                   f"{step['waiting']}")
            return
        with session_factory() as db:
            pause_seconds = float(setting(db, "seconds_per_sim_hour"))
        time.sleep(pause_seconds)


def play(session_factory: Callable[[], Session]) -> None:
    """Advance hour after hour, each only when the factory is quiet, until paused."""
    global _play_thread
    with _lock:
        _set_status(session_factory, "RUNNING")
        if _play_thread is None or not _play_thread.is_alive():
            _play_thread = threading.Thread(target=_play_loop, args=(session_factory,), name="simulation-play",
                                            daemon=True)
            _play_thread.start()


def pause(session_factory: Callable[[], Session]) -> None:
    """Stop after the current day; work already queued finishes."""
    _set_status(session_factory, "PAUSED")
