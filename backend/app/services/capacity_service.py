"""Production parameters per product: production lead time and capacity_per_day.

They are fixture/config values, not database columns (P0-11, P0-14; decided in Phase 2). The X1 values live in
`app/data/x1_fixture.py`; a new product needs an entry there (or in a later config source).
"""

from collections.abc import Iterable

from app.core.errors import AppError, ErrorCode
from app.data.x1_fixture import PRODUCTION
from app.schemas.domain import ProductionParameters


def production_parameters(item_ids: Iterable[str]) -> dict[str, ProductionParameters]:
    missing = [item_id for item_id in item_ids if item_id not in PRODUCTION]
    if missing:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "no production parameters (lead time, capacity per day) are configured for the ordered product",
            [{"field": "lines.item_id", "issue": f"no production parameters for {item_id}"} for item_id in missing],
        )
    return {item_id: PRODUCTION[item_id] for item_id in item_ids}
