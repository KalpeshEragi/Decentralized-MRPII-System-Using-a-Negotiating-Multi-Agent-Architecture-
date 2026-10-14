"""The only code that reads the Sales Agent tables for the tools (decision A.3: tools never touch the database directly).

In this checkpoint everything here is read-only. Saving (messages, inquiries, orders, memory) comes later.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.sales_agent.models import Customer, CustomerMemory, Inquiry, Order, Product
from app.sales_agent.rules import normalize_phone


class PastOrder(NamedTuple):
    """One confirmed order, with the date the customer originally asked for (from the inquiry it came from)."""

    order_number: str
    product_name: str
    quantity: Decimal
    requested_date: date | None
    delivery_date: date
    status: str
    confirmed_at: datetime


def find_customer_by_phone(db: Session, phone: str) -> Customer | None:
    """The customer with this phone number, or None. Customers are saved with their phone number cleaned the same way."""
    return db.scalar(select(Customer).where(Customer.phone == normalize_phone(phone)))


def list_active_products(db: Session) -> list[Product]:
    return list(db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.name)))


def list_active_memory(db: Session, customer_id: uuid.UUID, limit: int) -> list[CustomerMemory]:
    """The saved preferences and insights that are still valid, newest first."""
    query = (
        select(CustomerMemory)
        .where(CustomerMemory.customer_id == customer_id, CustomerMemory.status == "ACTIVE")
        .order_by(CustomerMemory.updated_at.desc(), CustomerMemory.id)
        .limit(limit)
    )
    return list(db.scalars(query))


def _past_orders_query(customer_id: uuid.UUID):
    """This customer's orders, newest first."""
    return (
        select(
            Order.order_number, Product.name, Order.quantity, Inquiry.requested_date, Order.delivery_date,
            Order.status, Order.confirmed_at,
        )
        .join(Product, Product.id == Order.product_id)
        .join(Inquiry, Inquiry.id == Order.inquiry_id)
        .where(Order.customer_id == customer_id)
        .order_by(Order.confirmed_at.desc(), Order.order_number.desc())
    )


def list_recent_orders(db: Session, customer_id: uuid.UUID, limit: int) -> list[PastOrder]:
    return [PastOrder(*row) for row in db.execute(_past_orders_query(customer_id).limit(limit))]


def find_order_by_number(db: Session, customer_id: uuid.UUID, order_number: str) -> PastOrder | None:
    """The order with this number, but only if it belongs to this customer."""
    row = db.execute(_past_orders_query(customer_id).where(Order.order_number == order_number)).first()
    return PastOrder(*row) if row else None
