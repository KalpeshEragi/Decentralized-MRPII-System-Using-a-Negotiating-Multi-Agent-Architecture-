"""`negotiation` schema, six-agent tables (negotiation.md §10.3). The old 25% tables of this schema
(`negotiation_sessions`, `negotiation_messages`, ...) stay in `app/models/negotiation.py` until step 5.

- `sessions`: one starter/owner negotiation, with its `case_id` (PD-O3).
- `messages`: every stored message, and at the same time the receiver's inbox queue (standard queue shape).
- `outbox`: messages waiting to be sent over A2A (standard queue shape).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform_base import PlatformBase
from app.core.work_runner import QueueMixin

SCHEMA = "negotiation"


class Session(PlatformBase):
    __tablename__ = "sessions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    resource_ref: Mapped[str] = mapped_column(String, nullable=False)
    starter: Mapped[str] = mapped_column(String, nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    turn: Mapped[str] = mapped_column(String, nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    commit_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_offer: Mapped[dict | None] = mapped_column(JSONB)
    agreed_terms: Mapped[dict | None] = mapped_column(JSONB)
    hold_id: Mapped[str | None] = mapped_column(String)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reason_code: Mapped[str | None] = mapped_column(String)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(QueueMixin, PlatformBase):
    """Stored message = receiver's inbox item. `kind` = message type; `scope_key` = receiver + session (in order)."""

    __tablename__ = "messages"
    __table_args__ = {"schema": SCHEMA}

    message_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.sessions.id"),
                                                  nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sender: Mapped[str] = mapped_column(String, nullable=False)
    receiver: Mapped[str] = mapped_column(String, nullable=False)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Outbox(QueueMixin, PlatformBase):
    """A message waiting to be sent. `scope_key` = session, so one session's messages leave in order."""

    __tablename__ = "outbox"
    __table_args__ = {"schema": SCHEMA}

    message_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    receiver: Mapped[str] = mapped_column(String, nullable=False)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
