"""The rule registry (RE-1, `architecture/rules_events_replenishment.md` §2): every business rule of the factory once.

A rule is a factory setting (`simulation/settings.py` holds the value and its documented default) plus what the rule
editor needs: the agent that owns it, plain words, a unit, safe bounds and whether code uses it. Settings that are not
listed here are SYSTEM settings (simulator, AI plumbing, seeds): the editor never shows them.

Bounds keep the system working; a value outside them is refused, also through the simulator's settings door.
Per-item policies (RE-2) and agent guidelines (RE-3) come in the next step.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

GENERAL, SALES, PLANNING, INVENTORY, PURCHASING, WAREHOUSE, HR = (
    "GENERAL", "SALES", "PLANNING", "INVENTORY", "PURCHASING", "WAREHOUSE", "HR")
OWNERS = (GENERAL, SALES, PLANNING, INVENTORY, PURCHASING, WAREHOUSE, HR)


@dataclass(frozen=True)
class Rule:
    key: str                 # the setting key
    owner: str               # GENERAL or the agent whose behaviour it shapes
    label: str
    description: str         # what it changes, in plain words
    kind: Literal["number", "percent", "hours", "days", "minutes"]
    unit: str                # shown next to the value
    min: Decimal
    max: Decimal
    whole: bool = True       # whole numbers only
    in_use: bool = True      # False: defined in the design, no code reads it yet (shown, not editable)
    decided_in: str = ""


def _r(key, owner, label, description, kind, unit, low, high, whole=True, in_use=True, decided_in=""):
    return Rule(key, owner, label, description, kind, unit, Decimal(str(low)), Decimal(str(high)), whole, in_use,
                decided_in)


RULES: tuple[Rule, ...] = (
    # -- general -------------------------------------------------------------------------------------------------------
    _r("time_fence_days", GENERAL, "Time fence",
       "Committed work starting within this many days is frozen: it is not moved automatically (only reported at "
       "risk). Larger = calmer shop floor, less flexible repairs.", "days", "days", 0, 14, decided_in="RD-4"),
    _r("hold_validity_days", GENERAL, "Hold validity",
       "How long an agreed but not yet committed hold (stock, hours, space) stays reserved before it expires.",
       "days", "days", 1, 7, decided_in="NG-2"),
    _r("later_date_horizon_days", GENERAL, "Later-date horizon",
       "How far ahead owners and Planning look for a later date when something does not fit on the wanted day.",
       "days", "days", 7, 120, decided_in="PL-7"),
    _r("dampener_quantity_share", GENERAL, "Small-change dampener",
       "A customer reduction smaller than this share of the order is not replanned (the stock stays reserved), "
       "to avoid churn for tiny changes.", "percent", "%", 0, "0.5", whole=False, decided_in="RD-8"),
    _r("dampener_days", GENERAL, "Dampener days",
       "Days within which small changes are dampened. Defined in the design; no code reads it yet.",
       "days", "days", 0, 7, in_use=False, decided_in="RD-8"),
    _r("follow_up_depth_limit", GENERAL, "Follow-up depth",
       "How many follow-up negotiations one need may start. Defined in the design; no code reads it yet.",
       "number", "levels", 1, 10, in_use=False, decided_in="HA-6"),
    # -- Sales ---------------------------------------------------------------------------------------------------------
    _r("sales_offer_validity_hours", SALES, "Offer validity",
       "How long options shown to a customer stay open before they expire.", "hours", "h", 1, 168,
       decided_in="RE-5"),
    _r("sales_planning_wait_minutes", SALES, "Wait for Planning",
       "After this long without Planning's answer, the customer and staff are told the request is late.",
       "minutes", "min", 1, 240, decided_in="RE-5"),
    _r("sales_ai_failures_before_staff", SALES, "AI failures before staff",
       "Model failures in a row in one conversation before it is handed to staff.", "number", "failures", 1, 10,
       decided_in="RE-5"),
    # -- Planning ------------------------------------------------------------------------------------------------------
    _r("best_option_repicks", PLANNING, "Option re-picks",
       "How many other options Planning tries to secure when the first one cannot be secured.", "number", "options",
       0, 5, decided_in="PL-7"),
    _r("release_lead_days", PLANNING, "Release lead",
       "How many days before its start a firm production order is released to the shop floor.", "days", "days",
       0, 7, decided_in="PL-7"),
    _r("production_batch_size", PLANNING, "Production batch size",
       "The shop floor finishes and stores goods in batches of this size, so components can feed the next operation "
       "as soon as a batch is done.", "number", "pieces", 1, 500, decided_in="SIM-2"),
    _r("planning_reask_limit", PLANNING, "Re-asks after a stale answer",
       "How often Planning asks an owner again after someone else took the resource first (decision D7).",
       "number", "times", 0, 5, decided_in="QD-6, RE-5"),
    # -- Inventory -----------------------------------------------------------------------------------------------------
    _r("safety_stock_release_share", INVENTORY, "Safety stock Inventory may lend",
       "The most of an item's safety stock Inventory may lend to an urgent order (then it publishes "
       "SafetyStockBreached).", "percent", "%", 0, 1, whole=False, decided_in="RD-6"),
    _r("safety_stock_max_slack_days", INVENTORY, "Only for orders due within",
       "Safety stock is lent only to orders needed within this many days (urgent ones).", "days", "days", 0, 14,
       decided_in="RD-6"),
    # -- Purchasing ----------------------------------------------------------------------------------------------------
    _r("purchasing_slot_retries", PURCHASING, "Receiving-slot retries",
       "How often Purchasing asks the Warehouse again for a receiving slot whose day filled up meanwhile.",
       "number", "times", 0, 5, decided_in="WH-1, RE-5"),
    # -- HR ------------------------------------------------------------------------------------------------------------
    _r("overtime_max_hours_per_day", HR, "Overtime per day",
       "The most extra hours one worker may work on a day when HR covers an absence or a peak.", "hours", "h", 0, 6,
       whole=False, decided_in="HR-3"),
    _r("overtime_max_hours_per_week", HR, "Overtime per week",
       "The most extra hours one worker may work in a week.", "hours", "h", 0, 30, whole=False, decided_in="HR-3"),
)

BY_KEY: dict[str, Rule] = {r.key: r for r in RULES}

OWNER_LABELS = {GENERAL: "General", SALES: "Sales", PLANNING: "Planning", INVENTORY: "Inventory",
                PURCHASING: "Purchasing", WAREHOUSE: "Warehouse", HR: "HR"}


def check_value(rule: Rule, value: object) -> tuple[Decimal | None, str | None]:
    """(clean value, None) when `value` is allowed for `rule`, else (None, the reason)."""
    try:
        number = Decimal(str(value).strip())
    except Exception:
        return None, f"{rule.label} must be a number"
    if not number.is_finite():
        return None, f"{rule.label} must be a number"
    if rule.whole and number != number.to_integral_value():
        return None, f"{rule.label} must be a whole number of {rule.unit}"
    if not rule.min <= number <= rule.max:
        shown = (lambda v: f"{v * 100:g} %") if rule.kind == "percent" else (lambda v: f"{v:g} {rule.unit}")
        return None, f"{rule.label} must be between {shown(rule.min)} and {shown(rule.max)}"
    return number, None


def cross_checks(values: dict[str, object]) -> list[str]:
    """Rules that must fit together (checked on the full set of values after a change)."""
    problems = []
    day, week = Decimal(str(values["overtime_max_hours_per_day"])), Decimal(str(values["overtime_max_hours_per_week"]))
    if week < day:
        problems.append("Overtime per week cannot be less than overtime per day")
    return problems
