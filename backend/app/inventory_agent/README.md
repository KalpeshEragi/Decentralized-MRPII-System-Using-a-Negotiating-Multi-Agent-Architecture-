# backend/app/inventory_agent

The Inventory Agent (`dev_docs/inventory_agent/`): the quantity truth per item (IN-1). Responder only (IN-3); every
decision is deterministic code (IN-4); wording is a template until the AI steps are switched on (IMP-2).

| File | Purpose |
| --- | --- |
| `models.py` | `inventory` schema: `stock_balances`, `stock_ledger` (QA-1), `holds`, `reservations` (for a customer demand or a production order, ID-2), `incoming_receipts`, `event_versions`, `audit_log`. |
| `manager.py` | `answer` (IF-1: offer / full quantity later / most by the date / reject, with the RD-6 safety-stock release), holds on ACCEPT, reservations on COMMIT (`ReservationCommitted`), aborts; events: day start (hold expiry → REJECT HOLD_EXPIRED), material issued, finished goods stored (on hand + a
reservation for what the goods were made for: the customer demand or the parent production order), shipment, plan revised (releases, `ReservationReleased`); `setup`; `register`. |
| `reads.py` | The read module other agents may import (IB-2): `stock_position`, `atp_by_date`, `reservations_for`. |
| `api.py` | `POST /inventory/setup` (simulator, `X-Door-Key`), `GET /inventory/items/{id}/position`, `/atp`, `/orders/{ref}/reservations`. |

Every quantity change is a ledger row + a balance update in the same transaction under the item's row lock. A repeated
event cannot change numbers twice (`source_id` + `line_no` unique; stale versions ignored through `event_versions`).

Supply (PI-4): `ProcurementCommitted` adds one expected receipt per supplier Leg; bought for an order it is pegged to it
(other requests do not count on it); `MaterialReceived` raises on hand and reserves a pegged delivery for its order.
Not yet: supplier delays and AT_RISK marking (IF-2, S2); a reconcile door comes with snapshots (step 7).

**Tests:** `backend/tests/platform/test_inventory_agent.py` (the 5000 → 3000 example with an exact ledger; no double
booking under competing requests).
