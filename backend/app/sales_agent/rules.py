"""Checks on what the customer tells us. Plain functions: no database and no clock (the caller passes `today`).

The language model only suggests details. This code decides whether they are valid.
"""

import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from app.sales_agent.models import Product


class Problem(BaseModel):
    field: str  # "product", "quantity" or "requested_date"
    message: str


class OrderDetailsCheck(BaseModel):
    """The result of checking product, quantity and date. The cleaned-up values are filled in only when they are valid."""

    valid: bool
    problems: list[Problem]
    product_id: str | None = None
    product_name: str | None = None
    quantity: Decimal | None = None
    requested_date: date | None = None


def normalize_phone(phone: str) -> str:
    """Remove spaces, dashes, dots and brackets, so "+91 98765-43210" and "+919876543210" are the same number."""
    return re.sub(r"[\s\-.()]", "", phone)


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _find_product(products: Sequence[Product], text: str) -> tuple[Product | None, str | None]:
    """The one product whose name or product code matches the text (ignoring capitals and extra spaces)."""
    wanted = _normalize_text(text)
    matches = [p for p in products if wanted in (_normalize_text(p.name), _normalize_text(p.sku))]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"we do not sell a product called '{text.strip()}'"
    return None, f"more than one product matches '{text.strip()}'"


def _read_quantity(value) -> tuple[Decimal | None, str | None]:
    if isinstance(value, bool):  # True would otherwise count as the number 1
        return None, "must be a number"
    try:
        quantity = Decimal(str(value).strip())
    except InvalidOperation:
        return None, "must be a number"
    if not quantity.is_finite():
        return None, "must be a number"
    if quantity <= 0:
        return None, "must be above 0"
    return quantity, None


def _read_date(value, today: date) -> tuple[date | None, str | None]:
    if isinstance(value, date):
        requested = value
    else:
        text = str(value).strip()
        # Only the form YYYY-MM-DD. (date.fromisoformat alone would also accept forms like 20261110 or 2026-W45-2.)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return None, "must be a date written as YYYY-MM-DD"
        try:
            requested = date.fromisoformat(text)
        except ValueError:  # the right form but not a real day, like 2026-13-40
            return None, "must be a date written as YYYY-MM-DD"
    if requested < today:
        return None, "is in the past"
    return requested, None


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def check_order_details(
    products: Sequence[Product], product, quantity, requested_date, today: date
) -> OrderDetailsCheck:
    """Check all three details and report every problem at once, so the customer can fix them in one message.

    `products` are the products we can sell. `today` is passed in, so the result never depends on the clock.
    """
    problems: list[Problem] = []
    found_product = None
    read_quantity = None
    read_date = None

    for field, value in (("product", product), ("quantity", quantity), ("requested_date", requested_date)):
        if _is_missing(value):
            problems.append(Problem(field=field, message="is missing"))

    if not _is_missing(product):
        found_product, problem = _find_product(products, str(product))
        if problem:
            problems.append(Problem(field="product", message=problem))
    if not _is_missing(quantity):
        read_quantity, problem = _read_quantity(quantity)
        if problem:
            problems.append(Problem(field="quantity", message=problem))
    if not _is_missing(requested_date):
        read_date, problem = _read_date(requested_date, today)
        if problem:
            problems.append(Problem(field="requested_date", message=problem))

    if problems:
        return OrderDetailsCheck(valid=False, problems=problems)
    return OrderDetailsCheck(
        valid=True,
        problems=[],
        product_id=str(found_product.id),
        product_name=found_product.name,
        quantity=read_quantity,
        requested_date=read_date,
    )
