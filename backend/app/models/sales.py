"""sales schema: customers, customer_orders, customer_order_items."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = {"schema": "sales"}

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str] = mapped_column(String, nullable=False)
    contact_info: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime | None] = created_at()


class CustomerOrder(Base):
    __tablename__ = "customer_orders"
    __table_args__ = {"schema": "sales"}

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.customers.id"))
    order_number: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str | None] = mapped_column(String)  # C1 OrderStatus
    created_at: Mapped[datetime | None] = created_at()


class CustomerOrderItem(Base):
    __tablename__ = "customer_order_items"
    __table_args__ = {"schema": "sales"}

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.customer_orders.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core.items.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
