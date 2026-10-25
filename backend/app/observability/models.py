"""`observability` schema: one row per AI model call (SD-3). No prompt text is stored (it may contain customer
messages); the agent's own audit keeps what is needed. Used by the Phase 6 measurements and the demo timeline."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform_base import PlatformBase


class LlmCall(PlatformBase):
    __tablename__ = "llm_calls"
    __table_args__ = {"schema": "observability"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str | None] = mapped_column(String)
    agent: Mapped[str] = mapped_column(String, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)  # e.g. SALES_TURN, PLANNING_RANKING, WORDING
    case_id: Mapped[str | None] = mapped_column(String)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String, nullable=False)  # OK, TIMEOUT, INVALID, ERROR, FALLBACK_USED
    prompt_chars: Mapped[int | None] = mapped_column(Integer)
    output_chars: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String)
