"""Inventory availability and reserve/release. Availability is calculated by the C1 rule, never by an LLM.

Positions are aggregated across warehouses (one warehouse in the X1 fixture, P0-10). A finished product's position is
read the same way as a component's; an item with no balance row has a zero position.
Reservation status values (ACTIVE, RELEASED) are working values; C3 does not define them yet.
"""

import uuid
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.inventory import InventoryBalance, InventoryReservation
from app.schemas.domain import InventoryPosition

ACTIVE = "ACTIVE"
RELEASED = "RELEASED"


def get_positions(db: Session, item_ids: Iterable[uuid.UUID | str]) -> dict[str, InventoryPosition]:
    """Aggregated InventoryPosition per item id (str). Items without stock rows are omitted."""
    ids = [uuid.UUID(str(item_id)) for item_id in item_ids]
    rows = db.execute(
        select(
            InventoryBalance.item_id,
            func.sum(InventoryBalance.on_hand),
            func.sum(InventoryBalance.reserved),
            func.sum(InventoryBalance.safety_stock),
        )
        .where(InventoryBalance.item_id.in_(ids))
        .group_by(InventoryBalance.item_id)
    )
    return {
        str(item_id): InventoryPosition(
            item_id=str(item_id), on_hand=on_hand, reserved=reserved or Decimal(0), safety_stock=safety or Decimal(0)
        )
        for item_id, on_hand, reserved, safety in rows
    }


def get_position(db: Session, item_id: uuid.UUID | str) -> InventoryPosition:
    return get_positions(db, [item_id]).get(str(item_id)) or InventoryPosition(
        item_id=str(item_id), on_hand=0, reserved=0, safety_stock=0
    )


def reserve(db: Session, item_id: uuid.UUID, order_id: uuid.UUID, quantity: Decimal) -> uuid.UUID:
    """Reserve stock for an order. Refused if it would exceed available_quantity (safety stock stays untouched)."""
    if quantity <= 0:
        raise AppError(ErrorCode.VALIDATION_ERROR, "reservation quantity must be greater than 0")
    balance = db.scalars(
        select(InventoryBalance).where(InventoryBalance.item_id == item_id).order_by(InventoryBalance.id).with_for_update()
    ).first()
    if balance is None or quantity > get_position(db, item_id).available_quantity:
        raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, "reservation exceeds available quantity")
    balance.reserved = (balance.reserved or Decimal(0)) + quantity
    reservation = InventoryReservation(
        item_id=item_id, warehouse_id=balance.warehouse_id, order_id=order_id, quantity=quantity, status=ACTIVE
    )
    db.add(reservation)
    db.commit()
    return reservation.id


def release(db: Session, reservation_id: uuid.UUID) -> None:
    reservation = db.get(InventoryReservation, reservation_id)
    if reservation is None:
        raise AppError(ErrorCode.NOT_FOUND, "reservation not found")
    if reservation.status != ACTIVE:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"reservation is {reservation.status}")
    balance = db.scalars(
        select(InventoryBalance)
        .where(InventoryBalance.item_id == reservation.item_id, InventoryBalance.warehouse_id == reservation.warehouse_id)
        .with_for_update()
    ).one()
    balance.reserved = balance.reserved - reservation.quantity
    reservation.status = RELEASED
    db.commit()
