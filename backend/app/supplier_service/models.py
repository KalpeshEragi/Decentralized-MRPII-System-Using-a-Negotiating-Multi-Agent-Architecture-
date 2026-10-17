"""The Supplier Service tables (schema `supplier_service`, docs/database_schema.md §5.1). They match migration 004.

Own declarative base, like the Sales Agent: the legacy demo reset cannot touch these tables. Other modules read this
data only through `service.py`, never these classes.
"""

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, MetaData, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "supplier_service"


class SupplierServiceBase(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Item(SupplierServiceBase):
    """A procurable item. In standalone mode an item is valid for Purchasing only if it is here."""

    __tablename__ = "items"

    id: Mapped[uuid.UUID] = uuid_pk()
    sku: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String)


class Supplier(SupplierServiceBase):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, unique=True)
    contact_info: Mapped[dict | None] = mapped_column(JSONB)
    rating_data: Mapped[dict | None] = mapped_column(JSONB)  # not used in ranking
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SupplierItem(SupplierServiceBase):
    __tablename__ = "supplier_items"
    __table_args__ = (UniqueConstraint("supplier_id", "item_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.suppliers.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.items.id"))
    lead_time_days: Mapped[int] = mapped_column(Integer)
    min_order_qty: Mapped[Decimal] = mapped_column(Numeric)
    available_qty: Mapped[Decimal] = mapped_column(Numeric)
