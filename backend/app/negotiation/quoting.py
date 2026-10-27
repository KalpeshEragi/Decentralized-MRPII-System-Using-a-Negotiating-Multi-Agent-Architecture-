"""Quote helpers (QD-1): formatting only, no business decisions.

An owner that quotes availability over days (stock it can promise, free worker-hours, free receiving) sends it as
steps: one option per day on which the value changes, "from this day on: this much". `value_on` reads it back.
"""

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from decimal import Decimal

from app.negotiation.envelope import Terms

ZERO = Decimal(0)


def steps(asked: Terms, start: date, end: date, value: Callable[[date], Decimal], kind: str) -> list[Terms]:
    """One option per change of `value(day)` between `start` and `end` (both included)."""
    options, last, day = [], None, start
    while day <= end:
        current = max(Decimal(value(day)), ZERO)
        if current != last:
            options.append(Terms(resource_type=asked.resource_type, resource_ref=asked.resource_ref, quantity=current,
                                 unit=asked.unit, available_from=day, order_id=asked.order_id, extra={"kind": kind}))
            last = current
        day += timedelta(days=1)
    return options


def value_on(options: Iterable[Terms] | Iterable[dict], day: date) -> Decimal:
    """The value a step quote gives for `day` (0 before its first step)."""
    found = ZERO
    for option in sorted((o if isinstance(o, Terms) else Terms.model_validate(o) for o in options),
                         key=lambda o: o.available_from or date.min):
        if option.available_from and option.available_from <= day:
            found = option.quantity
    return found


def quote_window(asked: Terms, today: date) -> tuple[date, date]:
    start = asked.date_from or today
    return start, max(start, asked.date_to or start)
