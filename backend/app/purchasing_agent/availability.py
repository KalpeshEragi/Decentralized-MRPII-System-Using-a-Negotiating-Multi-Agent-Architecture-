"""Effective availability (dev_docs/purchasing_agent/purchasing_agent_architecture.md §6.3), so Purchasing never
double-books a supplier.

- Effective availability = the Supplier Service's `available_qty` − Purchasing's holds on that supplier-item.
- A hold is a PENDING Leg's `allocated_quantity`, or an AGREED or COMMITTED Leg's `agreed_quantity`. FAILED and ABORTED
  Legs hold nothing, so failing or aborting a Leg releases its hold.
- Only other requests' Legs count: a request's own Legs are what reallocation is re-deciding, not competing with it.
- Reads run under a transaction-scoped advisory lock per supplier-item (released on commit or rollback), so selections
  and reallocations for the same supplier-item run one at a time and the second one sees the first one's holds.
  Every call locks all of the item's supplier-items in key order (re-locking in the same transaction is a no-op), so
  every transaction takes the same locks in the same order and two of them can't deadlock.
Supplier master data is only read, never written.
"""

import hashlib
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.purchasing_agent.models import LegStatus, ProcurementRequest, PurchaseRequisition
from app.supplier_service import service as supplier_service
from app.supplier_service.service import SupplierItemRecord



@dataclass(frozen=True)
class Availability:
    supplier: SupplierItemRecord  # its available_qty is the Supplier Service's quantity
    held: Decimal  # by other requests' Legs

    @property
    def available(self) -> Decimal:
        return self.supplier.available_qty

    @property
    def effective(self) -> Decimal:
        return max(self.available - self.held, Decimal(0))

    def capped(self, cap: Decimal | None) -> Decimal:
        """Effective availability, limited by a supplier's counter-offered cap when it has one."""
        return self.effective if cap is None else min(self.effective, cap)


def _lock_key(supplier_id: uuid.UUID, item_id: uuid.UUID) -> int:
    """A stable signed 64-bit key for `pg_advisory_xact_lock(bigint)`."""
    digest = hashlib.blake2b(f"purchasing_hold:{supplier_id}:{item_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def effective_availability(db: Session, item_id: uuid.UUID,
                           excluding_request_id: uuid.UUID | None = None) -> dict[uuid.UUID, Availability]:
    """Every supplier of the item (by supplier ID, in supplier-name order), with its holds. Locks each supplier-item
    until the transaction ends, then reads the holds. `available_qty` is read before the lock: only Purchasing's
    holds are serialized here (the Supplier Service quantity is master data Purchasing never writes). The caller
    writes its own Legs in the same transaction, so the next request waiting on the lock sees them."""
    suppliers = supplier_service.supplier_items_for(db, item_id)
    for key in sorted({_lock_key(s.supplier_id, item_id) for s in suppliers}):
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    leg = PurchaseRequisition
    held_quantity = case((leg.status == LegStatus.PENDING, leg.allocated_quantity),
                         else_=func.coalesce(leg.agreed_quantity, leg.allocated_quantity))
    query = (select(leg.supplier_id, func.sum(held_quantity))
             .join(ProcurementRequest, ProcurementRequest.id == leg.procurement_request_id)
             .where(ProcurementRequest.item_id == item_id, leg.status.in_(LegStatus.HOLDING))
             .group_by(leg.supplier_id))
    if excluding_request_id is not None:
        query = query.where(leg.procurement_request_id != excluding_request_id)
    held = dict(db.execute(query).all())
    return {s.supplier_id: Availability(s, Decimal(held.get(s.supplier_id) or 0)) for s in suppliers}
