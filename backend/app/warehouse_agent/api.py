"""Warehouse doors (warehouse_agent/3 §B, backend_api.md §5): setup (simulator, X-Door-Key) and read-only views.
Simulated deliveries and capacity changes come with the Purchasing stub (step 6)."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.doors import require_door_key
from app.warehouse_agent import manager, reads

router = APIRouter(prefix="/warehouse", tags=["warehouse"])


@router.post("/setup", dependencies=[Depends(require_door_key("simulation_door_key"))])
def setup(config: dict[str, Any], db: Session = Depends(get_db)) -> dict:
    manager.setup(db, config)
    db.commit()
    return {"status": "done"}


@router.get("/zones/{zone}/space")
def space(zone: str, start: date, end: date, db: Session = Depends(get_db)) -> dict:
    return reads.free_space(db, zone, start, end)


@router.get("/receiving")
def receiving(start: date, end: date, db: Session = Depends(get_db)) -> dict:
    return reads.free_receiving(db, start, end)


@router.get("/commitments/{for_ref}")
def commitments(for_ref: str, db: Session = Depends(get_db)) -> list[dict]:
    return reads.commitments_for(db, for_ref)
