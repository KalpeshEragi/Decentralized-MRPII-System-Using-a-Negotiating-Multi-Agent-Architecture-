# Inventory Agent: High-Level Architecture (System Boundary)

**Status:** APPROVED by the developer (2026-10-17). Nothing new here is implemented.
**Scope:** the Inventory Agent only. Other agents appear as contact points.
**Related:** `../architecture/quantity_accounting.md` (the number rules: QA-1 to QA-4, RD-6),
`../architecture/negotiation.md`, `../architecture/pubsub_event_channel.md`, `../planning_agent/`, `../DECISIONS.md`.
Later notes: `2_inventory_agent_functions.md`, `3_inventory_agent_backend.md`, `4_inventory_agent_database.md`.

## 1. Purpose

Inventory is the single source of truth for **how much** of each item exists, is promised, is held and is coming in.
It answers "can I have this quantity by this date?", protects stock from being promised twice, guards safety stock,
and tells others when availability changes. It does not decide what to produce or buy, and it does not move goods.

## 2. Inside the Inventory boundary (Inventory owns this)

1. Quantities per item: `on_hand`, `reserved`, `held`, `incoming` (by date), for raw materials, sub-assemblies and
   finished goods (`quantity_accounting.md` §4).
2. Available-to-promise by date (QA-4) and the `atp_by_date` read function.
3. Holds on agreement and their expiry (NG-2).
4. Reservations: commit, release, change as a delta (QA-3).
5. Safety-stock levels and the safety-stock release decision (QA-2, RD-6, configurable limits).
6. The stock ledger and balance, with a reconcile check (QA-1).
7. Updating quantities from physical facts reported by Warehouse (receipt, issue, finished goods stored, shipment).
8. Finding uncovered promises for an item when supply changes (due-date walk, `quantity_accounting.md` §5.3).
9. Publishing stock facts: reservations, availability changes, safety-stock breaches.

## 3. Outside the boundary

| Item | Owner |
| --- | --- |
| Where goods physically are; storage space per zone; receiving capacity; physical moves | Warehouse (IN-1) |
| What to produce, when; procurement requests; refills after a safety-stock breach | Planning (HA-3, RD-6) |
| Supplier choice and supplier commitments | Purchasing |
| Worker hours | HR |
| Customer communication | Sales |

## 4. Contact points

| Contact point | Direction | Kind |
| --- | --- | --- |
| Stock requests (REQUEST → OFFER/COUNTER → hold → COMMIT/ABORT) | Any starter → Inventory (mostly Planning) | Private negotiation (A2A, NG-1). Inventory is **responder only** (IN-3) |
| `atp_by_date`, `stock_position` | Others → Inventory | Read functions |
| Subscribed events | Owners → Inventory | §6 |
| Published events | Inventory → subscribers | §6 |
| `SimulatedDayStarted` | Simulator clock → Inventory | Expire holds whose time has passed |
| AI model | Inventory ↔ shared model | Negotiation wording and rationale only (IN-4) |
| Storage | Inventory ↔ `inventory` schema | Inventory-owned data only |

## 5. How Inventory answers a stock request

All deterministic (IN-4):

1. The request enters Inventory's queue; order of handling = NG-3 (dependencies → deadline slack read from Planning's
   `get_order_plan` → aging → first come).
2. Lock the item's balance row. Compute `ATP(needed_by)` (QA-4).
3. `q ≤ ATP` → **OFFER** q by `needed_by`.
4. Otherwise **COUNTER_OFFER** with the facts: the quantity available by `needed_by` and/or the earliest date the full
   quantity is available (from incoming receipts). Never more than ATP.
5. **Safety-stock release** (only if the shortfall is small and urgent): allowed only when all hold —
   - the request's deadline slack ≤ `safety_stock_max_slack_days` (default 2),
   - the release ≤ `safety_stock_release_share` × safety stock (default 50 %), minus what is already released,
   - after the release every existing promise of this item stays covered (`S(t) − C(t) ≥ 0` for all later t),
   - only the **minimum** needed is released.
   Then it records `SAFETY_STOCK_USE` and publishes `SafetyStockBreached` (Planning plans a refill, RD-6).
