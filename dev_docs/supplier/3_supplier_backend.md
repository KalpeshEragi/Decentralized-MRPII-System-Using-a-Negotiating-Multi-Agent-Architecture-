# Supplier: Backend

**Status:** implemented (migration `004`).
**Code:** `backend/app/supplier_service/` (`models.py`, `service.py`, `seed.py`). No routes of its own; the chat routes
belong to Purchasing (`2_supplier_interface.md`).

## 1. Modules

| File | Job |
| --- | --- |
| `models.py` | Tables `items`, `suppliers`, `supplier_items` on its own declarative base (schema `supplier_service`). Other modules never import these classes. |
| `service.py` | The read-only interface. Returns frozen records, never ORM objects. |
| `seed.py` | Fixed fixture (IDs derived from SKU / name with `uuid5`), `reset` (truncate own tables), `seed`. |

## 2. Functions (`service.py`)

| Function | Returns | Called by |
| --- | --- | --- |
| `get_item(db, item_id)` | `ItemRecord` (id, sku, name, unit) or `None` | `purchasing_agent/service.py` (unknown item → 422), `contracts.py`, `views.py` |
| `get_supplier(db, supplier_id)` | `SupplierRecord` (id, name, is_active) or `None` | `contracts.py`, `views.py`, `negotiation_engine/service.py` (participant check) |
| `get_suppliers(db, ids)` | `{id: SupplierRecord}` | `contracts.py`, `views.py` |
| `supplier_items_for(db, item_id)` | `[SupplierItemRecord]` (supplier id/name/active, lead time, MOQ, available qty), by supplier name; inactive included | `availability.py` (effective availability), `contracts.py` (supplier supplies item), `negotiation.py` (names) |

There is no write function. Purchasing decides what an inactive supplier means (excluded, `inactive_supplier`).

## 3. How Purchasing uses supplier data

| Use | Rule | Code |
| --- | --- | --- |
| Eligibility | Active; arrival (selection date + lead time) ≤ required date; effective availability ≥ MOQ | `selection.py` `_unusable_reason` |
| Effective availability | `available_qty` − holds of other requests' Legs, under an advisory lock per supplier-item | `availability.py` |
| Order quantity | max(shortage, MOQ); MOQ surplus counts in Total Purchasing Cost | `selection.py` |
| Price | From Purchasing Contracts, not from the Supplier Service | `contracts.py`, `selection.price_state` |
| Negotiation | One Engine session per Leg; supplier is participant `SUPPLIER` (its UUID), checked to exist | `negotiation_engine/service.py` |

## 4. Seed and reset

`python -m app.purchasing_agent.seed` (from `backend/`, uses `DATABASE_URL`) resets all three new schemas and calls
`supplier_service.seed.reset` + `seed`. DB tests reset the same way (`backend/tests/purchasing_agent/db/conftest.py`).

## 5. Tests

No separate supplier test folder. Supplier data is exercised through the Purchasing tests
(`backend/tests/purchasing_agent/`, `db/` needs `TEST_DATABASE_URL`).
