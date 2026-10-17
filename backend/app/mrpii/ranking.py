"""Planning's fixed ranking of alternatives (PL-6, planning_agent/2_planning_agent_functions.md §6). Plain code, no AI.

Used when the AI fails or chooses an alternative that does not pass the filters. It only orders alternatives that code
generated; it never changes their numbers and never picks one that delivers less than the target quantity.

Order:
1. filter: hard constraints must hold (re-checked just before ranking)
2. filter: must not touch released/started orders, the time fence, or another order's committed date or quantity;
   then fewest FIRM orders to renegotiate
3. full quantity on the target date first; then fewest days late
4. fewest other orders moved; then fewest days moved
5. least safety stock used; then fewest extra worker-hours; then fewest negotiations
6. earliest completion
7. tie: alphabetical key
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Alternative:
    key: str
    quantity: Decimal
    target_quantity: Decimal
    completion_date: date
    hard_ok: bool
    touches_protected: bool
    firm_changes: int
    full_on_target: bool
    days_late: int
    orders_moved: int
    days_moved: int
    safety_stock_used: Decimal
    extra_worker_hours: Decimal
    negotiations: int


def rejection_reason(alternative: Alternative) -> str | None:
    if not alternative.hard_ok:
        return "HARD_CONSTRAINT"
    if alternative.touches_protected:
        return "TOUCHES_PROTECTED_COMMITMENT"
    if alternative.quantity < alternative.target_quantity:
        return "LESS_THAN_TARGET_QUANTITY"  # becomes a customer option through Sales instead (§6.3)
    return None


def _sort_key(a: Alternative) -> tuple:
    return (a.firm_changes, not a.full_on_target, a.days_late, a.orders_moved, a.days_moved, a.safety_stock_used,
            a.extra_worker_hours, a.negotiations, a.completion_date, a.key)


def rank(alternatives: list[Alternative]) -> tuple[list[Alternative], dict[str, str]]:
    """(allowed alternatives best first, {key: reason} of the filtered-out ones). An empty first list means no
    automatic choice: NOTHING_FEASIBLE for a new request, or escalation for an existing order."""
    rejected = {a.key: reason for a in alternatives if (reason := rejection_reason(a))}
    allowed = sorted((a for a in alternatives if a.key not in rejected), key=_sort_key)
    return allowed, rejected


def check_ai_choice(chosen_key: str | None, alternatives: list[Alternative]) -> Alternative:
    """The AI may pick any alternative that passes the filters; anything else (or no answer) -> the fixed ranking."""
    allowed, _ = rank(alternatives)
    if not allowed:
        raise ValueError("no alternative passes the filters")
    return next((a for a in allowed if a.key == chosen_key), allowed[0])
