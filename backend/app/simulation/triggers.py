"""Simulator triggers (demo.md §7): a trigger changes a simulated fact through the owner's own input; the owner
publishes the event and every agent reacts as usual. A trigger never tells an agent what to answer.

Fired now, or scheduled for a simulated day (fired by the day cycle right after the clock advances). Every trigger is
logged in `simulation.trigger_log` and appears in the timeline.

| Kind           | Owner input                               | Params                                   |
| WORKER_ABSENT  | HR `record_absence`                       | worker, first_day, last_day              |
| SUPPLIER_DELAY | Purchasing `record_supplier_delay` (S2)   | leg_id, new_date                         |

Order changes and cancellations come with the customer driver (they go through Sales).
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.simulation.models import TriggerLog


def _worker_absent(db: Session, params: dict) -> dict:
    from app.hr_agent import manager as hr

    absence_id = params.get("absence_id") or f"SIM-{uuid.uuid4().hex[:8]}"
    status = hr.record_absence(db, absence_id, params["worker"], date.fromisoformat(params["first_day"]),
                               date.fromisoformat(params["last_day"]))
    return {"absence_id": absence_id, "status": status}


def _supplier_delay(db: Session, params: dict) -> dict:
    from app.purchasing_agent import a2a as purchasing

    return purchasing.record_supplier_delay(db, uuid.UUID(str(params["leg_id"])),
                                            date.fromisoformat(params["new_date"]))


KINDS = {"WORKER_ABSENT": _worker_absent, "SUPPLIER_DELAY": _supplier_delay}


def add(db: Session, kind: str, params: dict, day: date | None = None) -> TriggerLog:
    """Log a trigger; fire it now when no day is given. Caller commits."""
    if kind not in KINDS:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"unknown trigger {kind}", [{"field": "kind", "issue": "unknown"}])
    entry = TriggerLog(kind=kind, params=params, scheduled_day=day, status="SCHEDULED")
    db.add(entry)
    db.flush()
    if day is None:
        fire(db, entry)
    return entry


def fire(db: Session, entry: TriggerLog) -> None:
    """Apply one trigger through its owner's input. A refusal by the owner is recorded, not retried."""
    try:
        with db.begin_nested():  # the owner's refusal must not undo the log row
            entry.result = KINDS[entry.kind](db, entry.params)
        entry.status = "DONE"
    except AppError as error:
        entry.status, entry.result = "FAILED", {"code": str(error.code), "message": str(error)}
    entry.fired_at = datetime.now(timezone.utc)


def fire_due(db: Session, day: date) -> int:
    """Fire every scheduled trigger due on or before `day` (oldest first). Caller commits."""
    due = db.scalars(select(TriggerLog).where(TriggerLog.status == "SCHEDULED", TriggerLog.scheduled_day <= day)
                     .order_by(TriggerLog.scheduled_day, TriggerLog.id).with_for_update()).all()
    for entry in due:
        fire(db, entry)
    return len(due)


def view(entry: TriggerLog) -> dict:
    return {"id": entry.id, "kind": entry.kind, "params": entry.params,
            "scheduled_day": entry.scheduled_day.isoformat() if entry.scheduled_day else None,
            "status": entry.status, "result": entry.result,
            "fired_at": entry.fired_at.isoformat() if entry.fired_at else None}
