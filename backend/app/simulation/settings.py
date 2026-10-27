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
    "sales_offer_validity_hours": 24,            # RE-5 (was Sales' OFFER_VALIDITY)
    "sales_planning_wait_minutes": 10,           # RE-5 (was Sales' PLANNING_WAIT_LIMIT)
    "sales_ai_failures_before_staff": 2,         # RE-5 (was Sales' FAILURES_BEFORE_STAFF_IS_FLAGGED)
    "planning_reask_limit": 2,                   # QD-6, RE-5 (was Planning's MAX_REASKS)
    "purchasing_slot_retries": 2,                # WH-1, RE-5 (was Purchasing's SLOT_RETRIES)
    "customer_orders_per_day": 0,                # DM-3/DM-7: simulated customers' new requests per day
    "customer_order_days": 0,                    # load runs: customers order only on the run's first N days (0 = always)
    "ai_enabled": 0,                             # IMP-2: 1 = agents' AI steps on (wording, ranking); 0 = templates
    "ai_decision_max_orders": 10,                # QD-5: agents think only while at most this many orders are open
    "customer_chat_mode": 0,                     # DM-7: 0 = structured (data, no model), 1 = chat (Sales reads text)
    "customer_seed": 1,                          # DM-6: the customer driver's random generator is seeded per day
    "customer_quantity_min": 50,                 # DM-3 rules (starting values)
    "customer_quantity_max": 200,
    "customer_lead_days_min": 5,                 # requested date = today + this many days (min..max)
    "customer_lead_days_max": 15,
    "customer_later_date_max_days": 10,          # demo.md §9: accept LATER_DATE only if at most this much later
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
    from app.rules.registry import BY_KEY, check_value  # business rules have tighter bounds (RE-1)

    if key in BY_KEY and (problem := check_value(BY_KEY[key], number)[1]):
        raise AppError(ErrorCode.VALIDATION_ERROR, problem, [{"field": key, "issue": "out of bounds"}])
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
