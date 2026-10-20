"""The Sales Agent tables as Python classes. They match migration 003 and the design in
dev_docs/sales_agent/4_sales_agent_database.md.

These classes use their own base (`SalesAgentBase`), not the project's shared `Base`. The demo reset
(`app.data.seed_data.reset`) empties every table of the shared base, so Sales Agent data is safe from it.

The allowed values of each status are enforced by the database (CHECK constraints in the migration). They are listed
in the comments here so that the code is easy to read.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, MetaData, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.events.models import EventVersionMixin

SCHEMA = "sales_agent"


class SalesAgentBase(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def foreign_key(target: str, nullable: bool = True, circular_name: str | None = None) -> Mapped[uuid.UUID | None]:
    """A link to another table. `circular_name` is only for the two links that point back and forth between
    tables (conversations <-> inquiries, inquiries <-> options): it lets SQLAlchemy order the tables safely."""
    foreign_key_args = {"use_alter": True, "name": circular_name} if circular_name else {}
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.{target}", **foreign_key_args), nullable=nullable)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Customer(SalesAgentBase):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = uuid_pk()
    phone: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Product(SalesAgentBase):
    """Reference data that Sales only reads. Later replaced by a link to the shared product list."""

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = uuid_pk()
    sku: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Conversation(SalesAgentBase):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID | None] = foreign_key("customers.id")  # empty for an unknown number
    channel: Mapped[str] = mapped_column(String)  # TEST, WHATSAPP, SIMULATED (structured simulated customers, DM-7)
    sender_ref: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN, IDLE, CLOSED
    current_inquiry_id: Mapped[uuid.UUID | None] = foreign_key("inquiries.id", circular_name="fk_conversations_current_inquiry")
    busy: Mapped[bool] = mapped_column(Boolean, default=False)  # true while one turn is being processed
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Message(SalesAgentBase):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = foreign_key("conversations.id", nullable=False)
    direction: Mapped[str] = mapped_column(String)  # IN (from the customer), OUT (from us)
    provider_message_id: Mapped[str | None] = mapped_column(String)  # the channel's id; a repeat delivery is refused
    text: Mapped[str] = mapped_column(Text)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)  # only meaningful for IN messages
    delivery_status: Mapped[str | None] = mapped_column(String)  # OUT only: QUEUED, SENT, FAILED
    created_at: Mapped[datetime] = created_at()


class Inquiry(SalesAgentBase):
    """The customer's request, before it is an order."""

    __tablename__ = "inquiries"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = foreign_key("conversations.id", nullable=False)
    customer_id: Mapped[uuid.UUID | None] = foreign_key("customers.id")
    # GATHERING, WAITING_FOR_PLANNING, OPTIONS_PRESENTED, AWAITING_CONFIRMATION, CONFIRMED, NEEDS_STAFF, CLOSED
    stage: Mapped[str] = mapped_column(String, default="GATHERING")
    closed_reason: Mapped[str | None] = mapped_column(String)  # NO_OPTION, DECLINED, EXPIRED, ABANDONED, REPLACED
    product_id: Mapped[uuid.UUID | None] = foreign_key("products.id")  # product, quantity and date stay empty until known
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    requested_date: Mapped[date | None] = mapped_column(Date)
    offer_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selected_option_id: Mapped[uuid.UUID | None] = foreign_key("options.id", circular_name="fk_inquiries_selected_option")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_message_id: Mapped[uuid.UUID | None] = foreign_key("messages.id")  # the message with the "yes"
    planning_request_ref: Mapped[str | None] = mapped_column(String, unique=True)
    planning_request: Mapped[dict | None] = mapped_column(JSONB)  # what we sent to Planning, with the customer context
    planning_result: Mapped[dict | None] = mapped_column(JSONB)  # what Planning answered
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Option(SalesAgentBase):
    """One option Planning offered. Quantity and date are copied exactly from Planning's answer."""

    __tablename__ = "options"

    id: Mapped[uuid.UUID] = uuid_pk()
    inquiry_id: Mapped[uuid.UUID] = foreign_key("inquiries.id", nullable=False)
    kind: Mapped[str] = mapped_column(String)  # REQUESTED, LATER_DATE, LESS_QUANTITY, PART_NOW_REST_LATER
    quantity: Mapped[Decimal] = mapped_column(Numeric)
    delivery_date: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="OFFERED")  # OFFERED, SELECTED, EXPIRED, RELEASED
    created_at: Mapped[datetime] = created_at()


class Order(SalesAgentBase):
    """A confirmed customer order. Only created after the customer's explicit confirmation."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_number: Mapped[str] = mapped_column(String, unique=True)
    customer_id: Mapped[uuid.UUID] = foreign_key("customers.id", nullable=False)
    inquiry_id: Mapped[uuid.UUID] = foreign_key("inquiries.id", nullable=False)  # unique: one order per inquiry
    option_id: Mapped[uuid.UUID] = foreign_key("options.id", nullable=False)  # unique: one order per option
    product_id: Mapped[uuid.UUID] = foreign_key("products.id", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric)
    delivery_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, default="CONFIRMED")
    payment_status: Mapped[str] = mapped_column(String, default="ASSUMED_PAID")  # prototype: payment is assumed
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class CustomerMemory(SalesAgentBase):
    """A saved preference (the customer said it) or insight (our rules found it). Facts are not stored here."""

    __tablename__ = "customer_memory"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = foreign_key("customers.id", nullable=False)
    kind: Mapped[str] = mapped_column(String)  # PREFERENCE, INSIGHT
    type: Mapped[str] = mapped_column(String)  # from a fixed list, see migration 003
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    scope: Mapped[str] = mapped_column(String, default="GENERAL")  # GENERAL, or THIS_ORDER (then inquiry_id is set)
    inquiry_id: Mapped[uuid.UUID | None] = foreign_key("inquiries.id")
    source: Mapped[str] = mapped_column(String)  # STATED (customer said it), INFERRED (our rule found it)
    strength: Mapped[str | None] = mapped_column(String)  # LOW, MEDIUM, HIGH; inferred only
    status: Mapped[str] = mapped_column(String, default="ACTIVE")  # ACTIVE, SUPERSEDED, RETIRED
    evidence: Mapped[list] = mapped_column(JSONB, default=list)  # what supports it, e.g. a message or an order
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AuditLog(SalesAgentBase):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor: Mapped[str] = mapped_column(String)  # SALES_AI, SYSTEM, PLANNING, HUMAN
    event_type: Mapped[str] = mapped_column(String)  # for example AI_TURN, CHECK_FAILED, OPTIONS_PRESENTED
    conversation_id: Mapped[uuid.UUID | None] = foreign_key("conversations.id")
    inquiry_id: Mapped[uuid.UUID | None] = foreign_key("inquiries.id")
    details: Mapped[dict] = mapped_column(JSONB, default=dict)  # rules checked, reasons, the AI's structured answer
    created_at: Mapped[datetime] = created_at()


class EventVersion(EventVersionMixin, SalesAgentBase):
    """The last applied version of each entity Sales follows through events (stale check; migration 017)."""

    __tablename__ = "event_versions"
