"""Supplier lookup and feasibility. Suppliers are data/service, not agents; no price/cost anywhere."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mrpii.suppliers import arrival_date, covers_alone, is_usable
from app.models.purchasing import Supplier, SupplierItem
from app.schemas.domain import Shortage, SupplierOption


def supplier_options(db: Session, item_id: uuid.UUID | str) -> list[SupplierOption]:
    rows = db.execute(
        select(Supplier.name, SupplierItem)
        .join(SupplierItem, SupplierItem.supplier_id == Supplier.id)
        .where(SupplierItem.item_id == uuid.UUID(str(item_id)), Supplier.is_active.is_(True))
        .order_by(Supplier.name)
    )
    return [
        SupplierOption(
            item_id=str(item.item_id),
            supplier=name,
            lead_time_days=item.lead_time_days,
            min_order_qty=item.min_order_qty,
            available_qty=item.available_qty,
        )
        for name, item in rows
    ]


def feasibility(db: Session, shortage: Shortage, planning_date: date) -> list[dict]:
    """Deterministic feasibility inputs per supplier for a shortage (fixture rule, section 5.1). Not a selection."""
    return [
        {
            "supplier": option.supplier,
            "lead_time_days": option.lead_time_days,
            "min_order_qty": option.min_order_qty,
            "available_qty": option.available_qty,
            "arrival_date": arrival_date(option, planning_date),
            "usable": is_usable(option, planning_date, shortage.required_by),
            "covers_alone": covers_alone(option, planning_date, shortage.required_by, shortage.shortage_quantity),
        }
        for option in supplier_options(db, shortage.item_id)
    ]
