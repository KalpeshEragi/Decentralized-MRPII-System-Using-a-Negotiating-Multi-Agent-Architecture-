"""Deterministic supplier feasibility (X1 fixture section 5.1). Supplier data only; no price, no selection.

Which feasible supplier or split to choose is the Purchasing Agent's decision, not made here.
"""

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal

from app.schemas.domain import SupplierOption


def arrival_date(option: SupplierOption, planning_date: date) -> date:
    return planning_date + timedelta(days=option.lead_time_days)


def is_usable(option: SupplierOption, planning_date: date, required_by: date) -> bool:
    """Arrives by required_by and its available quantity reaches its own MOQ."""
    return arrival_date(option, planning_date) <= required_by and option.available_qty >= option.min_order_qty


def covers_alone(option: SupplierOption, planning_date: date, required_by: date, shortage_quantity: Decimal) -> bool:
    return is_usable(option, planning_date, required_by) and option.available_qty >= shortage_quantity


def is_split_feasible(
    allocations: Iterable[tuple[SupplierOption, Decimal]],
    planning_date: date,
    required_by: date,
    shortage_quantity: Decimal,
) -> bool:
    """Every supplier usable with MOQ <= ordered <= available, and the ordered quantities cover the shortage."""
    allocations = list(allocations)
    return all(
        is_usable(option, planning_date, required_by) and option.min_order_qty <= qty <= option.available_qty
        for option, qty in allocations
    ) and sum((qty for _, qty in allocations), Decimal(0)) >= shortage_quantity
