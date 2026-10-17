"""Purchasing's message text for the supplier chat. The terms are always computed by our own code; this only words
them. Templates never mention a price. (The LLM-written text with guardrails comes in a later ticket; these templates
remain the fallback.)
"""

from datetime import date
from decimal import Decimal

REPLY_FORMAT = "Please reply ACCEPT, COUNTER <quantity> <yyyy-mm-dd>, or REJECT."


def quantity_text(quantity: Decimal) -> str:
    """500 rather than 500.00 or 5E+2."""
    return format(quantity.normalize(), "f")


def offer_terms(quantity: Decimal, delivery_date: date) -> dict:
    """The structured terms stored with an offer. Never a price."""
    return {"quantity": quantity_text(quantity), "delivery_date": delivery_date.isoformat()}


def offer_text(supplier_name: str, item_name: str, sku: str, quantity: Decimal, delivery_date: date) -> str:
    return (
        f"Hello {supplier_name}, this is Purchasing. We would like to order {quantity_text(quantity)} units of "
        f"{item_name} ({sku}), delivered by {delivery_date.isoformat()}. {REPLY_FORMAT}"
    )
