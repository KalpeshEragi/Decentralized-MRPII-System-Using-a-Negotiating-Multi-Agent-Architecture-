"""planning schema: mps_plans, mrp_requirements. Day-bucket dates are DATE columns (P0-16)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class MpsPlan(Base):
    __tablename__ = "mps_plans"
    __table_args__ = {"schema": "planning"}

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.customer_orders.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"))
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    planned_start: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # C1 PlanStatus
    created_at: Mapped[datetime | None] = created_at()


class MrpRequirement(Base):
    __tablename__ = "mrp_requirements"
    __table_args__ = {"schema": "planning"}

    id: Mapped[uuid.UUID] = uuid_pk()
    mps_plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("planning.mps_plans.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"))
    gross_requirement: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    available_inventory: Mapped[Decimal] = mapped_column(Numeric, nullable=False)  # C1 available_quantity
    scheduled_receipts: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    projected_available_quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    net_requirement: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    required_by: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # C1 RequirementStatus
