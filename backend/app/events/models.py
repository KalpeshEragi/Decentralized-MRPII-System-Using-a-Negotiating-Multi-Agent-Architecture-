"""`events` schema: the event log and one delivery row per (event, subscriber) (pubsub_event_channel.md §5)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform_base import PlatformBase
from app.core.work_runner import QueueMixin

SCHEMA = "events"


class Event(PlatformBase):
    """The envelope (pubsub_event_channel.md §4). Never updated or deleted during a run."""

    __tablename__ = "events"
    __table_args__ = {"schema": SCHEMA}

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    publisher: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    entity_version: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class EventDelivery(QueueMixin, PlatformBase):
    """One subscriber's copy of an event. A standard queue row: `kind` = event type,
    `scope_key` = subscriber + entity, so per-entity order is kept per subscriber (EV-4)."""

    __tablename__ = "event_deliveries"
    __table_args__ = (UniqueConstraint("event_id", "subscriber"), {"schema": SCHEMA})

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.events.event_id"),
                                                nullable=False)
    subscriber: Mapped[str] = mapped_column(String, nullable=False)


class EventVersionMixin:
    """For an agent's own `event_versions` table (stale check, pubsub_event_channel.md §6.3)."""

    entity_type: Mapped[str] = mapped_column(String, primary_key=True)
    entity_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_version: Mapped[int] = mapped_column(Integer, nullable=False)
