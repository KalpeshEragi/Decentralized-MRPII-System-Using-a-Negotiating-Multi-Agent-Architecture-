"""core schema (shared reference data): items, routings, bom, bom_items."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk
from app.schemas.domain import ItemType


class Item(Base):
    __tablename__ = "items"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = uuid_pk()
    sku: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    item_type: Mapped[ItemType] = mapped_column(Enum(ItemType, name="item_type", schema="core"), nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime | None] = created_at()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # PD-2: whether the item is made in-house or bought, and the storage space one piece needs (Warehouse, WH-2).
    sourcing: Mapped[str] = mapped_column(String, nullable=False, default="BUY", server_default="BUY")
    space_per_unit: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0, server_default="0")


class Routing(Base):
    """One production step of a made item (PD-2, RD-2): which work center, which skill and crew, setup and run time."""

    __tablename__ = "routings"
    __table_args__ = (UniqueConstraint("item_id", "step_no"), {"schema": "core"})

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"), nullable=False)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    work_center_code: Mapped[str] = mapped_column(String, nullable=False)
    skill: Mapped[str] = mapped_column(String, nullable=False)
    crew_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    setup_hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    run_hours_per_unit: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class Bom(Base):
    __tablename__ = "bom"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = uuid_pk()
    parent_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime | None] = created_at()


class BomItem(Base):
    __tablename__ = "bom_items"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = uuid_pk()
    bom_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.bom.id"))
    component_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"))
    quantity_required: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
