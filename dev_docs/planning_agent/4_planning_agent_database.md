# Planning Agent: Database Design

**Status:** APPROVED by the developer (2026-10-17). Nothing here is created or migrated.
**Database:** PostgreSQL on Neon (`DATABASE_URL`; tests use `TEST_DATABASE_URL`).
**Schemas:** `planning` (owned by Planning) and changes to the shared reference schema `core`.
**Related:** `1_planning_agent_high_level_architecture.md`, `2_planning_agent_functions.md`,
`3_planning_agent_backend.md`, `../architecture/quantity_accounting.md` (ledger rules), `../sales_agent/4_sales_agent_database.md`.

## 1. Ground rules

1. Planning writes only the `planning` schema. `core` is shared reference data, read-only for every agent and set
   through the simulator's configuration.
2. Other agents' records are referenced by their ids only (for example a reservation id from Inventory); Planning
   never stores copies of their quantities as truth.
3. No price, cost or stored priority. Urgency is computed when needed (deadline slack, NG-3).
4. All times UTC; planning dates are `DATE` (whole days). Ids are UUIDs. JSON means JSONB.
5. Statuses are fixed lists enforced by the database.
6. Machine-hours follow the ledger + balance rule (QA-1).

## 2. Changes to the shared reference schema `core` (PD-2)

| Table | Change |
| --- | --- |
| `core.items` (exists) | Add `sourcing` (MAKE or BUY) and `space_per_unit` (used by Warehouse). `item_type` stays. |
| `core.bom`, `core.bom_items` (exist) | No change; they already allow any depth (RD-1). |
| `core.routings` (new) | id (PK) · item_id (FK) · step_no · work_center_code · skill · crew_size · setup_hours · run_hours_per_unit. Unique (item_id, step_no). |

Supplier lead times, multiples and minimums are Purchasing's data (read through its read function), not `core`.
Sales' placeholder `sales_agent.products` is linked to `core.items` at integration (Sales D4.2).

## 3. The `planning` tables

(PK = primary key, FK = link.)

### Capacity (Planning owns machine-hours)

**work_centers** — id (PK) · code (unique) · name · machine_hours_per_day · efficiency_pct (default 100) · active

**work_center_days** (balance, one row per work center and day, created when first needed) — work_center_id (FK) ·
date · capacity_hours · committed_hours · held_hours · note (e.g. MACHINE_DOWN). Unique (work_center_id, date).

**machine_hours_ledger** — id (PK) · work_center_id (FK) · date · bucket (CAPACITY, COMMITTED, HELD) · delta · reason
(HOLD, HOLD_EXPIRED, COMMIT, RELEASE, CANCEL, MACHINE_DOWN, ADJUSTMENT) · production_order_id · case_id · source_id ·
line_no · sim_time · created_at. Unique (source_id, line_no).

### Demand and answers to Sales

**customer_demands** (one per Sales request / order line) — id (PK) · request_ref (unique) · sales_inquiry_id ·
sales_order_id (empty until confirmed) · customer_id (reference only, never used for feasibility) · item_id (FK core) ·
quantity · requested_date · order_date · committed_quantity · committed_date · chosen_option_id (FK) · status (§4) ·
request_payload (JSON, exactly what Sales sent) · version · created_at · updated_at

**options** — id (PK) · demand_id (FK) · kind (REQUESTED, LATER_DATE, LESS_QUANTITY) · quantity · delivery_date ·
valid_until · held (yes/no) · reason_code · status (OFFERED, CHOSEN, EXPIRED, WITHDRAWN)

**sales_outbox** — id (PK) · request_ref · payload (JSON planning result) · status (PENDING, SENT, FAILED) · attempts ·
next_attempt_at · last_error

### Cases (the "why" behind negotiations)

**cases** — id (PK; the `case_id` in negotiations and events) · demand_id (FK) · kind (NEW_REQUEST, COMMIT, REPAIR,
CHANGE, CANCEL) · cause_event_id · depth (follow-up depth, HA-6) · status (OPEN, RESOLVED, ESCALATED, FAILED) ·
chosen_alternative_key · created_at · closed_at

### Production

**production_orders** — id (PK) · demand_id (FK) · item_id (FK core) · quantity · start_date · end_date · status (§4) ·
quantity_completed · case_id (FK) · version · created_at · updated_at

**production_order_steps** (the schedule per day) — id (PK) · production_order_id (FK) · step_no · work_center_id (FK) ·
skill · crew_size · date · machine_hours · worker_hours · hr_commitment_ref. Unique (production_order_id, step_no, date).

**shop_floor_reports** — report_id (PK) · production_order_id (FK) · kind (STARTED, QUANTITY_COMPLETED, MACHINE_DOWN) ·
quantity · work_center_id · days (JSON) · received_at

### Procurement (Planning starts it, HA-3; Purchasing owns the commitment)

**procurement_demand_lines** (one per order need, before grouping) — id (PK) · demand_id (FK) · production_order_id (FK,
the parent that needs it) · item_id · quantity · need_date · procurement_request_id (FK)

