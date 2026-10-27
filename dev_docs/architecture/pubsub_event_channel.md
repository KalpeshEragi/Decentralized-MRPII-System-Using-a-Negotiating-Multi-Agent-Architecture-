# Publish–Subscribe Event Channel

**Status:** APPROVED by the developer (2026-10-17). Nothing here is implemented; the current code has no
event channel (`agents/workflow.py` calls agents directly, step by step).
**Related:** `high_level_architecture.md` (§3 runtime, §5 two mechanisms), `negotiation.md`, `quantity_accounting.md`.

## 1. Purpose

The event channel lets an agent announce a fact once ("supplier delivery is 5 days late") and have every interested
agent hear it, without the publisher knowing or calling them. It is shared infrastructure: it stores, delivers,
retries and deduplicates. It never decides anything and never changes business data.

## 2. Decisions (2026-10-17)

| ID | Decision |
| --- | --- |
| EV-1 | Events are stored in PostgreSQL (Neon). A dispatcher inside the backend polls for work about every 0.5 s. No Kafka, RabbitMQ, Redis or LISTEN/NOTIFY for now. |
| EV-2 | Outbox rule: a business change and its event are saved in the same transaction by the owning agent. |
| EV-3 | One delivery row per (event, subscriber). The subscriber's business change and marking its delivery done are saved in the same transaction. |
| EV-4 | Order is kept per entity: for one subscriber, events about the same entity are handled in the order published; unrelated events run in parallel. An older version never overwrites newer state. |
| EV-5 | An event carries the changed facts needed to react (plus ids and version), not only ids and not a full copy of the record. |
| EV-6 | Subscriptions are a static list in code, documented in §8. **Since 2026-10-27 (EM-1):** the list is the event catalogue `backend/app/events/catalogue.py` (payload models, status, versions; checked at publish and subscribe), shown on the frontend page `/events`. |

## 3. What goes on the channel and what does not

| On the channel | Not on the channel |
| --- | --- |
| Facts and agreed outcomes: `OrderConfirmed`, `ReservationCommitted`, `SupplierDeliveryDelayed`, `PlanRevised` | Individual negotiation messages (offers, counter-offers): they stay in the negotiation layer |
| | Sales ↔ Planning request and result: these keep their own doors (Sales decision 1.1) |
| | LLM requests (the AI queue is separate) |
| | Reads: an agent that needs data uses the owner's read function |

The negotiation layer itself publishes nothing. When a negotiation ends in agreement, **the owner of the resource**
commits it and publishes the fact (for example Inventory publishes `ReservationCommitted`).

## 4. Event envelope

Every event has the same outer shape.

| Field | Meaning |
| --- | --- |
| `event_id` | UUID, unique. Used for deduplication. |
| `event_type` | Past-tense fact name, e.g. `SupplierDeliveryDelayed`. |
| `schema_version` | Version of this event type's payload shape (starts at 1). |
| `publisher` | Agent that owns the fact: `SALES`, `PLANNING`, `INVENTORY`, `PURCHASING`, `WAREHOUSE`, `HR`; or `SIMULATOR_CLOCK` for the time event only (§9, PB-3). |
| `entity_type`, `entity_id` | The thing the fact is about (`order`, `item`, `supplier_commitment`, `storage_zone`, `worker`, ...). |
| `entity_version` | Integer, +1 each time the owner changes that entity. Used for the stale check. |
| `correlation_id` | The case this belongs to (usually the customer order or the disruption case id). |
| `causation_id` | The `event_id` that caused this one, if any. Builds the "why" chain for the timeline. |
| `occurred_at` | When the fact happened (simulated time). |
| `published_at` | When it was saved (real time). |
| `payload` | The changed facts (JSON), defined per event type in §8. |

Example:

```json
{
  "event_id": "7f1c...", "event_type": "SupplierDeliveryDelayed", "schema_version": 1,
  "publisher": "PURCHASING", "entity_type": "supplier_commitment", "entity_id": "SC-17", "entity_version": 3,
  "correlation_id": "CASE-0042", "causation_id": null,
  "occurred_at": "2026-11-03T00:00:00Z", "published_at": "2026-10-17T10:12:03Z",
  "payload": { "item_id": "BAT-01", "quantity": 2000, "old_delivery_date": "2026-11-05", "new_delivery_date": "2026-11-10" }
}
```

## 5. Storage (two tables, own `events` schema)

**`events`**: one row per event, the envelope above. Never updated or deleted during a run.

Both queue tables of the channel (`event_deliveries` here, and the negotiation inbox and outbox) use the standard queue shape of `system_design.md` §4.2 (SD-1); `entity_key` is their `scope_key`.

