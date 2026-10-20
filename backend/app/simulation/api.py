"""Simulation doors (demo.md §13): the clock (next day, Play, Pause, what is still waiting), the factory settings and
triggers. States, scenarios and runs come later in step 7."""

import threading
from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db, new_session
from app.core.doors import require_door_key
from app.simulation import clock, factory_a, runner, scenarios, settings, states, triggers
from app.simulation.models import TriggerLog

router = APIRouter(prefix="/simulation", tags=["simulation"])


def get_session_factory() -> Callable[[], Session]:
    """How the day cycle opens its own sessions (it runs in the background). Tests replace it."""
    return new_session


@router.get("/clock")
def get_clock(db: Session = Depends(get_db)) -> dict:
    current = clock.get_clock(db)
    db.commit()  # the row is created on first use
    return {"current_day": current.current_day.isoformat(), "status": current.status, "waiting": runner.waiting(db)}


@router.post("/clock/next-day", status_code=202)
def next_day(session_factory: Callable[[], Session] = Depends(get_session_factory)) -> dict:
    """Play one simulated day in the background: advance, wait until quiet, shop floor, wait until quiet."""
    threading.Thread(target=runner.run_one_day, args=(session_factory,), name="simulation-day", daemon=True).start()
    return {"status": "started"}


@router.post("/clock/play", status_code=202)
def play(session_factory: Callable[[], Session] = Depends(get_session_factory)) -> dict:
    """Advance day after day, each only when the factory is quiet, until paused (DM-1)."""
    runner.play(session_factory)
    return {"status": "PLAYING"}


@router.post("/clock/pause")
def pause(session_factory: Callable[[], Session] = Depends(get_session_factory)) -> dict:
    runner.pause(session_factory)
    return {"status": "PAUSED"}


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return settings.read_settings(db)


@router.post("/settings", dependencies=[Depends(require_door_key("simulation_door_key"))])
def change_settings(changes: dict[str, Any], db: Session = Depends(get_db)) -> dict:
    """Change factory settings (validated); all changes get one new settings version."""
    result = settings.update_settings(db, changes)
    db.commit()
    return result


@router.post("/triggers", status_code=201, dependencies=[Depends(require_door_key("simulation_door_key"))])
def add_trigger(body: dict[str, Any], db: Session = Depends(get_db)) -> dict:
    """Fire a trigger now, or schedule it for a simulated day: {"kind", "params", "day"?} (demo.md §7)."""
    day = date.fromisoformat(body["day"]) if body.get("day") else None
    entry = triggers.add(db, body["kind"], body.get("params", {}), day)
    db.commit()
    return triggers.view(entry)


@router.get("/triggers")
def list_triggers(db: Session = Depends(get_db)) -> list[dict]:
    return [triggers.view(t) for t in db.scalars(select(TriggerLog).order_by(TriggerLog.id))]


@router.post("/states", status_code=201, dependencies=[Depends(require_door_key("simulation_door_key"))])
def save_state(body: dict[str, Any], db: Session = Depends(get_db)) -> dict:
    """Save the current run state under a name (DM-2). Only when the factory is quiet."""
    saved = states.save(db, body["name"], body.get("description"))
    db.commit()
    return saved


@router.get("/states")
def list_states(db: Session = Depends(get_db)) -> list[dict]:
    return states.listing(db)


@router.post("/states/{name}/restore", dependencies=[Depends(require_door_key("simulation_door_key"))])
def restore_state(name: str, db: Session = Depends(get_db)) -> dict:
    """Replace the whole run state with a saved one; every owner's reconcile check reports its differences."""
    restored = states.restore(db, name)
    db.commit()
    return restored


@router.post("/factories/factory-a", status_code=201, dependencies=[Depends(require_door_key("simulation_door_key"))])
def configure_factory_a(db: Session = Depends(get_db)) -> dict:
    """Configure (not trigger): empty the run, build the default demo factory (demo.md §4.1) through each owner's own
    setup, and save it as the starting state `factory-a`."""
    states.clear(db)
    items = factory_a.build(db)
    db.flush()
    saved = states.save(db, "factory-a", "Default demo factory (demo.md §4.1)")
    db.commit()
    return {"items": items, "state": saved}


@router.get("/scenarios")
def list_scenarios() -> list[dict]:
    return scenarios.listing()


@router.post("/scenarios/{name}/start", status_code=201,
             dependencies=[Depends(require_door_key("simulation_door_key"))])
def start_scenario(name: str, body: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict:
    """Restore the starting state, apply the scenario's settings and seed, schedule its triggers, open a run. Then use
    Play or Next day."""
    started = scenarios.start(db, name, int((body or {}).get("seed", 1)))
    db.commit()
    return started


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)) -> list[dict]:
    return scenarios.runs(db)


@router.post("/runs/{run_id}/finish", dependencies=[Depends(require_door_key("simulation_door_key"))])
def finish_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    """Close the run and save its report (kept when a state is restored later)."""
    report = scenarios.finish(db, run_id)
    db.commit()
    return report["metrics"]


@router.get("/runs/{run_id}/report")
def run_report(run_id: int, db: Session = Depends(get_db)) -> dict:
    return scenarios.report_of(db, run_id)
