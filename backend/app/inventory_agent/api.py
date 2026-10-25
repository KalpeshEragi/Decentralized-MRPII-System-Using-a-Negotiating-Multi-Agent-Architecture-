"""Inventory doors (inventory_agent/3 §C, backend_api.md §5): setup (simulator, X-Door-Key) and read-only views.
There is no other write door: changes come only through negotiation messages and events."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.doors import require_door_key
from app.inventory_agent import manager, reads

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post("/setup", dependencies=[Depends(require_door_key("simulation_door_key"))])
def setup(rows: list[dict[str, Any]], db: Session = Depends(get_db)) -> dict:
    manager.setup(db, rows)
    db.commit()
    return {"status": "done", "items": len(rows)}


@router.get("/items/{item_id}/position")
def position(item_id: str, db: Session = Depends(get_db)) -> dict:
    return reads.stock_position(db, item_id)


@router.get("/items/{item_id}/atp")
def atp(item_id: str, start: date, end: date, db: Session = Depends(get_db)) -> dict:
    return reads.atp_by_date(db, item_id, start, end)


@router.get("/orders/{for_ref}/reservations")
def reservations(for_ref: str, db: Session = Depends(get_db)) -> list[dict]:
    return reads.reservations_for(db, for_ref)
