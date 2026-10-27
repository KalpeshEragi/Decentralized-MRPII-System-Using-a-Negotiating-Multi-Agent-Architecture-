"""`planning` schema of the Planning Agent (planning_agent/4_planning_agent_database.md).

Simplifications against note 4 for step 5 (same meaning): a production order keeps its per-day schedule as JSON
(`steps`) instead of a separate steps table; a case keeps its negotiation sessions as JSON. Pegs, procurement demand
lines and procurement requests come with procurement and replanning in step 6.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.owner_tables import AuditMixin, LedgerMixin
from app.core.platform_base import PlatformBase
from app.core.work_runner import QueueMixin
from app.events.models import EventVersionMixin

SCHEMA = "planning"


class WorkCenter(PlatformBase):
    __tablename__ = "work_centers"
    __table_args__ = {"schema": SCHEMA}

    code: Mapped[str] = mapped_column(String, primary_key=True)
    machine_hours_per_day: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class WorkCenterDay(PlatformBase):
    __tablename__ = "work_center_days"
    __table_args__ = {"schema": SCHEMA}

    work_center: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    capacity_hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    committed_hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    held_hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)


class MachineHoursLedger(LedgerMixin, PlatformBase):
    __tablename__ = "machine_hours_ledger"
    __table_args__ = (UniqueConstraint("source_id", "line_no"), {"schema": SCHEMA})


class CustomerDemand(PlatformBase):
    __tablename__ = "customer_demands"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_ref: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sales_inquiry_id: Mapped[str] = mapped_column(String, nullable=False)
    sales_order_number: Mapped[str | None] = mapped_column(String)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    requested_day: Mapped[date] = mapped_column(Date, nullable=False)
    order_day: Mapped[date] = mapped_column(Date, nullable=False)
    committed_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    committed_day: Mapped[date | None] = mapped_column(Date)
    quantity_shipped: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    chosen_option_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String, nullable=False, default="RECEIVED")
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Option(PlatformBase):
    __tablename__ = "options"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    demand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # REQUESTED, LATER_DATE, LESS_QUANTITY
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    delivery_day: Mapped[date] = mapped_column(Date, nullable=False)
    held: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="OFFERED")
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False)  # the plan behind the option (production, needs)


class Case(PlatformBase):
    """Why negotiations happen: one case per attempt to secure (or commit) an option."""

    __tablename__ = "cases"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    demand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    option_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # NEW_REQUEST
    auto_commit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="OPEN")  # OPEN, AGREED, COMMITTING, ...
    sessions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # session id -> {owner, status}
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteRound(PlatformBase):
    """One round of quotes for a new customer request (DC-1, QD-1): what was asked of which owner and what each
    quoted. Planning plans from the quotes when every owner has answered."""

    __tablename__ = "quote_rounds"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String, primary_key=True)  # also the negotiation case id of its quote sessions
    demand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="QUOTING")  # QUOTING, PLANNED
    sessions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # session id -> {owner, need, ...}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionOrder(PlatformBase):
    __tablename__ = "production_orders"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    demand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    option_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    start_day: Mapped[date] = mapped_column(Date, nullable=False)
    end_day: Mapped[date] = mapped_column(Date, nullable=False)
    for_kind: Mapped[str] = mapped_column(String, nullable=False)  # CUSTOMER_DEMAND or PRODUCTION_ORDER
    for_ref: Mapped[str] = mapped_column(String, nullable=False)
    steps: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{work_center, skill, crew, hours_by_day}]
    status: Mapped[str] = mapped_column(String, nullable=False, default="PLANNED")
    quantity_completed: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorkItem(QueueMixin, PlatformBase):
    __tablename__ = "work_items"
    __table_args__ = {"schema": SCHEMA}


class SalesOutbox(QueueMixin, PlatformBase):
    """Planning results waiting to be sent to Sales door 3 (PB-2)."""

    __tablename__ = "sales_outbox"
    __table_args__ = {"schema": SCHEMA}


class ShopFloorReport(PlatformBase):
    __tablename__ = "shop_floor_reports"
    __table_args__ = {"schema": SCHEMA}

    report_id: Mapped[str] = mapped_column(String, primary_key=True)
    production_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # STARTED, QUANTITY_COMPLETED
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventVersion(EventVersionMixin, PlatformBase):
    __tablename__ = "event_versions"
    __table_args__ = {"schema": SCHEMA}


class AuditLog(AuditMixin, PlatformBase):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": SCHEMA}
