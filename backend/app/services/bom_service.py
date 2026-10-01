"""BOM and item reads. Single-level BOM (P1-02): the active version of each parent item."""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Bom, BomItem
from app.models.core import Item as ItemRow
from app.schemas.domain import BOMLine, Item


def get_bom(db: Session, parent_item_id: uuid.UUID) -> list[BOMLine]:
    """Lines of the highest active BOM version for the parent item; empty if it has none."""
    bom_id = db.scalar(
        select(Bom.id).where(Bom.parent_item_id == parent_item_id, Bom.is_active.is_(True)).order_by(Bom.version.desc())
    )
    if bom_id is None:
        return []
    rows = db.scalars(select(BomItem).where(BomItem.bom_id == bom_id).order_by(BomItem.id))
    return [
        BOMLine(
            parent_item_id=str(parent_item_id),
            component_item_id=str(row.component_item_id),
            quantity_per=row.quantity_required,
        )
        for row in rows
    ]


def get_boms(db: Session, parent_item_ids: Iterable[uuid.UUID]) -> list[BOMLine]:
    return [line for parent in parent_item_ids for line in get_bom(db, parent)]


def list_items(db: Session) -> list[Item]:
    """All items (master data), finished products first."""
    rows = db.scalars(select(ItemRow).order_by(ItemRow.item_type.desc(), ItemRow.name))
    return [Item(id=str(r.id), sku=r.sku, name=r.name, item_type=r.item_type, unit=r.unit) for r in rows]
