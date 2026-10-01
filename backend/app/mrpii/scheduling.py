"""Backward scheduling in whole-day buckets."""

from datetime import date, timedelta


def backward_schedule(due_date: date, production_lead_time_days: int) -> tuple[date, date]:
    """Return (planned_start, planned_end): the plan ends on the due date and starts one lead time earlier."""
    return due_date - timedelta(days=production_lead_time_days), due_date