**`event_deliveries`**: one row per (event, subscriber).

| Column | Meaning |
| --- | --- |
| `event_id`, `subscriber` | Together unique. |
| `entity_key` | `entity_type:entity_id`, copied for the ordering rule. |
| `status` | `PENDING`, `DONE`, `IGNORED_STALE`, `FAILED`. |
| `attempts`, `next_attempt_at`, `last_error` | Retry state. |
| `done_at` | When handled; with `published_at` gives the delivery lag. |

## 6. How it works

### 6.1 Publishing (inside the owner's transaction)

1. The agent changes its own data.
2. In the same transaction it inserts the event and one `PENDING` delivery row per subscriber from the static list.
3. Commit. Either everything is saved or nothing is: no lost event, no event for a change that did not happen.

### 6.2 Delivering (the dispatcher)

A small loop in the backend, with a few workers (starting value 4). Each worker repeatedly:

1. Starts a transaction and claims one `PENDING` delivery whose `next_attempt_at` has passed, **and** which has no
   earlier unfinished delivery for the same subscriber and `entity_key` (per-entity order). The row is locked so no
   other worker takes it (`FOR UPDATE SKIP LOCKED`).
2. Calls the subscriber agent's handler for that event type inside the same transaction.
3. Marks the delivery `DONE` and commits, together with the handler's own changes.
4. If the handler fails: roll back everything, then in a new transaction increase `attempts` and set `next_attempt_at`.

If the program crashes mid-way, the transaction is undone and the row is simply claimed again after restart.

### 6.3 Handler rules

- **Quick and deterministic.** A handler updates the agent's own state and, if needed, records a work item in the
  agent's own queue (for example "re-check order 42"). It never calls the LLM and never waits on a negotiation
  inside the transaction; that work runs later from the agent's queue.
- **Stale check.** The agent stores the last `entity_version` it applied per entity. A lower or equal version →
  the delivery is marked `IGNORED_STALE` and nothing changes.
- **Duplicate check.** A delivery already `DONE` is never claimed again; the version check also makes a repeat harmless.
- A handler may publish new events (with `causation_id` set) through the outbox rule.

### 6.4 Retries and failures

| Attempt | Wait before next |
| --- | --- |
| 1 → 2 | 1 s |
| 2 → 3 | 5 s |
| 3 → 4 | 30 s |
| 4 → 5 | 2 min |
| after 5 | `FAILED` |

(starting values). A `FAILED` delivery is shown in the timeline with its error and flags staff. Later events for the
same entity at that subscriber **wait** (order is never broken); a manual "retry" door re-queues it.

## 7. Agent work queue vs event delivery vs AI queue

Three different queues, never combined:
- **Event deliveries** (this doc): facts arriving at an agent.
- **Agent work queue**: things an agent must do, ordered by its own priority rule (`negotiation.md`).
- **AI queue**: requests waiting for the shared model (Ollama).

## 8. Event catalogue (initial)

Starting set, grounded in the order flow and the disruptions in the brief. New events are added only with a real
reaction to document. One fact = one event name.