6. Starter accepts → **hold** + `AGREEMENT_PROPOSED` (expiry 24 h). `COMMIT` → re-check → hold becomes reservation →
   `ReservationCommitted`. `ABORT` or expiry → hold released.

## 6. Events

| Subscribes to | Effect on Inventory's numbers |
| --- | --- |
| `ProcurementCommitted` | `incoming` + quantity on its date |
| `SupplierDeliveryDelayed`, `SupplierQuantityReduced` | `incoming` date / quantity changes → uncovered-promise check |
| `MaterialReceived` (Warehouse) | `on_hand` +, `incoming` − |
| `MaterialIssuedToProduction` (Warehouse) | `on_hand` −, `reserved` − |
| `FinishedGoodsStored` (Warehouse, **new**, IN-2) | Finished goods `on_hand` + |
| `ShipmentDispatched` (Warehouse) | Finished goods `on_hand` −, `reserved` − |
| `ProductionOrderReleased` (Planning) | Reservations of that order marked "to be issued" (no quantity change) |
| `PlanRevised`, `PlanCommitFailed` (Planning) | Release reservations / holds Planning no longer needs (through its negotiation) |
| `SimulatedDayStarted` | Expire holds |

| Publishes | When |
| --- | --- |
| `ReservationCommitted`, `ReservationReleased` | A reservation is made or released |
| `StockAvailabilityChanged` | ATP of an item changes in a way that uncovers a promise or frees stock |
| `SafetyStockBreached` | Safety stock is released or projected stock falls below it |

## 7. Rules (write these on the diagram)

1. One number, one owner: Inventory owns quantities; Warehouse owns space and physical moves.
2. Never promise more than ATP; never let `on_hand` go below 0.
3. Safety stock only through the fixed release rule and the configured limits.
4. Inventory never starts negotiations; it reports problems as events.
5. The LLM writes wording only; every number in a message comes from code.
6. Same state, same requests, same order → same answers.
7. No price or cost.

## 8. Decisions recorded

| ID | Decision |
| --- | --- |
| IN-1 | Inventory is the quantity truth per item (on-hand, reserved, held, incoming); Warehouse is the space and movement truth. |
| IN-2 | New event `FinishedGoodsStored` (publisher Warehouse; subscriber Inventory, also Planning and Sales) raises finished-goods on-hand, like `MaterialReceived` for materials. |
| IN-3 | Inventory is a responder only; it reports problems through events and never starts negotiations. |
| IN-4 | All Inventory decisions are deterministic, including the safety-stock release (fixed rule within configured limits, minimum needed). The LLM writes wording and rationale only. |
| Inherited | QA-1 to QA-4, RD-6, NG-1 to NG-4, HA-3. |

## 9. Open (for the next notes)

| ID | Question |
| --- | --- |
| IN-O1 | Done 2026-10-17: `FinishedGoodsStored` added to the catalogue; Inventory removed from `ProductionCompleted` subscribers. |
| IN-O2 | Confirmed 2026-10-17: one factory site, no multi-site transfers. |
| IN-O3 | Stock count corrections stay out of scope (QA-O3) unless a scenario needs them. |
| IN-O4 | Existing code: `agents/inventory/` starts procurement and reserves after human approval — retire in the Phase 2 review; keep `inventory_service.reserve/release` and the balance table as the base. |

## 10. Diagram checklist

- One box "Inventory Agent" with the 9 inside items (§2).
- Starters (mostly Planning) → Inventory: dashed negotiation arrows; Inventory never starts one.
- Read-function arrows: `atp_by_date`, `stock_position`.
- Warehouse → Inventory: `MaterialReceived`, `MaterialIssuedToProduction`, `FinishedGoodsStored`, `ShipmentDispatched`.
- Purchasing → Inventory: `ProcurementCommitted`, delays, quantity reductions.
- Inventory → Planning: `ReservationCommitted/Released`, `StockAvailabilityChanged`, `SafetyStockBreached`.
- Simulator clock → Inventory: `SimulatedDayStarted` (hold expiry).
- AI model: "wording only". `inventory` schema with ledger + balance.
- Rules note (§7).
