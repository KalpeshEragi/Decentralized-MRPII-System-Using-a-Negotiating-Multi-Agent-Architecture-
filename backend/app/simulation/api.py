"""Simulation doors of step 1 (demo.md §13): the clock and the factory settings. The rest of the simulator
(states, scenarios, triggers, Play/Pause, runs) comes in step 7. The old `POST /simulation/reset` stays in
`app/api/simulation.py` until the Phase 2 retirement."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.doors import require_door_key
from app.simulation import clock, settings

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/clock")
def get_clock(db: Session = Depends(get_db)) -> dict:
    current = clock.get_clock(db)
    db.commit()  # the row is created on first use
    return {"current_day": current.current_day.isoformat(), "status": current.status}


@router.post("/clock/next-day")
def next_day(db: Session = Depends(get_db)) -> dict:
    """Advance one simulated day; publishes SimulatedDayStarted."""
    day = clock.next_day(db)
    db.commit()
    return {"current_day": day.isoformat()}


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return settings.read_settings(db)


@router.post("/settings", dependencies=[Depends(require_door_key("simulation_door_key"))])
def change_settings(changes: dict[str, Any], db: Session = Depends(get_db)) -> dict:
    """Change factory settings (validated); all changes get one new settings version."""
    result = settings.update_settings(db, changes)
    db.commit()
    return result


@router.post("/triggers/supplier-delay", dependencies=[Depends(require_door_key("simulation_door_key"))])
def supplier_delay(body: dict[str, Any], db: Session = Depends(get_db)) -> dict:
    """Trigger S2: a supplier announces a later date for a committed delivery. The fact goes through Purchasing (the
    owner of the supplier commitment); agents react to its event. {"leg_id": ..., "new_date": "YYYY-MM-DD"}"""
    from datetime import date
    from uuid import UUID

    from app.purchasing_agent import a2a as purchasing

    payload = purchasing.record_supplier_delay(db, UUID(str(body["leg_id"])), date.fromisoformat(body["new_date"]))
    db.commit()
    return payload
