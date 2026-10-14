"""The only code that reads and writes the Sales Agent tables (decision A.3: nothing else touches the database directly).

The functions that save only add and flush the rows. The caller (the manager) decides when to commit.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.sales_agent.models import (
    AuditLog, Conversation, Customer, CustomerMemory, Inquiry, Message, Option, Order, Product,
)
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
    db: Session, conversation_id: uuid.UUID, direction: str, text: str, delivery_status: str | None = None,
    provider_message_id: str | None = None,
) -> Message:
    # The time is set here, not by the database: the database would use the start of the whole transaction, and a
    # reply saved after a long model call could then appear before a message the customer sent while we were waiting.
    message = Message(
        conversation_id=conversation_id, direction=direction, text=text, delivery_status=delivery_status,
        provider_message_id=provider_message_id, created_at=datetime.now(timezone.utc),
    )
    db.add(message)
    db.flush()
    return message


def find_message_by_provider_id(db: Session, conversation_id: uuid.UUID, provider_message_id: str) -> Message | None:
    return db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id, Message.provider_message_id == provider_message_id
        )
    )


def list_unprocessed_incoming(db: Session, conversation_id: uuid.UUID) -> list[Message]:
    """The customer's messages that have not been answered yet, oldest first."""
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.direction == "IN", Message.processed.is_(False))
            .order_by(Message.created_at, Message.id)
        )
    )


def mark_messages_processed(db: Session, message_ids: list[uuid.UUID]) -> None:
    """Only the messages the model actually saw. A message that arrived during the turn stays for the next one."""
    db.execute(update(Message).where(Message.id.in_(message_ids)).values(processed=True))


def list_messages_after(db: Session, conversation_id: uuid.UUID, after: Message | None) -> list[Message]:
    """The messages of the conversation, oldest first; only the ones after `after` if it is given."""
    query = select(Message).where(Message.conversation_id == conversation_id)
    if after is not None:
        query = query.where(
            (Message.created_at > after.created_at) | ((Message.created_at == after.created_at) & (Message.id > after.id))
        )
    return list(db.scalars(query.order_by(Message.created_at, Message.id)))


def get_message(db: Session, message_id: uuid.UUID) -> Message | None:
    return db.get(Message, message_id)


def find_last_outgoing_before(db: Session, conversation_id: uuid.UUID, message: Message) -> Message | None:
    """The last thing we said before this customer message."""
    return db.scalar(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.direction == "OUT", Message.created_at < message.created_at)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )


# -- one worker at a time per conversation --------------------------------------------------------------------------


def try_claim_conversation(db: Session, conversation_id: uuid.UUID) -> bool:
    """Take the conversation for answering. False if another worker already has it. Committed at once."""
    result = db.execute(
        update(Conversation).where(Conversation.id == conversation_id, Conversation.busy.is_(False)).values(busy=True)
    )
    db.commit()
    return result.rowcount == 1


def release_conversation(db: Session, conversation_id: uuid.UUID) -> None:
    db.rollback()  # leave nothing half-done from a failed turn
    db.execute(update(Conversation).where(Conversation.id == conversation_id).values(busy=False))
    db.commit()


def release_all_conversations(db: Session) -> None:
    """At startup: a conversation still marked busy belongs to a worker that died with the previous run."""
    db.execute(update(Conversation).where(Conversation.busy.is_(True)).values(busy=False))
    db.commit()


def count_consecutive_ai_failures(db: Session, conversation_id: uuid.UUID) -> int:
    """How many times in a row the model failed, counting back from now until the last successful turn."""
    events = db.scalars(
        select(AuditLog.event_type)
        .where(AuditLog.conversation_id == conversation_id, AuditLog.event_type.in_(("AI_TURN", "AI_FAILED")))
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
    )
    count = 0
    for event_type in events:
        if event_type != "AI_FAILED":
            break
        count += 1
    return count


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


def create_customer(db: Session, phone: str) -> Customer:
    """A new customer, made when a first order is confirmed. The name is not known."""
    customer = Customer(phone=phone)
    db.add(customer)
    db.flush()
    return customer


def create_order(
    db: Session, order_number: str, inquiry: Inquiry, option: Option, customer_id: uuid.UUID, confirmed_at: datetime
) -> Order:
    """The confirmed order. Product, quantity and date are copied from the inquiry and the option Planning gave."""
    order = Order(
        order_number=order_number, customer_id=customer_id, inquiry_id=inquiry.id, option_id=option.id,
        product_id=inquiry.product_id, quantity=option.quantity, delivery_date=option.delivery_date, confirmed_at=confirmed_at,
    )
    db.add(order)
    db.flush()
    return order


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
    db.add(AuditLog(
        actor=actor, event_type=event_type, details=details, conversation_id=conversation_id, inquiry_id=inquiry_id,
        created_at=datetime.now(timezone.utc),  # the time of the event, not the start of the transaction
    ))
    db.flush()


# -- looking things up for the doors --------------------------------------------------------------------------------


def get_conversation(db: Session, conversation_id: uuid.UUID) -> Conversation | None:
    return db.get(Conversation, conversation_id)


def get_inquiry(db: Session, inquiry_id: uuid.UUID) -> Inquiry | None:
    return db.get(Inquiry, inquiry_id)


def get_customer(db: Session, customer_id: uuid.UUID) -> Customer | None:
    return db.get(Customer, customer_id)


def list_options(db: Session, inquiry_id: uuid.UUID) -> list[Option]:
    return list(db.scalars(select(Option).where(Option.inquiry_id == inquiry_id).order_by(Option.created_at, Option.id)))


def list_open_conversations(db: Session, channel: str) -> list[Conversation]:
    return list(db.scalars(select(Conversation).where(Conversation.channel == channel, Conversation.status != "CLOSED")))


# -- planning requests and options ----------------------------------------------------------------------------------


def find_inquiry_by_request_ref(db: Session, request_ref: str) -> Inquiry | None:
    return db.scalar(select(Inquiry).where(Inquiry.planning_request_ref == request_ref))


def save_options(db: Session, inquiry_id: uuid.UUID, options: list[dict]) -> list[Option]:
    """Save Planning's options in the order given. Each option's time is one microsecond after the one before, so the
    order is kept when they are read back."""
    start = datetime.now(timezone.utc)
    rows = [
        Option(
            inquiry_id=inquiry_id, kind=o["kind"], quantity=o["quantity"], delivery_date=o["delivery_date"],
            reason_code=o.get("reason_code"), created_at=start + timedelta(microseconds=position),
        )
        for position, o in enumerate(options)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def release_options(db: Session, inquiry_id: uuid.UUID) -> None:
    """The customer will not take these options (the request changed or was dropped)."""
    db.execute(update(Option).where(Option.inquiry_id == inquiry_id, Option.status == "OFFERED").values(status="RELEASED"))
