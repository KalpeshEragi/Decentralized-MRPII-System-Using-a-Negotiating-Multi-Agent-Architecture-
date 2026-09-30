"""purchasing schema: suppliers, supplier_items, purchase_requisitions (no purchase orders in the 25%)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = {"schema": "purchasing"}

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    contact_info: Mapped[dict | None] = mapped_column(JSONB)
    rating_data: Mapped[dict | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class SupplierItem(Base):
    __tablename__ = "supplier_items"
    __table_args__ = {"schema": "purchasing"}

    id: Mapped[uuid.UUID] = uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("purchasing.suppliers.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"))
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    min_order_qty: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    available_qty: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class PurchaseRequisition(Base):
    __tablename__ = "purchase_requisitions"
    __table_args__ = {"schema": "purchasing"}

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"))
    quantity_required: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    required_by: Mapped[date] = mapped_column(Date, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str | None] = mapped_column(String)
    created_by_agent: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.agents.id"))
    created_at: Mapped[datetime | None] = created_at()
