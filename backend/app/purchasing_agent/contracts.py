"""Purchasing Contracts: register and list (dev_docs/purchasing_agent/purchasing_agent_architecture.md §6.2).

Write rules live here, not in the database: the seed must be able to store overlapping contracts (bad data) so the
selection-time `contract_overlap` exclusion stays testable. The price lookup on the selection date is
`selection.price_state`.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.purchasing_agent.models import PurchasingContract
from app.purchasing_agent.selection import validity_overlaps
from app.supplier_service import service as supplier_service

CURRENCY = "INR"


@dataclass(frozen=True)
class NewContract:
    supplier_id: uuid.UUID
    item_id: uuid.UUID
    unit_price: Decimal  # > 0, at most two decimals (checked by the API)
    valid_from: date
    valid_until: date | None  # None = open-ended
    is_active: bool


def register(db: Session, new: NewContract) -> uuid.UUID:
    """Store a contract. Refused: a validity that ends before it starts, a supplier-item pair the Supplier Service
    does not know, or an active contract overlapping another active contract for the same pair."""
    if new.valid_until is not None and new.valid_until < new.valid_from:
        raise AppError(ErrorCode.VALIDATION_ERROR, "valid_until is before valid_from",
                       [{"field": "valid_until", "issue": "must not be before valid_from"}])
    _check_supplier_item(db, new.supplier_id, new.item_id)

    if new.is_active:
        # One writer per supplier-item at a time, so two overlapping contracts can't both pass the check.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                   {"key": f"purchasing_contract:{new.supplier_id}:{new.item_id}"})
        clash = next((c for c in _contracts(db, new.supplier_id, new.item_id)
                      if c.is_active and validity_overlaps(c.valid_from, c.valid_until, new.valid_from, new.valid_until)),
                     None)
        if clash is not None:
            db.rollback()
            raise AppError(ErrorCode.CONFLICT, "an active contract for this supplier and item already covers these dates",
                           [{"field": "valid_from", "issue": f"overlaps active contract {clash.id}"}])

    contract = PurchasingContract(
        id=uuid.uuid4(), supplier_id=new.supplier_id, item_id=new.item_id, unit_price=new.unit_price,
        valid_from=new.valid_from, valid_until=new.valid_until, is_active=new.is_active,
    )
    db.add(contract)
    db.commit()
    return contract.id


def _check_supplier_item(db: Session, supplier_id: uuid.UUID, item_id: uuid.UUID) -> None:
    if supplier_service.get_supplier(db, supplier_id) is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "the supplier is not in the Supplier Service",
                       [{"field": "supplier_id", "issue": "unknown supplier"}])
    if supplier_service.get_item(db, item_id) is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "the item is not in the Supplier Service catalogue",
                       [{"field": "item_id", "issue": "unknown item"}])
    # A contract for an item the supplier does not sell could never be used.
    if all(s.supplier_id != supplier_id for s in supplier_service.supplier_items_for(db, item_id)):
        raise AppError(ErrorCode.VALIDATION_ERROR, "the supplier does not supply this item in the Supplier Service",
                       [{"field": "item_id", "issue": "not supplied by this supplier"}])


def _contracts(db: Session, supplier_id: uuid.UUID, item_id: uuid.UUID) -> list[PurchasingContract]:
    return list(db.scalars(select(PurchasingContract).where(
        PurchasingContract.supplier_id == supplier_id, PurchasingContract.item_id == item_id)))


def list_contracts(db: Session, supplier_id: uuid.UUID | None = None,
                   item_id: uuid.UUID | None = None) -> list[dict]:
    query = select(PurchasingContract)
    if supplier_id is not None:
        query = query.where(PurchasingContract.supplier_id == supplier_id)
    if item_id is not None:
        query = query.where(PurchasingContract.item_id == item_id)
    rows = list(db.scalars(query))
    suppliers = supplier_service.get_suppliers(db, list({c.supplier_id for c in rows}))
    items = {i: supplier_service.get_item(db, i) for i in {c.item_id for c in rows}}
    views = [contract_view(c, suppliers.get(c.supplier_id), items.get(c.item_id)) for c in rows]
    # Grouped by item and supplier, then oldest validity first: a pair's price history reads top to bottom.
    return sorted(views, key=lambda v: (v["item"]["sku"] or "", v["supplier"]["name"] or "", v["valid_from"], v["id"]))


def get_contract(db: Session, contract_id: uuid.UUID) -> dict:
    contract = db.get(PurchasingContract, contract_id)
    if contract is None:
        raise AppError(ErrorCode.NOT_FOUND, "purchasing contract not found")
    return contract_view(contract, supplier_service.get_supplier(db, contract.supplier_id),
                         supplier_service.get_item(db, contract.item_id))


def contract_view(contract: PurchasingContract, supplier, item) -> dict:
    return {
        "id": str(contract.id),
        "supplier": {"id": str(contract.supplier_id), "name": supplier.name if supplier else None},
        "item": {"id": str(contract.item_id), "sku": item.sku if item else None, "name": item.name if item else None},
        "unit_price": str(contract.unit_price),
        "currency": CURRENCY,
        "valid_from": contract.valid_from.isoformat(),
        "valid_until": contract.valid_until.isoformat() if contract.valid_until else None,
        "is_active": contract.is_active,
        "created_at": contract.created_at.isoformat(),
    }
