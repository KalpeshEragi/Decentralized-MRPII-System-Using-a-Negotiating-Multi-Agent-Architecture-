"""The read-only tools the Sales Agent may request (tools 1 to 5 in dev_docs/sales_agent/2_sales_agent_functions.md).

A tool asks the data access layer, or the rules, and returns plain data (text, numbers, lists) that the language model
can read. The tools that save or promise something (send to Planning, save a preference, record a confirmation, ...)
come in a later checkpoint.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.sales_agent import data_access, rules
from app.sales_agent.data_access import PastOrder

MAX_MEMORY_ITEMS = 10
MAX_ORDERS_IN_HISTORY = 5

# How an order status is said to the customer.
STATUS_IN_WORDS = {"CONFIRMED": "confirmed"}


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _order_to_dict(order: PastOrder) -> dict[str, Any]:
    return {
        "order_number": order.order_number,
        "product": order.product_name,
        "quantity": _number(order.quantity),
        "requested_date": _day(order.requested_date),
        "delivery_date": _day(order.delivery_date),
        "status": order.status,
        "confirmed_on": _day(order.confirmed_at.date()),
    }


def get_customer_info(db: Session, phone: str) -> dict[str, Any]:
    """The customer with this phone number and what we saved about them, or {"found": False}.

    `memory` holds the saved preferences (the customer said it, source STATED) and insights (our rules found it,
    source INFERRED), so the agent can tell them apart.
    """
    customer = data_access.find_customer_by_phone(db, phone)
    if customer is None:
        return {"found": False}
    memory = data_access.list_active_memory(db, customer.id, MAX_MEMORY_ITEMS)
    return {
        "found": True,
        "customer": {"id": str(customer.id), "name": customer.name, "phone": customer.phone},
        "memory": [
            {"kind": m.kind, "type": m.type, "value": m.value, "scope": m.scope, "source": m.source, "strength": m.strength}
            for m in memory
        ],
    }


def get_order_history(db: Session, customer_id: uuid.UUID, limit: int = MAX_ORDERS_IN_HISTORY) -> dict[str, Any]:
    """The customer's latest confirmed orders, newest first."""
    orders = data_access.list_recent_orders(db, customer_id, min(limit, MAX_ORDERS_IN_HISTORY))
    return {"orders": [_order_to_dict(order) for order in orders]}


def get_product_list(db: Session) -> dict[str, Any]:
    """The products we can sell."""
    products = data_access.list_active_products(db)
    return {"products": [{"id": str(p.id), "sku": p.sku, "name": p.name} for p in products]}


def check_order_details(db: Session, product, quantity, requested_date, today: date) -> dict[str, Any]:
    """Are the product, quantity and date valid? The answer comes from our rules, not from the language model."""
    result = rules.check_order_details(data_access.list_active_products(db), product, quantity, requested_date, today)
    answer = result.model_dump(mode="json")
    if result.quantity is not None:
        answer["quantity"] = _number(result.quantity)  # a number, not the text "500"
    return answer


def get_order_status(db: Session, customer_id: uuid.UUID | None, order_number: str | None = None) -> dict[str, Any]:
    """The status of one of this customer's orders (the latest one if no order number is given).

    An order that belongs to someone else gets the same answer as an order that does not exist, so one customer can
    never learn about another customer's orders.
    """
    if customer_id is None:
        return {"found": False, "message": "No order was found."}
    if order_number:
        order = data_access.find_order_by_number(db, customer_id, order_number.strip())
    else:
        latest = data_access.list_recent_orders(db, customer_id, 1)
        order = latest[0] if latest else None
    if order is None:
        return {"found": False, "message": "No order was found."}

    status_in_words = STATUS_IN_WORDS.get(order.status, order.status.lower())
    return {
        "found": True,
        **_order_to_dict(order),
        "status_in_words": status_in_words,
        "message": (
            f"Order {order.order_number} for {_number(order.quantity)} x {order.product_name} is {status_in_words}. "
            f"Delivery date: {order.delivery_date.isoformat()}."
        ),
    }
