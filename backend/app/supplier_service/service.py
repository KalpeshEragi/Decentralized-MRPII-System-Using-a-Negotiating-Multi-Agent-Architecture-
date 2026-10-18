"""The Supplier Service's read-only interface. Other modules (Purchasing, the Negotiation Engine) use only these
functions and the plain records they return; they never import the tables or write supplier master data.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.supplier_service.models import Item, Supplier, SupplierItem


@dataclass(frozen=True)
class ItemRecord:
    id: uuid.UUID
    sku: str
    name: str
    unit: str


@dataclass(frozen=True)
class SupplierRecord:
    id: uuid.UUID
    name: str
    is_active: bool


@dataclass(frozen=True)
class SupplierItemRecord:
    """One supplier of an item, with its terms. Inactive suppliers are included; the caller decides what that means."""

    supplier_id: uuid.UUID
    supplier_name: str
    supplier_is_active: bool
    lead_time_days: int
    min_order_qty: Decimal
    available_qty: Decimal


def get_item(db: Session, item_id: uuid.UUID) -> ItemRecord | None:
    item = db.get(Item, item_id)
    return ItemRecord(item.id, item.sku, item.name, item.unit) if item else None


def get_supplier(db: Session, supplier_id: uuid.UUID) -> SupplierRecord | None:
    supplier = db.get(Supplier, supplier_id)
    return SupplierRecord(supplier.id, supplier.name, supplier.is_active) if supplier else None


def get_suppliers(db: Session, supplier_ids: list[uuid.UUID]) -> dict[uuid.UUID, SupplierRecord]:
    rows = db.scalars(select(Supplier).where(Supplier.id.in_(supplier_ids))) if supplier_ids else []
    return {s.id: SupplierRecord(s.id, s.name, s.is_active) for s in rows}


def supplier_items_for(db: Session, item_id: uuid.UUID) -> list[SupplierItemRecord]:
    rows = db.execute(
        select(SupplierItem, Supplier)
        .join(Supplier, Supplier.id == SupplierItem.supplier_id)
        .where(SupplierItem.item_id == item_id)
        .order_by(Supplier.name)
    )
    return [
        SupplierItemRecord(s.id, s.name, s.is_active, si.lead_time_days, si.min_order_qty, si.available_qty)
        for si, s in rows
    ]
