"""`warehouse` schema of the Warehouse Agent (warehouse_agent/4_warehouse_agent_database.md). Warehouse is the truth for
space and physical movement, never for item quantities (IN-1). Space uses a movement profile (WD-1).

Simplification against note 4: the daily receiving and shipping capacities are one row each in `daily_capacities`
(the configured numbers, WH-3); per-day usage is in `receiving_days` / `shipping_days`.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.owner_tables import AuditMixin, LedgerMixin
from app.core.platform_base import PlatformBase
from app.events.models import EventVersionMixin

SCHEMA = "warehouse"


class Zone(PlatformBase):
    __tablename__ = "zones"
    __table_args__ = {"schema": SCHEMA}

    zone: Mapped[str] = mapped_column(String, primary_key=True)  # MATERIALS or FINISHED_GOODS (WH-2)
    capacity_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    occupied_now: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DailyCapacity(PlatformBase):
    __tablename__ = "daily_capacities"
    __table_args__ = {"schema": SCHEMA}

    resource: Mapped[str] = mapped_column(String, primary_key=True)  # RECEIVING or SHIPPING
    units: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class ReceivingDay(PlatformBase):
    __tablename__ = "receiving_days"
    __table_args__ = {"schema": SCHEMA}

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    committed_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    held_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    used_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)


class ShippingDay(PlatformBase):
    __tablename__ = "shipping_days"
    __table_args__ = {"schema": SCHEMA}

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    used_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)


class Hold(PlatformBase):
    __tablename__ = "holds"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # DELIVERY or FINISHED_GOODS
    zone: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    space_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    receiving_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    arrival_day: Mapped[date] = mapped_column(Date, nullable=False)
    until_day: Mapped[date | None] = mapped_column(Date)
    for_ref: Mapped[str] = mapped_column(String, nullable=False)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    negotiation_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    expires_day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")


class SpaceCommitment(PlatformBase):
    __tablename__ = "space_commitments"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    zone: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    space_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    arrival_day: Mapped[date] = mapped_column(Date, nullable=False)
    until_day: Mapped[date | None] = mapped_column(Date)
    for_ref: Mapped[str] = mapped_column(String, nullable=False)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    negotiation_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SpaceMovement(PlatformBase):
    __tablename__ = "space_movements"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commitment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    zone: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # ARRIVAL or DEPARTURE
    space_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    planned_day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PLANNED")


class SpaceLedger(LedgerMixin, PlatformBase):
    __tablename__ = "space_ledger"
    __table_args__ = (UniqueConstraint("source_id", "line_no"), {"schema": SCHEMA})


class EventVersion(EventVersionMixin, PlatformBase):
    __tablename__ = "event_versions"
    __table_args__ = {"schema": SCHEMA}


class AuditLog(AuditMixin, PlatformBase):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": SCHEMA}
