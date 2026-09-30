"""audit schema: append-only decision records (C7)."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class DecisionAudit(Base):
    __tablename__ = "decision_audit"
    __table_args__ = {"schema": "audit"}

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.agents.id"))
    decision_type: Mapped[str] = mapped_column(String, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    decision: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = created_at()