| Event | Publisher | Subscribers | Payload (besides envelope) | Expected reaction |
| --- | --- | --- | --- | --- |
| `OrderConfirmed` | Sales | Planning | order, option, product, quantity, delivery date | Planning re-validates and asks owners to commit |
| `OrderChangeRequested` | Sales | Planning | order, old and new quantity/date | Planning re-checks feasibility |
| `OrderCancelled` | Sales | Planning | order | Planning releases its plan; owners release via `PlanRevised` |
| `PlanCommitted` | Planning | Sales, Inventory, Purchasing, Warehouse, HR | order, plan version, dates, quantities per owner | Owners turn holds into commitments; Sales tells the customer |
| `PlanCommitFailed` | Planning | Sales, Inventory, Purchasing, Warehouse, HR | order, reason code | Owners release holds; Sales informs honestly |
| `PlanRevised` | Planning | Sales, Inventory, Purchasing, Warehouse, HR | order, plan version, what changed | Owners adjust; Sales informs if customer-visible |
| `PlanAtRisk` | Planning | Sales | order, reason, current estimate | Sales may warn the customer |
| `ProductionOrderReleased` | Planning | Warehouse, HR, Inventory | production order, item, quantity, start/end dates, work center, required material | Warehouse prepares material issue; HR confirms shift assignments; Inventory turns the reservation into an issue request (RD-7) |
| `ProductionStarted` | Planning | Sales, Inventory, Warehouse | order, quantity, start date | Warehouse issues material; Inventory books issue |
| `ProductionCompleted` | Planning | Sales, Warehouse, HR | order, production order, quantity, completion day | Warehouse stores finished goods (then publishes `FinishedGoodsStored`); HR frees unused later hours (HB-3) |
| `ReservationCommitted` | Inventory | Planning | order, item, quantity, reservation id | Planning marks material secured |
| `ReservationReleased` | Inventory | Planning | order, item, quantity, reason | Planning re-checks if needed |
| `StockAvailabilityChanged` | Inventory | Planning | item, old and new available quantity, from date | Planning re-checks affected orders |
| `SafetyStockBreached` | Inventory | Planning | item, available, safety stock | Planning plans a refill at once (RD-6) |
| `ProcurementCommitted` | Purchasing | Planning, Inventory, Warehouse | item, quantity, delivery date, commitment id | Inventory counts it as incoming; Warehouse expects it |
| `SupplierDeliveryDelayed` | Purchasing | Planning, Inventory, Warehouse | item, quantity, old and new delivery date | See `high_level_architecture.md` §6.5 |
| `SupplierQuantityReduced` | Purchasing | Planning, Inventory, Warehouse | item, old and new quantity, delivery date | Planning re-checks; may procure the gap |
| `ReceivingSlotCommitted` | Warehouse | Purchasing, Planning | commitment id, date, space units | Purchasing confirms delivery date can be received |
| `MaterialReceived` | Warehouse | Inventory, Purchasing, Planning | item, quantity received, commitment id | Inventory increases stock; Purchasing closes or flags short delivery |
| `MaterialIssuedToProduction` | Warehouse | Inventory, Planning | order, item, quantity | Inventory reduces stock and reservation |
| `FinishedGoodsStored` | Warehouse | Inventory, Planning, Sales | order, item, quantity, zone | Inventory raises finished-goods on-hand; Planning marks the order ready to ship (IN-2) |
| `StorageCapacityChanged` | Warehouse | Planning, Purchasing | zone, old and new capacity, from date | Re-check affected receipts |
| `ShipmentDispatched` | Warehouse | Sales, Inventory, Planning | order, quantity, date | Sales informs customer; Inventory reduces finished goods |
| `WorkforceCommitted` | HR | Planning | order or task, hours per day, dates, skill | Planning marks labor secured |
| `WorkforceCapacityChanged` | HR | Planning | skill, date range, old and new hours | Re-check schedules that use those hours |
| `SimulatedDayStarted` | Simulator clock (infrastructure, PB-3) | Planning, Inventory, Sales, Warehouse, HR, Purchasing (daily routines WB-3, HB-3; Purchasing's adapter follows open requests, PI-3) | date | Planning releases due production orders; Inventory expires holds; Sales checks offer expiry |

Not events (on purpose): `FeasibilityRequested` / `FeasibilityResult` (Sales doors), `MaterialRequirementsCalculated`
(internal to Planning; Planning negotiates with owners directly), `StockChecked` / `ReceivingChecked` /
`WorkforceChecked` (these are reads or negotiation steps, not facts others need).

## 9. Simulator triggers

A trigger does not publish events itself. It changes the simulated outside world through the **owner's input**
(supplier adapter → Purchasing; shop-floor adapter → Planning (RD-3); worker absence → HR; storage change → Warehouse; customer message → Sales), and the
owner publishes the event as usual. So a trigger travels exactly the normal path and never tells agents what to do.

**One exception (PB-3, 2026-10-17):** the simulator clock publishes `SimulatedDayStarted(date)` when a simulated day
begins. It carries time only — never a business fact — so agents that need time (releasing orders, expiring holds and
offers) subscribe to it instead of each reading the clock.

## 10. Observability and reset

- The demo timeline is built from `events` + `event_deliveries` (what happened, who heard it, when, handled or failed),
  linked by `correlation_id` and `causation_id`.
- Measured per delivery: lag (`done_at − published_at`), attempts, failures.
- Reset/replay empties both tables together with the agents' run data, so nothing leaks into the next run.

## 11. Open

| ID | Question |
| --- | --- |
| EV-O1 | Exact payload fields per event (fixed when each agent's doc is written). |
| EV-O2 | Resolved 2026-10-17: production events stay with Planning (RD-3, RD-7). |
| EV-O3 | Resolved 2026-10-17: events of a run are cleared on reset and kept in the run report (DM-4). |
| EV-O4 | LISTEN/NOTIFY as a speed-up, only if measured lag is a problem (must be checked against Neon first). |
