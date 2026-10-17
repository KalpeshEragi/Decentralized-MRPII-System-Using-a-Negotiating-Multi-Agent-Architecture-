# Inventory Agent: Backend Design

**Status:** APPROVED by the developer (2026-10-17). Nothing new here is implemented.
**Stack:** FastAPI backend, PostgreSQL on Neon.
**Related:** `1_inventory_agent_high_level_architecture.md`, `2_inventory_agent_functions.md`,
`../planning_agent/3_planning_agent_backend.md` (same pattern), `../architecture/negotiation.md` §10.

## A. Layers

| # | Layer | Job |
| --- | --- | --- |
| 1 | API doors | A2A endpoint for stock negotiations; read-only view doors for team and demo |
| 2 | Inventory manager | Work queue; one worker per item; runs every step of a work item |
| 3 | Rules | Answer rule (IF-1), safety-stock rule (RD-6), AT_RISK rule (IF-2), message checks |
| 4 | Calculation | Pure functions: available now, ATP by date, earliest full date, uncovered walk |
| 5 | AI wording | `ai_word_message` only (IN-4) |
| 6 | Data access | The only code that reads and writes the `inventory` schema |
| 7 | Read module | `reads.py`: the read functions other agents call (IB-2) |
| 8 | Connectors | Negotiation replies (outbox → A2A), AI model, event publisher (outbox) |
| Side | Audit, settings, errors | |

**Folder (IB-1):** `backend/app/inventory_agent/` with the Sales layout (`manager.py`, `rules.py`, `calc.py`,
`agent.py`, `prompts.py`, `data_access.py`, `reads.py`, `connectors.py`, `api.py`, `models.py`, `views.py`). The
working parts of `services/inventory_service.py` (position, reserve/release with a row lock) move into
`data_access.py` and are extended with holds, the ledger and incoming receipts. The old service and
`agents/inventory/` are retired after the Phase 2 review.

## B. Read functions across agents (IB-2, applies to all six agents)

- Each agent has one read-only module (`<agent>/reads.py`). Others import **only** that module and call it inside the
  same backend program (HA-1).
- A read function opens its own read-only database session and returns plain data (no ORM objects).
- A test checks the import rule: no agent imports anything from another agent except its `reads.py`.
- Writes never go through read modules: they go through negotiation (A2A) or events.
- The same reads are also offered as HTTP GET doors for the demo and the team.

Inventory's read module: `atp_by_date(item, from, to)`, `stock_position(item)`, `reservations_for_order(order)`.

## C. API doors

| # | Door | Who | Returns |
| --- | --- | --- | --- |
| 1 | `/a2a/inventory` | Starters (A2A, NG-1) | Store and acknowledge |
| 2 | `GET /inventory/items/{item_id}/atp?from=&to=` | Team, demo | ATP per day |
| 3 | `GET /inventory/items/{item_id}/position` | Team, demo | on_hand, reserved, held, incoming, safety stock |
| 4 | `GET /inventory/orders/{order_ref}/reservations` | Team, demo | Holds and reservations with status |
| 5 | `GET /inventory/items/{item_id}/ledger` | Team, demo | Ledger rows (the "why" of every number) |
| 6 | `POST /inventory/maintenance/reconcile` | Us | Balances vs ledger sums; reports differences, changes nothing |

There is no write door: changes come only through negotiation messages and subscribed events. Starting stock is set
by the simulator configuration (IB-O1).

## D. Functions (plumbing)

**Manager:** `handle_negotiation_message` (from the inbox dispatcher); `handle_event` (quick: records an ITEM work
item); `process_work` (claim the next work item of an item no other worker holds); `answer_request`; `commit_hold`;
`abort_hold`; `expire_holds`; `apply_physical_fact`; `apply_supply_change`; `reconcile`.

**Rules:** `answer_rule` (IF-1); `safety_release_allowed` (RD-6); `mark_uncovered` (IF-2); `check_wording`.

**Connectors:** `negotiation_client` (replies through the outbox); `ai_connector` (timeout, one retry, else template);
`publish` (event outbox).

## E. Flows

