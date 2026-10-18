"""Tables of the adapter that connects the Purchasing Agent to the six-agent platform (PI-3, schema `purchasing_link`).
Kept apart from the Purchasing Agent's own schema: Purchasing's tables and rules are unchanged."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform_base import PlatformBase
from app.core.work_runner import QueueMixin
from app.events.models import EventVersionMixin

SCHEMA = "purchasing_link"


class PlanningLink(PlatformBase):
    """One SUPPLY negotiation with Planning and the Procurement Request that serves it."""

    __tablename__ = "planning_links"
    __table_args__ = {"schema": SCHEMA}

    session_id: Mapped[str] = mapped_column(String, primary_key=True)  # the negotiation session with Planning
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)  # core.items id (Planning's item)
    supplier_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # supplier_service.items id
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    needed_by: Mapped[date] = mapped_column(Date, nullable=False)
    for_kind: Mapped[str] = mapped_column(String, nullable=False)
    for_ref: Mapped[str] = mapped_column(String, nullable=False)
    procurement_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # REQUESTED -> NEGOTIATING -> OFFERED -> HELD -> COMMITTED; or FAILED / ABORTED
    status: Mapped[str] = mapped_column(String, nullable=False, default="REQUESTED")
    last_message: Mapped[dict] = mapped_column(JSONB, nullable=False)  # Planning's latest envelope (to reply to)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdapterWork(QueueMixin, PlatformBase):
    """Work that runs outside the inbox transaction, because Purchasing's own functions commit and may call the
    language model: SUBMIT (a Procurement Request), CHECK (follow its status), SUPPLIER_TURN (simulated suppliers)."""

    __tablename__ = "work_items"
    __table_args__ = {"schema": SCHEMA}


class EventVersion(EventVersionMixin, PlatformBase):
    __tablename__ = "event_versions"
    __table_args__ = {"schema": SCHEMA}
