# Inventory Agent: Database Design

**Status:** APPROVED by the developer (2026-10-17). Nothing here is created or migrated.
**Database:** PostgreSQL on Neon (`DATABASE_URL`; tests use `TEST_DATABASE_URL`).
**Schema:** `inventory` (owned by Inventory). Items come from the shared `core.items`.
**Related:** `1_inventory_agent_high_level_architecture.md`, `2_inventory_agent_functions.md`,
`3_inventory_agent_backend.md`, `../architecture/quantity_accounting.md` (ledger, formulas, invariants).

## 1. Ground rules

1. Inventory writes only the `inventory` schema; it reads `core.items` (shared reference).
2. One factory site (IN-O2): balances are per item, no warehouse or location column (space is Warehouse's, IN-1).
3. Every quantity change is a ledger row plus a balance update in one transaction (QA-1).
4. Holds and reservations name what they serve: a customer demand or a production order (ID-2).
5. No price, cost or priority. Times UTC; dates `DATE`; ids UUID; JSON = JSONB. Statuses enforced by the database.

## 2. Tables

**stock_balances** (one row per item) — item_id (PK, FK `core.items`) · on_hand · reserved · held ·
incoming_total · safety_stock · safety_stock_released · version · updated_at

**stock_ledger** — id (PK) · item_id · bucket (ON_HAND, RESERVED, HELD, INCOMING, SAFETY_STOCK) · delta · reason
(RECEIPT, ISSUE, FG_STORED, SHIPMENT, HOLD, HOLD_EXPIRED, HOLD_ABORTED, COMMIT, RELEASE, CHANGE, SAFETY_STOCK_USE,
INCOMING_ADDED, INCOMING_CHANGED, ADJUSTMENT) · for_kind · for_ref · case_id · hold_id · reservation_id · receipt_id ·
source_id · line_no · sim_time · created_at. Unique (source_id, line_no).

**holds** — id (PK) · item_id · quantity · due_date · for_kind (CUSTOMER_DEMAND, PRODUCTION_ORDER) · for_ref
(Planning's id) · case_id · negotiation_id (unique) · expires_at · safety_stock_used · status (§3) · created_at

**reservations** — id (PK) · item_id · quantity · quantity_issued · due_date · for_kind · for_ref · case_id · hold_id
(unique; the hold it came from) · status (§3) · missing_quantity (when AT_RISK) · version · created_at · updated_at

**incoming_receipts** (Inventory's view of committed supply; Purchasing owns the commitment itself) — id (PK) ·
purchasing_commitment_ref (unique) · item_id · quantity · quantity_received · expected_date · status (§3) ·
source_version (Purchasing's entity version) · updated_at

**Queue tables** (`work_items` and any outbox here) use the standard queue shape of `../architecture/system_design.md` §4.2: `scope_key` (the "one at a time" key; `ref` below), `status` adds RUNNING, plus `locked_by`, `locked_until`, `last_error`, `done_at` (SD-1).

**work_items** — id (PK) · scope (ITEM) · ref (item id) · kind · payload (JSON) · status (PENDING, DONE, FAILED) ·
attempts · next_attempt_at · created_at

**event_versions** — entity_type · entity_id · last_version. PK (entity_type, entity_id).

**audit_log** — id (PK) · time · actor (INVENTORY_AI, SYSTEM, HUMAN) · event_type (e.g. REQUEST_ANSWERED,
HOLD_PLACED, COMMITTED, SAFETY_STOCK_RELEASED, MARKED_AT_RISK, RECONCILE_DIFFERENCE) · item_id · case_id · details (JSON)

Negotiation outbox and inbox are in the shared `negotiation` schema (NG-1); events in the shared `events` schema.

## 3. Statuses

| Table | Statuses |
| --- | --- |
| holds | ACTIVE → COMMITTED; side: EXPIRED, ABORTED |
| reservations | ACTIVE ↔ AT_RISK → ISSUED; side: RELEASED |
| incoming_receipts | EXPECTED → PARTLY_RECEIVED → RECEIVED; side: CANCELLED |

## 4. Relationships

| One | Many | Note |
| --- | --- | --- |
| core.items | stock_balances (one), stock_ledger, holds, reservations, incoming_receipts | |
| holds | reservations (at most one) | A committed hold becomes one reservation |
| reservations, holds, incoming_receipts | stock_ledger | Each ledger row says which record it changed |

Links to other agents are ids only: `for_ref` (Planning's demand or production order), `case_id`, `negotiation_id`,
`purchasing_commitment_ref`.

## 5. How the balance relates to the records (checked by reconcile)

| Balance column | Equals |
| --- | --- |
| `held` | Σ quantity of ACTIVE holds |
| `reserved` | Σ (quantity − quantity_issued) of ACTIVE and AT_RISK reservations |
| `incoming_total` | Σ (quantity − quantity_received) of EXPECTED and PARTLY_RECEIVED receipts |
| every column | Σ of its ledger deltas |

ATP by date (QA-4) is computed from `stock_balances` + the due dates of holds and reservations + the expected dates of
incoming receipts; nothing date-based is stored in the balance.

## 6. Rules the database enforces

- All quantities and balance columns ≥ 0; `quantity_issued ≤ quantity`; `quantity_received ≤ quantity` (unless
  over-delivery is allowed later).
- Unique (source_id, line_no) in the ledger → a repeated event or message cannot change numbers twice.
- One hold per negotiation; one reservation per hold; one incoming receipt per Purchasing commitment.
- Status values only from §3.

"Never promise more than ATP" is checked by code under the row lock (it depends on dates), not by a constraint.

## 7. Decisions recorded

| ID | Decision |
| --- | --- |
| ID-1 | New `inventory` tables; the old `warehouses`, `inventory_balance`, `inventory_reservations` stay untouched until the Phase 2 review, then are dropped. Reserve/release logic moves over (IB-1), not the old shapes. |
| ID-2 | Holds and reservations are made for a customer demand (finished goods) or a production order (components), using Planning's ids, plus the case id. |

## 8. Open

| ID | Question |
| --- | --- |
| ID-O1 | Resolved 2026-10-17: cleared on reset; kept in the run report (DM-4). |
| ID-O2 | Resolved 2026-10-17: set through `POST /inventory/setup`; Factory A defaults in `demo.md` §4.1. |
