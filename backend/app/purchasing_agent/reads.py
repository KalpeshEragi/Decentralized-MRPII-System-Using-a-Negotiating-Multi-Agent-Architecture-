"""Purchasing's read module for the other agents (IB-2). Read-only; plain data. Planning uses it to plan bought items
(PI-6): which supplier item a factory item is (by SKU) and the earliest a supply could arrive. The estimate is not a
promise: the Procurement Request and its supplier negotiation decide."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Item
from app.supplier_service import service as supplier_service
from app.supplier_service.models import Item as SupplierItem


def supplier_item_id(db: Session, item_id: str) -> uuid.UUID | None:
    """The Supplier Service item for a factory item (`core.items`), matched by SKU."""
    try:
        item = db.get(Item, uuid.UUID(str(item_id)))
    except ValueError:
        return None
    if item is None:
        return None
    return db.scalar(select(SupplierItem.id).where(SupplierItem.sku == item.sku))


def supply_lead_time_days(db: Session, item_id: str, quantity: Decimal) -> int | None:
    """Days until `quantity` could arrive: the slowest lead time among the fastest active suppliers that together have
    enough available. None when no supplier (or not enough of them) can deliver it."""
    found = supplier_item_id(db, item_id)
    if found is None:
        return None
    offers = sorted((s for s in supplier_service.supplier_items_for(db, found)
                     if s.supplier_is_active and s.available_qty > 0), key=lambda s: s.lead_time_days)
    covered = Decimal(0)
    for offer in offers:
        covered += offer.available_qty
        if covered >= quantity:
            return offer.lead_time_days
    return None


def next_committed_delivery(db: Session, sku: str, from_day) -> dict | None:
    """The earliest committed supplier delivery of an item (by SKU) still to come: what a "supplier delay" trigger
    acts on when the scenario cannot know the delivery's id in advance."""
    from app.purchasing_agent.models import LegStatus, ProcurementRequest, PurchaseRequisition

    leg = db.scalar(select(PurchaseRequisition).join(
        ProcurementRequest, ProcurementRequest.id == PurchaseRequisition.procurement_request_id).join(
        SupplierItem, SupplierItem.id == ProcurementRequest.item_id).where(
        SupplierItem.sku == sku, PurchaseRequisition.status == LegStatus.COMMITTED,
        PurchaseRequisition.agreed_delivery_date >= from_day).order_by(PurchaseRequisition.agreed_delivery_date))
    return {"leg_id": str(leg.id), "delivery_date": leg.agreed_delivery_date.isoformat()} if leg else None
