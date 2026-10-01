"""core schema: items, bom, bom_items."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, func
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
