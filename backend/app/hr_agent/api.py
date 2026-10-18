"""HR doors (hr_agent/3 §B, backend_api.md §5): simulator inputs (X-Door-Key) and read-only views."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.doors import require_door_key
from app.core.errors import AppError, ErrorCode
from app.hr_agent import manager, reads

router = APIRouter(prefix="/hr", tags=["hr"])
simulator = [Depends(require_door_key("simulation_door_key"))]


class AbsenceIn(BaseModel):
    absence_id: str
    worker_code: str
    first_day: date
    last_day: date
    reason: str | None = None


@router.post("/setup", dependencies=simulator)
def setup(workers: list[dict[str, Any]], db: Session = Depends(get_db)) -> dict:
    manager.setup(db, workers)
    db.commit()
    return {"status": "done", "workers": len(workers)}


@router.post("/absences", status_code=202, dependencies=simulator)
def absence(body: AbsenceIn, db: Session = Depends(get_db)) -> dict:
    try:
        status = manager.record_absence(db, body.absence_id, body.worker_code, body.first_day, body.last_day,
                                        body.reason)
    except ValueError as error:
        raise AppError(ErrorCode.VALIDATION_ERROR, str(error)) from None
    db.commit()
    return {"status": status, "ref": body.absence_id}


@router.get("/pools/{skill}")
def pool(skill: str, start: date, end: date, db: Session = Depends(get_db)) -> dict:
    return {"free": reads.free_worker_hours(db, skill, start, end), "overtime_room": reads.overtime_room(db, skill, start, end)}


@router.get("/production-orders/{production_order_id}/assignments")
def assignments(production_order_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return reads.assignments_for(db, production_order_id)
