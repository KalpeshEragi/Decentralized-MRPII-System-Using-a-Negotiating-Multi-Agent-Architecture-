"""`inventory` schema of the Inventory Agent (inventory_agent/4_inventory_agent_database.md). Inventory is the quantity
truth per item (IN-1); every change is a ledger row + a balance update in one transaction (QA-1)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.owner_tables import AuditMixin, LedgerMixin
from app.core.platform_base import PlatformBase
from app.events.models import EventVersionMixin

SCHEMA = "inventory"


class StockBalance(PlatformBase):
    __tablename__ = "stock_balances"
    __table_args__ = {"schema": SCHEMA}

    item_id: Mapped[str] = mapped_column(String, primary_key=True)
    on_hand: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    reserved: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    held: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    incoming_total: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    safety_stock: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    safety_stock_released: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class StockLedger(LedgerMixin, PlatformBase):
    __tablename__ = "stock_ledger"
    __table_args__ = (UniqueConstraint("source_id", "line_no"), {"schema": SCHEMA})


class Hold(PlatformBase):
    __tablename__ = "holds"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    due_day: Mapped[date] = mapped_column(Date, nullable=False)
    for_kind: Mapped[str] = mapped_column(String, nullable=False)  # CUSTOMER_DEMAND or PRODUCTION_ORDER (ID-2)
    for_ref: Mapped[str] = mapped_column(String, nullable=False)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    negotiation_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    expires_day: Mapped[date] = mapped_column(Date, nullable=False)
    safety_stock_used: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reservation(PlatformBase):
    __tablename__ = "reservations"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    quantity_issued: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    due_day: Mapped[date] = mapped_column(Date, nullable=False)
    for_kind: Mapped[str] = mapped_column(String, nullable=False)
    for_ref: Mapped[str] = mapped_column(String, nullable=False)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    hold_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    missing_quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class IncomingReceipt(PlatformBase):
    """Inventory's view of committed supply (Purchasing owns the commitment itself)."""

    __tablename__ = "incoming_receipts"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchasing_commitment_ref: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    expected_day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="EXPECTED")
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # bought for one order (pegged): other requests do not count on it; reserved for it when it arrives (011)
    for_kind: Mapped[str | None] = mapped_column(String)
    for_ref: Mapped[str | None] = mapped_column(String)


class EventVersion(EventVersionMixin, PlatformBase):
    __tablename__ = "event_versions"
    __table_args__ = {"schema": SCHEMA}


class AuditLog(AuditMixin, PlatformBase):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": SCHEMA}
