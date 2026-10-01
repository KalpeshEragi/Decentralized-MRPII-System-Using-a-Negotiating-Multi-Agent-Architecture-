"""inventory schema: warehouses, inventory_balance, inventory_reservations."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = {"schema": "inventory"}

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str] = mapped_column(String, nullable=False)


class InventoryBalance(Base):
    __tablename__ = "inventory_balance"
    __table_args__ = {"schema": "inventory"}

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory.warehouses.id"))
    on_hand: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    reserved: Mapped[Decimal] = mapped_column(Numeric, default=0, server_default="0")
    safety_stock: Mapped[Decimal] = mapped_column(Numeric, default=0, server_default="0")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryReservation(Base):
    __tablename__ = "inventory_reservations"
    __table_args__ = {"schema": "inventory"}

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory.warehouses.id"))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.customer_orders.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    status: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime | None] = created_at()