1. **Stock request:** A2A door stores and acknowledges → inbox dispatcher → ITEM work item → lock balance row →
   IF-1 → reply (OFFER / COUNTER_OFFER / REJECT) through the outbox.
2. **Accept → hold:** `place_hold` (ledger HOLD +, balance `held` +) → `AGREEMENT_PROPOSED` with hold id and expiry.
3. **Commit / abort:** `COMMIT` → re-check ATP → hold → reservation → `ReservationCommitted`. Re-check fails → `REJECT`
   (`STALE` / `UNAVAILABLE`). `ABORT` → hold released.
4. **Day starts:** `SimulatedDayStarted` → `expire_holds` → availability event if stock was freed.
5. **Physical facts:** `MaterialReceived`, `MaterialIssuedToProduction`, `FinishedGoodsStored`, `ShipmentDispatched`
   → ledger + balance → `StockAvailabilityChanged` when ATP changes.
6. **Supply change:** `ProcurementCommitted`, `SupplierDeliveryDelayed`, `SupplierQuantityReduced` → `incoming`
   updated → due-date walk → AT_RISK / ACTIVE → one `StockAvailabilityChanged` listing them.
7. **Order change:** delta request from Planning (QA-3) → Flow 1 for the extra quantity, or a release of the
   difference.

## F. Data shapes

- **Stock request terms** (`negotiation.md` §5): `resource_type = STOCK`, **item**, **quantity**, **needed_by**,
  **order_id**, **case_id**, `facts_version`.
- **Offer / counter terms:** item, quantity, available date, reason code, `facts_version`, safety stock used (if any).
- **`AGREEMENT_PROPOSED`:** hold id, quantity, date, **expires_at**.
- **`ReservationCommitted` / `ReservationReleased` payload:** order, item, quantity, reservation id, reason.
- **`StockAvailabilityChanged` payload:** item, from date, old and new ATP, list of AT_RISK reservations (id, order,
  missing quantity) and of restored ones.
- **`SafetyStockBreached` payload:** item, safety stock, released quantity, projected minimum.

## G. Concurrency

- Work items are ITEM-scoped. One worker at a time per item; different items in parallel (starting value 4 workers).
- Every change locks the item's balance row (`FOR UPDATE`); check and change happen in the same transaction as the
  ledger row and the outbox event (`quantity_accounting.md` §9).
- Events about one item are handled in order (per-entity order, EV-4); a negotiation session is always about one
  item, so no work item needs two item locks.
- AI wording runs after the decision is saved, outside the lock; a slow model never blocks stock.

## H. Errors and tests

| Situation | What we do | Test |
| --- | --- | --- |
| Same negotiation message twice | Acknowledged as duplicate, no second ledger row | Send twice |
| Same event twice | Ignored by `source_id` | Replay an event |
| Older event version | Ignored (stale) | Deliver v2 then v1 |
| Hold expired before `COMMIT` | `REJECT` `UNAVAILABLE` (or re-hold if still available) | Commit after day change |
| Two requests for the last units | Second gets a counter-offer | Parallel requests |
| Issue larger than the reservation | Refused, error audited (invariant 6) | Fake Warehouse over-issue |
| Model down | Template wording | Fake AI fails |
| Restart mid-work | Work item claimed again; outbox resumes | Kill and restart |

Plus the tests in `2_inventory_agent_functions.md` §11.

## I. Decisions recorded

| ID | Decision |
| --- | --- |
| IB-1 | New folder `backend/app/inventory_agent/` with the Sales layout; reusable parts of `services/inventory_service.py` move into its data access; old service and `agents/inventory/` retired after the Phase 2 review. |
| IB-2 | **All agents:** read functions are an in-process read-only module (`<agent>/reads.py`) that other agents may import; nothing else may be imported across agents (checked by a test); HTTP GET doors remain for demo and team. |

## J. Open

| ID | Item |
| --- | --- |
| IB-O1 | Resolved 2026-10-17: `POST /inventory/setup` while CONFIGURING (`demo.md` §4). |
| IB-O2 | Done 2026-10-17: IB-2 added to `high_level_architecture.md` §3. |
| IB-O3 | Number of Inventory workers (starting 4; measure in Phase 6). |
