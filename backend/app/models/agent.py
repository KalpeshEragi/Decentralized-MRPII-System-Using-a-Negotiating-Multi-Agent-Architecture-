"""agent schema: agents, agent_state (state content is C6, populated from Phase 3)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = {"schema": "agent"}

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_code: Mapped[str] = mapped_column(String, unique=True)
    agent_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime | None] = created_at()


class AgentState(Base):
    __tablename__ = "agent_state"
    __table_args__ = {"schema": "agent"}

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.agents.id"), primary_key=True)
    current_goal: Mapped[dict | None] = mapped_column(JSONB)
    preferred_terms: Mapped[dict | None] = mapped_column(JSONB)
    reserved_limits: Mapped[dict | None] = mapped_column(JSONB)
    initial_proposal: Mapped[dict | None] = mapped_column(JSONB)
    own_offer_history: Mapped[list | None] = mapped_column(JSONB)
    opponent_offer_history: Mapped[list | None] = mapped_column(JSONB)
    dialogue_history: Mapped[list | None] = mapped_column(JSONB)
    negotiation_rules: Mapped[dict | None] = mapped_column(JSONB)
    current_task: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