**procurement_requests** (grouped per item and release date, PL-3) — id (PK) · item_id · quantity (after lot size) ·
need_date · release_date · status (PLANNED, NEGOTIATING, COMMITTED, CANCEL_REQUESTED, CANCELLED) ·
purchasing_commitment_ref · case_id · version

### Pegging (RD-5)

**pegs** — id (PK) · top_demand_id (FK customer_demands) · level · demand_kind (CUSTOMER_DEMAND, PRODUCTION_ORDER) ·
demand_ref · item_id · quantity · need_date · supply_kind (STOCK_RESERVATION, STOCK_HOLD, PRODUCTION_ORDER,
PROCUREMENT_REQUEST, PURCHASE_COMMITMENT) · supply_ref · rebuild_no · created_at.
Index on (supply_kind, supply_ref) — "which orders does this supply serve?" is the impact lookup.

### Plumbing

**Queue tables** (`work_items` and any outbox here) use the standard queue shape of `../architecture/system_design.md` §4.2: `scope_key` (the "one at a time" key; `ref` below), `status` adds RUNNING, plus `locked_by`, `locked_until`, `last_error`, `done_at` (SD-1).

**work_items** (PB-4) — id (PK) · scope (ORDER, ITEM) · ref · kind · payload (JSON) · status (PENDING, DONE, FAILED) ·
attempts · next_attempt_at · created_at

**event_versions** (stale check) — entity_type · entity_id · last_version. PK (entity_type, entity_id).

**audit_log** — id (PK) · time · actor (PLANNING_AI, SYSTEM, HUMAN) · event_type (e.g. REQUEST_PLANNED,
OPTIONS_SENT, ALTERNATIVES_RANKED, COMMITTED, COMMIT_FAILED, REPLANNED, ESCALATED) · demand_id · case_id · details
(JSON; for rankings the full table of criterion values and who chose: AI or fixed rule, PD-3)

## 4. Statuses

| Table | Statuses |
| --- | --- |
| customer_demands | RECEIVED → PLANNING → ANSWERED → CONFIRMED → COMMITTED → COMPLETED; side: COMMIT_FAILED, EXPIRED, CANCELLED, NOT_FEASIBLE (the customer was told nothing can be offered: no option found, or none could be secured) |
| production_orders | PLANNED → FIRM → RELEASED → STARTED → COMPLETED; side: CANCELLED (RD-4) |
| procurement_requests | PLANNED → NEGOTIATING → COMMITTED; side: CANCEL_REQUESTED → CANCELLED (only if Purchasing agrees) |
| options | OFFERED → CHOSEN; side: EXPIRED, WITHDRAWN |
| cases | OPEN → RESOLVED; side: ESCALATED, FAILED |

## 5. Relationships

| One | Many | Note |
| --- | --- | --- |
| customer_demands | options, cases, production_orders, procurement_demand_lines, pegs (top) | |
| production_orders | production_order_steps, shop_floor_reports, procurement_demand_lines (as parent) | |
| procurement_requests | procurement_demand_lines | Grouping across orders (PL-3) |
| work_centers | work_center_days, machine_hours_ledger, production_order_steps | |
| cases | production_orders, procurement_requests, ledger rows | Loose links |
| core.items | routings, customer_demands, production_orders, pegs | Shared reference |

Negotiation sessions live in the shared `negotiation` schema and carry the `case_id` (PD-O3).

## 6. Rules the database enforces

- Unique `request_ref`, `report_id`, (`source_id`, `line_no`) in the ledger, (work_center_id, date) in the balance.
- At most one CHOSEN option per demand.
- Quantities and hours never negative; `quantity_completed ≤ quantity`.
- Status values only from the lists in §4.
- No columns for price, cost or priority.

The rule "committed + held ≤ capacity" is checked by code under a row lock, not by a constraint, because a capacity
cut (machine down) may leave an excess that must be flagged, not rejected (`quantity_accounting.md` invariant 3).

## 7. Decisions recorded

| ID | Decision |
| --- | --- |
| PD-1 | New `planning` tables; the old `mps_plans` and `mrp_requirements` stay untouched until the Phase 2 review, then are dropped by a migration. The MPS is represented by finished-goods production orders and customer demands. |
| PD-2 | `core` stays the shared reference: `items` gains `sourcing` (MAKE/BUY) and `space_per_unit`; new `core.routings`. Work centers and calendars are in `planning`. |
| PD-3 | Ranked alternatives are stored as JSON in the audit record of the decision; no separate table. |

## 8. Open

| ID | Question |
| --- | --- |
| PD-O1 | Resolved 2026-10-17: cleared on reset; kept in the run report (DM-4). |
| PD-O2 | Resolved 2026-10-17: created lazily; calendars set through `POST /planning/setup` (`demo.md` §4). |
| PD-O3 | The shared `negotiation` schema needs a `case_id` on sessions (negotiation contract change, Phase 3 step 3). |

## 9. Neon notes

Same as Sales: the first request after idle may be slow, so the backend retries the connection. Tests use their own
database. Exact Neon limits not checked.
