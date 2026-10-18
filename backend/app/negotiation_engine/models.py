"""The Negotiation Engine tables (schema `negotiation_engine`, dev_docs/OVERALL_DATABASE_SCHEMA.md §8). They match migration 004.

Own declarative base, like the Sales Agent. Protocol state only: no business decisions are stored here. Other modules
use `service.py`, never these classes.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, MetaData, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "negotiation_engine"


class NegotiationEngineBase(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def session_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.negotiation_sessions.id"))


class NegotiationSession(NegotiationEngineBase):
    __tablename__ = "negotiation_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_type: Mapped[str] = mapped_column(String)  # PURCHASING_SUPPLIER
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN, AGREED, REJECTED, TIMED_OUT, CANCELLED
    status_reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # the Procurement Request
    objective: Mapped[dict] = mapped_column(JSONB)  # item, quantity, required date; never price
    round_count: Mapped[int] = mapped_column(Integer, default=0)
    max_rounds: Mapped[int] = mapped_column(Integer, default=3)
    response_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NegotiationParticipant(NegotiationEngineBase):
    __tablename__ = "negotiation_participants"
    __table_args__ = (UniqueConstraint("session_id", "participant_type", "participant_ref"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = session_fk()
    participant_type: Mapped[str] = mapped_column(String)  # AGENT, SUPPLIER
    participant_ref: Mapped[str] = mapped_column(String)  # agent code or supplier ID, validated on write
    role: Mapped[str] = mapped_column(String)  # INITIATOR, RESPONDENT
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NegotiationMessage(NegotiationEngineBase):
    __tablename__ = "negotiation_messages"
    __table_args__ = (UniqueConstraint("session_id", "sequence_number"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = session_fk()
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)  # sender-supplied; duplicates ignored
    sequence_number: Mapped[int] = mapped_column(Integer)
    round_number: Mapped[int] = mapped_column(Integer)
    sender_type: Mapped[str] = mapped_column(String)  # AGENT, SUPPLIER
    sender_ref: Mapped[str] = mapped_column(String)
    # Purchasing: OFFER, COUNTER_OFFER, CLARIFICATION_REQUEST, CANCEL, CONFIRMATION (migration 005).
    # Supplier: ACCEPT, COUNTER_OFFER, REJECT, UNCLEAR.
    message_type: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    terms: Mapped[dict | None] = mapped_column(JSONB)  # quantity, delivery_date; never price
    interpretation_source: Mapped[str | None] = mapped_column(String)  # supplier messages only: LLM, FALLBACK_PARSER
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
