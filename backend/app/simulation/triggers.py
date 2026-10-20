"""Simulator triggers (demo.md §7): a trigger changes a simulated fact through the owner's own input; the owner
publishes the event and every agent reacts as usual. A trigger never tells an agent what to answer.

Fired now, or scheduled for a simulated day (fired by the day cycle right after the clock advances). Every trigger is
logged in `simulation.trigger_log` and appears in the timeline.

| Kind           | Owner input                               | Params                                                  |
| NEW_ORDER      | Sales simulated-customer door             | product_sku, quantity, lead_days                         |
| CANCEL_ORDER   | Sales (a customer cancels, S6)            | order_number or "latest"                                 |
| CHANGE_ORDER   | Sales (a customer changes, S7)            | order_number or "latest", quantity                       |
| WORKER_ABSENT  | HR `record_absence` (S5)                  | worker, first_day, last_day (or first/last day offsets) |
| SUPPLIER_DELAY | Purchasing `record_supplier_delay` (S2)   | leg_id, new_date; or item_sku, days                      |
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.simulation.clock import today
from app.simulation.models import TriggerLog


def _worker_absent(db: Session, params: dict) -> dict:
    from app.hr_agent import manager as hr

    absence_id = params.get("absence_id") or f"SIM-{uuid.uuid4().hex[:8]}"
    first = (date.fromisoformat(params["first_day"]) if "first_day" in params
             else today(db) + timedelta(days=int(params["first_day_offset"])))
    last = (date.fromisoformat(params["last_day"]) if "last_day" in params
            else today(db) + timedelta(days=int(params["last_day_offset"])))
    status = hr.record_absence(db, absence_id, params["worker"], first, last)
    return {"absence_id": absence_id, "status": status}


def _supplier_delay(db: Session, params: dict) -> dict:
    from app.purchasing_agent import a2a as purchasing, reads as purchasing_reads

    if "leg_id" not in params:  # "the next delivery of this item is N days late"
        found = purchasing_reads.next_committed_delivery(db, params["item_sku"], today(db))
        if found is None:
            raise AppError(ErrorCode.NOT_FOUND, f"no committed delivery of {params['item_sku']} to delay")
        params = {"leg_id": found["leg_id"],
                  "new_date": (date.fromisoformat(found["delivery_date"]) + timedelta(days=int(params["days"])))
                  .isoformat()}
    return purchasing.record_supplier_delay(db, uuid.UUID(str(params["leg_id"])),
                                            date.fromisoformat(params["new_date"]))


def _new_order(db: Session, params: dict) -> dict:
    from app.simulation import customers

    return customers.request_one(db, today(db), params["product_sku"], int(params["quantity"]),
                                 int(params["lead_days"]), params.get("phone"))


def _order_number(db: Session, params: dict) -> str:
    if params.get("order_number", "latest") != "latest":
        return params["order_number"]
    from app.planning_agent import reads as planning

    found = next((d["order_number"] for d in planning.demands(db) if d["order_number"] and d["status"] == "COMMITTED"),
                 None)
    if found is None:
        raise AppError(ErrorCode.NOT_FOUND, "no committed order to change")
    return found


def _cancel_order(db: Session, params: dict) -> dict:
    from app.simulation import customers

    return customers.order_action(_order_number(db, params), "cancel")


def _change_order(db: Session, params: dict) -> dict:
    from app.simulation import customers

    return customers.order_action(_order_number(db, params), "change", {"quantity": str(params["quantity"])})


KINDS = {"NEW_ORDER": _new_order, "CANCEL_ORDER": _cancel_order, "CHANGE_ORDER": _change_order,
         "WORKER_ABSENT": _worker_absent, "SUPPLIER_DELAY": _supplier_delay}


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
    except (ValueError, KeyError) as error:  # bad parameters (unknown product, missing field)
        entry.status, entry.result = "FAILED", {"code": "VALIDATION_ERROR", "message": str(error)}
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
