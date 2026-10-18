"""Purchasing's message templates for the supplier chat. The terms are always computed by our own code; this only
words them. Templates never mention a price. Offers, counter-offers and clarification requests may be reworded by the
LLM (`writer.py`); these templates are the fallback, and the echo and closing messages are always sent as written here.
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


def reply_terms(quantity: Decimal | None, delivery_date: date | None) -> dict:
    """The terms read from a supplier's counter-offer. A term the supplier didn't state stays empty."""
    return {"quantity": quantity_text(quantity) if quantity is not None else None,
            "delivery_date": delivery_date.isoformat() if delivery_date is not None else None}


def offer_text(supplier_name: str, item_name: str, sku: str, quantity: Decimal, delivery_date: date) -> str:
    return (
        f"Hello {supplier_name}, this is Purchasing. We would like to order {quantity_text(quantity)} units of "
        f"{item_name} ({sku}), delivered by {delivery_date.isoformat()}. {REPLY_FORMAT}"
    )


def understood_text(action: str, quantity: Decimal | None, delivery_date: date | None) -> str:
    """The echo of how Purchasing read the supplier's reply, so misunderstandings are visible."""
    if action == "ACCEPT":
        return "Understood: you accept our offer."
    if action == "REJECT":
        return "Understood: you cannot supply this order."
    if delivery_date is None:
        return f"Understood: {quantity_text(quantity)} units, with no delivery date given."
    if quantity is None:
        return f"Understood: delivery by {delivery_date.isoformat()}, with no quantity given."
    return f"Understood: {quantity_text(quantity)} units by {delivery_date.isoformat()}."


def agreed_text(echo: str, quantity: Decimal, delivery_date: date) -> str:
    return f"{echo} Agreed: {quantity_text(quantity)} units, delivered by {delivery_date.isoformat()}. Thank you."


def counter_text(echo: str, quantity: Decimal, delivery_date: date, required_date: date) -> str:
    return (
        f"{echo} We need {quantity_text(quantity)} units delivered by {required_date.isoformat()}; this date cannot "
        f"change. Our offer: {quantity_text(quantity)} units by {delivery_date.isoformat()}. {REPLY_FORMAT}"
    )


def revised_offer_text(quantity: Decimal, delivery_date: date) -> str:
    """To a supplier whose Leg quantity changed because the procurement was reallocated among its suppliers."""
    return (
        f"We have rearranged this procurement among our suppliers, so our order to you has changed. Our revised "
        f"offer: {quantity_text(quantity)} units by {delivery_date.isoformat()}. {REPLY_FORMAT}"
    )


def closed_text(echo: str, reason: str) -> str:
    """`echo` is empty when the reply could not be read."""
    if reason == "round_limit_exceeded":
        closing = "We could not agree within the round limit, so we have closed this negotiation."
    elif reason == "unclear_response":
        closing = "We still could not read your reply, so we have closed this negotiation; nothing will be ordered."
    else:
        closing = "We have closed this negotiation. Thank you for your reply."
    return f"{echo} {closing}".strip()


CLARIFICATION_TEXT = f"Sorry, we could not read your reply. {REPLY_FORMAT}"


def clarification_text(echo: str) -> str:
    """`echo` is empty when the reply could not be read; otherwise it was read but a term is missing."""
    if not echo:
        return CLARIFICATION_TEXT
    return f"{echo} Please give both the quantity and the delivery date. {REPLY_FORMAT}"

# To a supplier whose Leg is aborted because another Leg of the procurement failed.
CANCELLED_TEXT = "This procurement could not be completed, so we have cancelled this order; nothing will be ordered."

# To a supplier dropped when the procurement was reallocated among its other suppliers.
NO_LONGER_NEEDED_TEXT = ("We have rearranged this procurement among our suppliers and no longer need this order, so we "
                         "have cancelled it; nothing will be ordered. Thank you.")

# To a supplier whose order the reallocation had to revise, but whose round limit is already reached.
REVISION_ROUND_LIMIT_TEXT = ("We needed to revise our order to you, but the round limit of this negotiation is reached, "
                             "so we have closed it; nothing will be ordered.")

# To a supplier who did not reply by the response deadline.
TIMEOUT_TEXT = "We did not receive your reply in time, so we have closed this negotiation; nothing will be ordered."

# To every supplier still negotiating or agreed when a procurement is aborted manually.
MANUALLY_ABORTED_TEXT = "This procurement has been stopped, so we have cancelled this order; nothing will be ordered."

# To every supplier of a procurement whose agreement was rejected at approval.
APPROVAL_REJECTED_TEXT = "Our approval of this procurement was declined, so we have cancelled this order; nothing will be ordered."
