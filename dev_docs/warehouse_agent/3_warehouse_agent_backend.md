# Warehouse Agent: Backend Design

**Status:** APPROVED by the developer (2026-10-17). Nothing here is implemented.
**Stack:** FastAPI backend, PostgreSQL on Neon.
**Related:** `1_warehouse_agent_high_level_architecture.md`, `2_warehouse_agent_functions.md`,
`../inventory_agent/3_inventory_agent_backend.md` (same pattern), `../architecture/negotiation.md` §10.

## A. Layers

| # | Layer | Job |
| --- | --- | --- |
| 1 | API doors | A2A endpoint; simulated-delivery input; read-only view doors |
| 2 | Warehouse manager | Work queue with **one writer** (WB-2); the daily routine (WB-3) |
| 3 | Rules | Answer rule, complete kits (WF-1), receiving rule (WF-2), shipping list, capacity-change walk |
| 4 | Calculation | Pure functions from `2_warehouse_agent_functions.md` §4.1 |
| 5 | AI wording | Negotiation wording only (WH-5) |
| 6 | Data access | The only code that reads and writes the `warehouse` schema |
| 7 | Read module | `reads.py`: `free_receiving`, `free_space`, `commitments_for` (IB-2) |
| 8 | Connectors | Negotiation client (outbox → A2A), AI model, event publisher (outbox), read modules of Inventory and Planning |
| Side | Audit, settings, errors | |

**Folder (WB-1):** `backend/app/warehouse_agent/` with the Sales layout (`manager.py`, `rules.py`, `calc.py`,
`agent.py`, `prompts.py`, `data_access.py`, `reads.py`, `connectors.py`, `api.py`, `models.py`, `views.py`). There is
no old Warehouse code to retire.

## B. API doors

| # | Door | Who | Returns |
| --- | --- | --- | --- |
| 1 | `/a2a/warehouse` | Purchasing, Planning (A2A) | Store and acknowledge |
| 2 | `POST /warehouse/deliveries` | Simulated supplier deliveries (key) | `202` received / duplicate (by `delivery_id`) |
| 3 | `GET /warehouse/receiving?from=&to=` | Team, demo | Capacity, committed, held, free per day |
| 4 | `GET /warehouse/zones/{zone}/space?from=&to=` | Team, demo | Space per day |
| 5 | `GET /warehouse/commitments/{ref}` | Team, demo | Commitments of a delivery or order |
| 6 | `GET /warehouse/ledger?zone=&from=&to=` | Team, demo | Ledger rows |
| 7 | `POST /warehouse/maintenance/reconcile` | Us | Balances vs ledger; reports only |

## C. Functions (plumbing)

**Manager:** `handle_negotiation_message`; `handle_event` (records a work item); `accept_delivery` (door 2: dedupe,
save, work item if due today or earlier); `process_work` (the single writer); `run_day` (WB-3);
`answer_request`; `commit_hold`; `receive_delivery`; `issue_kits`; `store_finished_goods`; `ship`;
`apply_capacity_change`; `reconcile`.

**Connectors:** `negotiation_client` (outbox); `ai_connector` (timeout, one retry, template); `publish` (event
outbox); Inventory and Planning read modules.

## D. Flows

1. **Slot / space request:** A2A stored and acknowledged → work item → answer rule → reply through the outbox.
2. **Hold, commit, abort, expiry** as in Inventory; commit of a delivery slot → `ReceivingSlotCommitted`.
3. **Delivery arrives:** door 2 stores it → on its day (or at once if the day already started) → `receive_delivery`
   (WF-2) → `MaterialReceived` (received and refused quantities).
4. **Daily routine** on `SimulatedDayStarted` (WB-3), in this order:
   1. expire holds (frees capacity first);
   2. receive the day's stored deliveries;
   3. issue complete kits for production orders starting today (`MaterialIssuedToProduction`);
   4. ship orders due today within the shipping capacity (`ShipmentDispatched`);
   5. release receiving slots of deliveries that did not arrive the previous day and report them.
5. **Production completed:** `ProductionCompleted` → `store_finished_goods` → `FinishedGoodsStored`.
6. **Supply change:** `SupplierDeliveryDelayed` / `SupplierQuantityReduced` → move or shrink commitments → if the new
   day does not fit, date-change negotiation with Purchasing.
7. **Capacity change** (simulator configuration change) → `apply_capacity_change` → `StorageCapacityChanged`, flags,
   negotiations.

## E. Data shapes

- **Slot / space request terms:** `resource_type` RECEIVING_SLOT or STORAGE_SPACE, **item**, **quantity**,
  **arrival day**, **until day** (planned issue or shipment), **case_id**, delivery or order ref, `facts_version`.
- **Simulated delivery:** **delivery_id**, **purchasing_commitment_ref**, **item**, **quantity**, **arrival day**.
- **`MaterialReceived` payload:** item, received quantity, refused quantity, commitment ref.
- **`MaterialIssuedToProduction` payload:** production order, per component: issued and missing quantity; kits issued.
- **`FinishedGoodsStored` payload:** order, item, quantity, zone.
- **`ShipmentDispatched` payload:** order, item, quantity, date.
- **`StorageCapacityChanged` payload:** zone or receiving, old and new capacity, from date, flagged commitments.

## F. Concurrency (WB-2)

- All Warehouse writes run through one worker, one work item at a time; reads (doors, read module) run in parallel.
- Each write is still one transaction (ledger + balance + outbox event) under row locks, so a later split into
  several writers needs no data change.
- AI wording runs after the decision is saved; the writer never waits for the model.
- If Phase 6 measurements show waiting, split by resource with a fixed lock order (receiving → materials → finished
  goods).

## G. Errors and tests

| Situation | What we do | Test |
| --- | --- | --- |
| Same delivery posted twice | Duplicate, nothing repeated | Post twice |
| Delivery without a committed slot | Received if receiving and space are free today; else refused and reported | Unexpected delivery |
| Over-delivery | Excess refused (WF-2) | Deliver 120 % |
| Kits short | Issue complete kits, report missing (WF-1) | §5.2 example |
| Shipping capacity exceeded | Earliest committed first; rest next day, reported | Many orders due |
| Repeated event / message | No second ledger row | Replay |
| Restart in the middle of the daily routine | Each step is its own work item; finished steps are not repeated | Kill during `run_day` |

Plus the tests in `2_warehouse_agent_functions.md` §11.

## H. Decisions recorded

| ID | Decision |
| --- | --- |
| WB-1 | New folder `backend/app/warehouse_agent/` with the Sales layout. |
| WB-2 | One writer for all Warehouse changes; reads in parallel; split by resource only if measurements show waiting. |
| WB-3 | Daily routine order on `SimulatedDayStarted`: expire holds → receive → issue kits → ship → release slots of missed deliveries. |

## I. Open

| ID | Item |
| --- | --- |
| WB-O1 | Exact simulated-delivery input (who decides short or late arrivals) — with the Purchasing doc and `demo.md` (WH-O2). |
| WB-O2 | Resolved 2026-10-17: Factory A defaults in `demo.md` §4.1. |
