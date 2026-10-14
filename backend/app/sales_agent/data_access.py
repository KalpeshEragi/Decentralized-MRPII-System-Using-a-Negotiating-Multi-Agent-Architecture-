"""The only code that reads and writes the Sales Agent tables (decision A.3: nothing else touches the database directly).

The functions that save only add and flush the rows. The caller (the manager) decides when to commit.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.sales_agent.models import AuditLog, Conversation, Customer, CustomerMemory, Inquiry, Message, Order, Product
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


# -- conversations and messages -------------------------------------------------------------------------------------

FINISHED_STAGES = ("CONFIRMED", "CLOSED")


def find_open_conversation(db: Session, channel: str, sender_ref: str) -> Conversation | None:
    return db.scalar(
        select(Conversation).where(
            Conversation.channel == channel, Conversation.sender_ref == sender_ref, Conversation.status != "CLOSED"
        )
    )


def create_conversation(db: Session, channel: str, sender_ref: str, customer_id: uuid.UUID | None) -> Conversation:
    conversation = Conversation(channel=channel, sender_ref=sender_ref, customer_id=customer_id)
    db.add(conversation)
    db.flush()
    return conversation


def save_message(
    db: Session, conversation_id: uuid.UUID, direction: str, text: str, delivery_status: str | None = None
) -> Message:
    message = Message(conversation_id=conversation_id, direction=direction, text=text, delivery_status=delivery_status)
    db.add(message)
    db.flush()
    return message


def mark_incoming_messages_processed(db: Session, conversation_id: uuid.UUID) -> None:
    """The model has now seen every message the customer sent so far, including any it could not answer earlier."""
    db.execute(
        update(Message)
        .where(Message.conversation_id == conversation_id, Message.direction == "IN", Message.processed.is_(False))
        .values(processed=True)
    )


def list_recent_messages(db: Session, conversation_id: uuid.UUID, limit: int) -> list[Message]:
    """The latest messages of the conversation, oldest first."""
    query = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id)
        .limit(limit)
    )
    return list(reversed(list(db.scalars(query))))


# -- inquiries ------------------------------------------------------------------------------------------------------


def find_active_inquiry(db: Session, conversation_id: uuid.UUID) -> Inquiry | None:
    """The inquiry that is not finished yet (a conversation has at most one)."""
    return db.scalar(
        select(Inquiry).where(Inquiry.conversation_id == conversation_id, Inquiry.stage.not_in(FINISHED_STAGES))
    )


def create_inquiry(db: Session, conversation: Conversation) -> Inquiry:
    inquiry = Inquiry(conversation_id=conversation.id, customer_id=conversation.customer_id)
    db.add(inquiry)
    db.flush()
    conversation.current_inquiry_id = inquiry.id
    return inquiry


def get_product(db: Session, product_id: uuid.UUID) -> Product | None:
    return db.get(Product, product_id)


def close_conversation(db: Session, conversation: Conversation) -> None:
    """End the conversation and give up its unfinished inquiry (used when a tester clears a test chat)."""
    inquiry = find_active_inquiry(db, conversation.id)
    if inquiry is not None:
        inquiry.stage, inquiry.closed_reason = "CLOSED", "ABANDONED"
    conversation.status = "CLOSED"
    db.flush()


# -- audit ----------------------------------------------------------------------------------------------------------


def save_audit_note(
    db: Session, actor: str, event_type: str, details: dict, conversation_id: uuid.UUID | None = None,
    inquiry_id: uuid.UUID | None = None,
) -> None:
    db.add(AuditLog(actor=actor, event_type=event_type, details=details, conversation_id=conversation_id, inquiry_id=inquiry_id))
    db.flush()
