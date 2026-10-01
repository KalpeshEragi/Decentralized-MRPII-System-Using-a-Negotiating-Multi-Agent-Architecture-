"""Minimal capacity check (P1-03): one capacity_per_day per product, no scheduling."""

import math
from decimal import Decimal

from app.schemas.domain import CapacityCheck, MPSEntry, ProductionParameters


def check_capacity(entry: MPSEntry, params: ProductionParameters) -> CapacityCheck:
    """Feasible iff ceil(planned_quantity / capacity_per_day) <= production_lead_time_days."""
    required_days = math.ceil(entry.planned_quantity / params.capacity_per_day)
    working_days = params.production_lead_time_days
    return CapacityCheck(
        mps_entry_id=entry.id,
        item_id=entry.item_id,
        required_quantity=entry.planned_quantity,
        capacity_per_day=params.capacity_per_day,
        required_days=required_days,
        working_days=working_days,
        max_quantity=params.capacity_per_day * Decimal(working_days),
        feasible=required_days <= working_days,
    )
