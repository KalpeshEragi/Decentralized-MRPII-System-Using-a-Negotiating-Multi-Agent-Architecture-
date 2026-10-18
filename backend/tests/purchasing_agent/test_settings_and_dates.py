"""Purchasing's working values and the selection date. Plain code: no database."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.purchasing_agent.service import selection_date


def test_the_selection_date_is_the_date_in_the_configured_timezone():
    assert selection_date(datetime(2026, 11, 1, 20, 0, tzinfo=UTC), "Asia/Kolkata") == date(2026, 11, 2)


def test_a_naive_datetime_is_refused_rather_than_read_in_the_host_timezone():
    with pytest.raises(ValueError):
        selection_date(datetime(2026, 11, 2, 10, 0), "Asia/Kolkata")


@pytest.mark.parametrize("field, value", [
    ("purchasing_max_rounds", 0),
    ("purchasing_max_clarifications", -1),
    ("purchasing_response_deadline_hours", 0),
])
def test_working_values_outside_their_bounds_are_refused(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_no_clarifications_is_allowed():
    assert Settings(_env_file=None, purchasing_max_clarifications=0).purchasing_max_clarifications == 0
