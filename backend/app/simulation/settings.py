"""Factory settings (SD-2): business settings of the simulated factory, stored per run in `simulation.settings`.

Every key has a documented default (the decision in brackets). A key that was never changed has version 0 and its
default value. Agents read settings through `read_settings` and keep the returned version in their audit records.
Technical settings (database URL, Ollama, timeouts, worker counts) are environment variables (`core/config.py`).
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.simulation.models import Setting

# key -> default value. Numbers are non-negative.
DEFAULTS: dict[str, object] = {
    "simulation_start_day": "2026-11-02",       # demo.md §6 (a Monday)
    "hold_validity_days": 1,                     # NG-2: 24 h = one simulated day
    "safety_stock_release_share": "0.5",         # RD-6
    "safety_stock_max_slack_days": 2,            # RD-6
    "later_date_horizon_days": 60,               # PL-7 (also the owners' counter-offer horizon)
    "best_option_repicks": 2,                    # PL-7
    "release_lead_days": 1,                      # PL-7
    "time_fence_days": 2,                        # RD-4
    "dampener_days": 1,                          # RD-8
    "dampener_quantity_share": "0.05",           # RD-8
    "follow_up_depth_limit": 3,                  # HA-6
    "overtime_max_hours_per_day": 2,             # HR-3
    "overtime_max_hours_per_week": 8,            # HR-3
    "quiet_limit_seconds": 300,                  # demo.md §6
    "simulated_suppliers": 1,                    # PI-1: 1 = suppliers answer automatically, 0 = a person answers
}


def _check(key: str, value: object) -> object:
    if key not in DEFAULTS:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"unknown setting {key}", [{"field": key, "issue": "unknown"}])
    if key == "simulation_start_day":
        try:
            date.fromisoformat(str(value))
        except ValueError:
            raise AppError(ErrorCode.VALIDATION_ERROR, "simulation_start_day must be YYYY-MM-DD",
                           [{"field": key, "issue": "not a date"}]) from None
        return str(value)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{key} must be a number",
                       [{"field": key, "issue": "not a number"}]) from None
    if number < 0:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{key} must not be negative",
                       [{"field": key, "issue": "negative"}])
    return str(number) if isinstance(DEFAULTS[key], str) else int(number) if number == int(number) else str(number)


def read_settings(db: Session) -> dict:
    """{"version": n, "values": {key: value}} with defaults for keys never changed."""
    rows = {row.key: row for row in db.scalars(select(Setting))}
    values = {key: rows[key].value["value"] if key in rows else default for key, default in DEFAULTS.items()}
    return {"version": max((row.version for row in rows.values()), default=0), "values": values}


def setting(db: Session, key: str) -> object:
    return read_settings(db)["values"][key]


def update_settings(db: Session, changes: dict[str, object]) -> dict:
    """Validate and store changed values under one new settings version (caller commits)."""
    checked = {key: _check(key, value) for key, value in changes.items()}
    version = (db.scalar(select(func.max(Setting.version))) or 0) + 1
    for key, value in checked.items():
        row = db.get(Setting, key, with_for_update=True)
        if row is None:
            db.add(Setting(key=key, value={"value": value}, version=version))
        else:
            row.value, row.version = {"value": value}, version
    db.flush()
    return read_settings(db)
