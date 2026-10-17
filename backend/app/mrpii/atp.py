"""Available-to-promise by date (QA-4, quantity_accounting.md §4–5). Pure functions, no database.

    S(t) = on_hand + incoming arriving on or before t          (cumulative supply)
    C(t) = reserved + held due on or before t                   (cumulative promises)
    ATP(D) = max(0, min over all t >= D of (S(t) - C(t)) - safety_stock)

A new promise of q due on D is allowed only if q <= ATP(D). With nothing incoming, ATP(today) equals
`available_now = max(0, on_hand - reserved - held - safety_stock)`.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal(0)


@dataclass(frozen=True)
class Dated:
    """A dated quantity: an incoming receipt (by arrival day) or a promise (reservation or hold, by due day)."""

    day: date
    quantity: Decimal
    ref: str = ""
    order: int = 0  # commit order among promises with the same due day (earlier commit = covered first)


def available_now(on_hand: Decimal, reserved: Decimal, held: Decimal, safety_stock: Decimal) -> Decimal:
    return max(ZERO, on_hand - reserved - held - safety_stock)


def _cumulative(rows: Iterable[Dated], day: date) -> Decimal:
    return sum((row.quantity for row in rows if row.day <= day), ZERO)


def atp(day: date, on_hand: Decimal, incoming: Sequence[Dated], promises: Sequence[Dated],
        safety_stock: Decimal = ZERO) -> Decimal:
    """ATP(D). The minimum over t >= D only needs the days where S or C changes, plus D itself."""
    checkpoints = {day} | {row.day for row in (*incoming, *promises) if row.day > day}
    lowest = min(on_hand + _cumulative(incoming, t) - _cumulative(promises, t) for t in checkpoints)
    return max(ZERO, lowest - safety_stock)


def earliest_full_date(quantity: Decimal, from_day: date, horizon_days: int, on_hand: Decimal,
                       incoming: Sequence[Dated], promises: Sequence[Dated], safety_stock: Decimal = ZERO) -> date | None:
    """First day in [from_day, from_day + horizon] on which ATP covers the full quantity, or None (IF-1 counter rule)."""
    last = from_day + timedelta(days=horizon_days)
    candidates = sorted({from_day} | {row.day for row in incoming if from_day < row.day <= last})
    for candidate in candidates:  # ATP can only rise on a day when supply arrives
        if atp(candidate, on_hand, incoming, promises, safety_stock) >= quantity:
            return candidate
    return None


def uncovered_promises(on_hand: Decimal, incoming: Sequence[Dated], promises: Sequence[Dated]) -> list[tuple[str, Decimal]]:
    """Promises that supply no longer covers, walked in due-day order then commit order (quantity_accounting.md §5.3).
    Returns (ref, missing quantity) for each uncovered promise. Safety stock does not count here: it limits new
    promises only (invariant 2)."""
    result: list[tuple[str, Decimal]] = []
    promised = missing_so_far = ZERO
    for promise in sorted(promises, key=lambda p: (p.day, p.order)):
        promised += promise.quantity
        shortfall = promised - (on_hand + _cumulative(incoming, promise.day))
        missing = max(ZERO, min(promise.quantity, shortfall - missing_so_far))
        if missing > 0:
            result.append((promise.ref, missing))
            missing_so_far += missing
    return result
