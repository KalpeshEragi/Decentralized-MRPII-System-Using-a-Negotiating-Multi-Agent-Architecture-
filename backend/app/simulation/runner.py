"""The simulated day cycle and Play / Pause (demo.md §6, DM-1). Infrastructure: it moves time and plays the outside
world; it never decides anything for an agent.

One day:  advance the clock (`SimulatedDayStarted`) and fire the triggers scheduled for that day -> wait until quiet (every agent finished its
(holds expired, deliveries received, kits issued, ...) -> the shop floor reports today's progress ->
wait until quiet again.

Quiet = no PENDING or RUNNING item in any work queue (FAILED items do not count; they wait for a person). A day that
does not become quiet within `quiet_limit_seconds` (real time) pauses the run and reports what is still waiting.
"""

import logging
import threading
import time
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import work_runner
from app.simulation import shop_floor, triggers
from app.simulation.clock import get_clock, next_day
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


def waiting(db: Session) -> dict[str, int]:
    """Unfinished work per queue (PENDING or RUNNING). Empty = the factory is quiet."""
    found = {}
    for model in queue_models():
        count = db.scalar(select(func.count()).select_from(model).where(
            model.status.in_((work_runner.PENDING, work_runner.RUNNING))))
        if count:
            found[f"{model.__table__.schema}.{model.__tablename__}"] = count
    return found


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
    """Advance one simulated day and play it out. `settle` waits for the work (tests pass their pump)."""
    settle = settle or (lambda: wait_until_quiet(session_factory))
    with session_factory() as db:
        day = next_day(db)
        triggers.fire_due(db, day)  # scheduled triggers change their facts with the new day
        db.commit()
    left = settle()
    if left:
        return {"day": day.isoformat(), "waiting": left, "shop_floor": []}
    with session_factory() as db:
        reports = shop_floor.report_day(db, day)
        db.commit()
    return {"day": day.isoformat(), "waiting": settle(), "shop_floor": reports}


# -- Play / Pause (one background thread; the clock row holds the status) ----------------------------------------------


_play_thread: threading.Thread | None = None
_lock = threading.Lock()


def _set_status(session_factory, status: str, reason: str | None = None) -> None:
    with session_factory() as db:
        clock = get_clock(db, lock=True)
        clock.status = status
        db.commit()
    if reason:
        logger.warning("simulation paused: %s", reason)


def _playing(session_factory) -> bool:
    with session_factory() as db:
        return get_clock(db).status == "PLAYING"


def _play_loop(session_factory) -> None:
    while _playing(session_factory):
        day = run_one_day(session_factory)
        if day["waiting"]:
            _set_status(session_factory, "PAUSED", f"day {day['day']} did not become quiet: {day['waiting']}")
            return


def play(session_factory: Callable[[], Session]) -> None:
    """Advance day after day, each only when the factory is quiet, until paused."""
    global _play_thread
    with _lock:
        _set_status(session_factory, "PLAYING")
        if _play_thread is None or not _play_thread.is_alive():
            _play_thread = threading.Thread(target=_play_loop, args=(session_factory,), name="simulation-play",
                                            daemon=True)
            _play_thread.start()


def pause(session_factory: Callable[[], Session]) -> None:
    """Stop after the current day; work already queued finishes."""
    _set_status(session_factory, "PAUSED")
