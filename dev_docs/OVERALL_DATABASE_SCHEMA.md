## Overview

The system uses a single PostgreSQL (Neon Serverless) database organized into logical schemas.
The database acts as the shared system of record, while autonomous agents make
decisions using domain services/tools.

### Logical Schemas

- `core` — Products, items, and BOM
- `sales` — Customers, customer orders, and customer ordered items
- `inventory` — Warehouses, stock, and reservations
- `planning` — MPS and MRP requirements
- `supplier_service` — Procurable items, suppliers and supplier items (Supplier Service master data)
- `purchasing_agent` — Purchasing Contracts, Procurement Requests, requisitions (Legs) and Purchasing decision audit
- `production` — Machines, production orders, and schedules (legacy design, not built; see §6)
- `agent` — Agent definitions and internal agent state
- `negotiation_engine` — Negotiation sessions, participants (agents or suppliers) and messages
- `simulation` — What-if scenarios and simulated disruptions (events)
- `audit` — Agent decision history
- Legacy, untouched and not used by the new Purchasing Agent / Negotiation Engine: `purchasing`, `negotiation`

---

# 1. Core Schema

## `core.items`

Stores all products and materials used by the MRPII system.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique item ID |
| `sku` | VARCHAR | UNIQUE, NOT NULL | Stock keeping unit |
| `name` | VARCHAR | NOT NULL | Item name |
| `item_type` | ENUM | NOT NULL | Finished product / raw material / component |
| `unit` | VARCHAR | NOT NULL | Unit of measurement |
| `description` | TEXT | | Item description |
| `is_active` | BOOLEAN | DEFAULT TRUE | Whether item is active |
| `created_at` | TIMESTAMP | | Creation time |
| `updated_at` | TIMESTAMP | | Last update time |

---

## `core.bom`

Stores Bill of Materials (BOM) definitions for products.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | BOM ID |
| `parent_item_id` | UUID | FK → `core.items.id` | Finished/parent item |
| `version` | INTEGER | NOT NULL | BOM version |
| `is_active` | BOOLEAN | DEFAULT TRUE | Active BOM version |
| `created_at` | TIMESTAMP | | Creation time |

---

## `core.bom_items`

Stores the components required by a BOM.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | BOM item ID |
| `bom_id` | UUID | FK → `core.bom.id` | Parent BOM |
| `component_item_id` | UUID | FK → `core.items.id` | Required component |
| `quantity_required` | DECIMAL | NOT NULL | Quantity required per parent item |

---

# 2. Sales Schema

## `sales.customers`

Stores customer information.

| Column         | Type      | Constraint | Description         |
| -------------- | --------- | ---------- | ------------------- |
| `id`           | UUID      | PK         | Customer ID         |
| `name`         | VARCHAR   | NOT NULL   | Customer name       |
| `location`     | VARCHAR   | NOT NULL   | Customer location   |
| `contact_info` | JSONB     | NOT NULL   | Contact information |
| `created_at`   | TIMESTAMP |            | Creation time       |

---

## `sales.customer_orders`

Stores customer orders.

| Column         | Type      | Constraint                | Description            |
| -------------- | --------- | ------------------------- | ---------------------- |
| `id`           | UUID      | PK                        | Order ID               |
| `customer_id`  | UUID      | FK → `sales.customers.id` | Customer               |
| `order_number` | VARCHAR   | UNIQUE, NOT NULL          | Order number           |
| `order_date`   | DATE      | NOT NULL                  | Order date             |
| `due_date`     | DATE      | NOT NULL                  | Required delivery date |
| `priority`     | INTEGER   | NOT NULL                  | Order priority         |
| `status`       | VARCHAR   |                           | Order status           |
| `created_at`   | TIMESTAMP |                           | Creation time          |

---

## `sales.customer_order_items`

Stores products and quantities within customer orders.

| Column     | Type    | Constraint                      | Description      |
| ---------- | ------- | ------------------------------- | ---------------- |
| `id`       | UUID    | PK                              | Order item ID    |
| `order_id` | UUID    | FK → `sales.customer_orders.id` | Customer order   |
| `item_id`  | UUID    | FK → `core.items.id`            | Ordered item     |
| `quantity` | DECIMAL | NOT NULL                        | Ordered quantity |

```text
sales.customers
       │
       └──< sales.customer_orders
                    │
                    └──< sales.customer_order_items >── core.items
```

---

# 3. Inventory Schema

## `inventory.warehouses`

Stores warehouse information.

| Column     | Type    | Constraint | Description        |
| ---------- | ------- | ---------- | ------------------ |
| `id`       | UUID    | PK         | Warehouse ID       |
| `name`     | VARCHAR | NOT NULL   | Warehouse name     |
| `location` | VARCHAR | NOT NULL   | Warehouse location |

---

## `inventory.inventory_balance`

Stores current inventory quantities.

| Column         | Type      | Constraint                     | Description          |
| -------------- | --------- | ------------------------------ | -------------------- |
| `id`           | UUID      | PK                             | Inventory record ID  |
| `item_id`      | UUID      | FK → `core.items.id`           | Item                 |
| `warehouse_id` | UUID      | FK → `inventory.warehouses.id` | Warehouse            |
| `on_hand`      | DECIMAL   | NOT NULL                       | Physical stock       |
| `reserved`     | DECIMAL   | DEFAULT 0                      | Reserved stock       |
| `safety_stock` | DECIMAL   | DEFAULT 0                      | Minimum safety stock |
| `updated_at`   | TIMESTAMP |                                | Last update          |

### Available Quantity

```text
available_quantity =
    on_hand - reserved - safety_stock
```

---

## `inventory.inventory_reservations`

Stores inventory reservations.

| Column         | Type      | Constraint                      | Description        |
| -------------- | --------- | ------------------------------- | ------------------ |
| `id`           | UUID      | PK                              | Reservation ID     |
| `item_id`      | UUID      | FK → `core.items.id`            | Reserved item      |
| `warehouse_id` | UUID      | FK → `inventory.warehouses.id`  | Warehouse          |
| `order_id`     | UUID      | FK → `sales.customer_orders.id` | Related order      |
| `quantity`     | DECIMAL   | NOT NULL                        | Reserved quantity  |
| `status`       | VARCHAR   |                                 | Reservation status |
| `created_at`   | TIMESTAMP |                                 | Creation time      |

---

# 4. Planning Schema

## `planning.mps_plans`

Stores Master Production Schedule (MPS) plans.

| Column             | Type      | Constraint                      | Description                 |
| ------------------ | --------- | ------------------------------- | --------------------------- |
| `id`               | UUID      | PK                              | MPS plan ID                 |
| `order_id`         | UUID      | FK → `sales.customer_orders.id` | Related customer order      |
| `item_id`          | UUID      | FK → `core.items.id`            | Product                     |
| `planned_quantity` | DECIMAL   | NOT NULL                        | Planned production quantity |
| `planned_start`    | TIMESTAMP | NOT NULL                        | Planned start               |
| `planned_end`      | TIMESTAMP | NOT NULL                        | Planned completion          |
| `status`           | VARCHAR   |  NOT NULL                       | Plan status                 |
| `created_at`       | TIMESTAMP |                                 | Creation time               |

---

## `planning.mrp_requirements`

Stores material requirements calculated from MRP.

| Column                | Type      | Constraint                   | Description                  |
| --------------------- | --------- | ---------------------------- | ---------------------------- |
| `id`                  | UUID      | PK                           | MRP requirement ID           |
| `mps_plan_id`         | UUID      | FK → `planning.mps_plans.id` | MPS plan                     |
| `item_id`             | UUID      | FK → `core.items.id`         | Required material            |
| `gross_requirement`   | DECIMAL   | NOT NULL                     | Total material required      |
| `available_inventory` | DECIMAL   | NOT NULL                     | Available inventory (`available_quantity`, excludes incoming) |
| `scheduled_receipts`  | DECIMAL   | NOT NULL                     | Committed incoming quantity due by `required_by` (P0-12, P0-13) |
| `projected_available_quantity` | DECIMAL | NOT NULL           | `available_inventory + scheduled_receipts` (P0-13) |
| `net_requirement`     | DECIMAL   | NOT NULL                     | Additional quantity required |
| `required_by`         | TIMESTAMP | NOT NULL                     | Required date                |
| `status`              | VARCHAR   | NOT NULL                     | Requirement status           |

---

# 5. Supplier Service and Purchasing Agent Schemas

> **Legacy:** the `purchasing` schema (`suppliers`, `supplier_items`, `purchase_requisitions`) was created by legacy migrations. It is left untouched and is **not** used by the new Purchasing Agent.

Cross-schema references below are **logical references** (UUIDs without a database FK). The owning module validates on write that each reference points to an existing record, through the owning service's interface.

## 5.1 `supplier_service` schema

Owned by the **Supplier Service** (deterministic supplier master data). Purchasing reads it only through the Supplier Service interface and never writes to it.

### `supplier_service.items`

The Supplier Service's catalogue of procurable items. In standalone mode an item is valid for Purchasing only if it exists here. It maps to `core.items` during integration; the legacy `core` schema is not written by this module.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Item ID |
| `sku` | VARCHAR | NOT NULL, UNIQUE | Stock keeping unit |
| `name` | VARCHAR | NOT NULL | Item name |
| `unit` | VARCHAR | NOT NULL | Unit of measurement |

### `supplier_service.suppliers`

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Supplier ID |
| `name` | VARCHAR | NOT NULL, UNIQUE | Supplier name (also the final ranking tie-breaker) |
| `contact_info` | JSONB | | Supplier contact information |
| `rating_data` | JSONB | | Supplier evaluation data (not used in ranking) |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | Inactive suppliers are never selected |

### `supplier_service.supplier_items`

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Supplier item ID |
| `supplier_id` | UUID | FK → `supplier_service.suppliers.id`, NOT NULL | Supplier |
| `item_id` | UUID | FK → `supplier_service.items.id`, NOT NULL | Supplied item |
| `lead_time_days` | INTEGER | NOT NULL, CHECK ≥ 0 | Expected lead time |
| `min_order_qty` | DECIMAL | NOT NULL, CHECK > 0 | Minimum order quantity (MOQ) |
| `available_qty` | DECIMAL | NOT NULL, CHECK ≥ 0 | Available quantity |

UNIQUE (`supplier_id`, `item_id`).

## 5.2 `purchasing_agent` schema

Owned by the **Purchasing Agent** (`backend/app/purchasing_agent/`, own declarative base, like Sales' `sales_agent`).

### `purchasing_agent.purchasing_contracts`

Standing unit-price contracts for supplier-item pairs.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Purchasing Contract ID |
| `supplier_id` | UUID | NOT NULL, logical ref → `supplier_service.suppliers.id` | Supplier covered |
| `item_id` | UUID | NOT NULL, logical ref → `supplier_service.items.id` | Item covered |
| `unit_price` | NUMERIC(12,2) | NOT NULL, CHECK (`unit_price` > 0) | Price per unit in INR |
| `valid_from` | DATE | NOT NULL | First valid date |
| `valid_until` | DATE | NULL = open-ended, CHECK ≥ `valid_from` | Last valid date |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | Whether the contract is active |
| `created_at` | TIMESTAMPTZ | NOT NULL | Creation time |

Rules:
- A pair may have several contracts over time (historical and future).
- Creating or modifying an active contract whose validity overlaps another active contract for the same pair is **rejected** by the contract write service (per-pair lock), not by a database constraint, so bad seeded data stays testable.
- A price is usable only when exactly one active contract covers the **selection date**. None → **Not Registered** (never zero, never estimated). More than one (data error) → the pair is **excluded from selection** with reason `contract_overlap`, shown in the options and audit; other suppliers are still evaluated.

### `purchasing_agent.procurement_requests`

One row per **Procurement Request**. It also holds the combined **Procurement Agreement** outcome.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Procurement Request ID (correlation ID for its Legs) |
| `item_id` | UUID | NOT NULL, logical ref → `supplier_service.items.id` | Item to procure |
| `shortage_quantity` | DECIMAL | NOT NULL, CHECK > 0 | Quantity to cover (whole units; 500.0 is accepted as 500, fractions are refused) |
| `required_date` | DATE | NOT NULL | Requester's deadline (never changed by Purchasing) |
| `priority` | INTEGER | NOT NULL | Request priority (ordering/urgency only, not supplier ranking) |
| `requested_by` | VARCHAR | NOT NULL | Requester reference (test API now; the requesting agent is decided at integration) |
| `request_ref` | VARCHAR | NOT NULL, UNIQUE | Requester's idempotency key; a repeat with the same item, quantity, date and priority returns the existing request; different data is refused (409 Conflict) |
| `status` | VARCHAR | NOT NULL | See statuses below |
| `split_type` | VARCHAR | NULL until selection | `SINGLE`, `NECESSARY_SPLIT`, `COST_SAVING_SPLIT` |
| `cost_ranking_available` | BOOLEAN | NULL until selection | FALSE when the selection relied on a Not Registered supplier |
| `constrained_quantity` | DECIMAL | NULL unless FAILED | Quantity that could have been covered |
| `status_reason` | TEXT | | Reason for `FAILED` / `APPROVAL_REJECTED` |
| `decided_at` | TIMESTAMPTZ | | Approval / rejection time |
| `created_at` | TIMESTAMPTZ | NOT NULL | Creation time |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Last update |

Statuses: `RECEIVED` → `NEGOTIATING` → `AGREEMENT_PROPOSED` → `COMMITTED` or `APPROVAL_REJECTED`. `FAILED` from `RECEIVED` (no feasible option) or `NEGOTIATING` (a Leg failed, or no valid allocation remains).

### `purchasing_agent.purchase_requisitions`

**Each row represents one Leg**: one supplier's part of a Procurement Request. A single-supplier procurement has exactly one row.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Requisition (Leg) ID |
| `procurement_request_id` | UUID | FK → `purchasing_agent.procurement_requests.id`, NOT NULL | Parent request |
| `supplier_id` | UUID | NOT NULL, logical ref → `supplier_service.suppliers.id` | Selected supplier |
| `purchasing_contract_id` | UUID | FK → `purchasing_agent.purchasing_contracts.id`, NULL = Not Registered | Contract used at selection |
| `unit_price_at_selection` | NUMERIC(12,2) | NULL = Not Registered | Price snapshot used for the decision |
| `allocated_quantity` | DECIMAL | NOT NULL | Current quantity Purchasing asks of this supplier (changes on reallocation) |
| `quantity_cap` | DECIMAL | NULL | Supplier's counter-offered maximum for this procurement |
| `agreed_quantity` | DECIMAL | NULL until AGREED | Leg Agreement quantity |
| `agreed_delivery_date` | DATE | NULL until AGREED | Leg Agreement delivery date |
| `negotiation_session_id` | UUID | UNIQUE, NOT NULL, logical ref → `negotiation_engine.negotiation_sessions.id` | Supplier negotiation for this Leg |
| `status` | VARCHAR | NOT NULL | `PENDING`, `AGREED`, `FAILED`, `ABORTED`, `COMMITTED` |
| `status_reason` | TEXT | | e.g. `round_limit_exceeded`, `supplier_rejected`, `timeout`, `unclear_response`, `no_longer_needed`, `split_failed`, `approval_rejected`, `manually_aborted` |
| `created_at` | TIMESTAMPTZ | NOT NULL | Creation time |
| `updated_at` | TIMESTAMPTZ | NOT NULL | Last update |

CHECKs (migration `004`): `allocated_quantity` > 0; `purchasing_contract_id` and `unit_price_at_selection` are both NULL (Not Registered) or both set.

A Leg's status is Purchasing's business status, separate from the Engine session status.

**Effective availability** of a supplier-item for a request = `supplier_service.supplier_items.available_qty` − quantity held by **other** requests' `PENDING`, `AGREED` and `COMMITTED` Legs for that supplier-item (`allocated_quantity` while PENDING, `agreed_quantity` once AGREED/COMMITTED), never below 0. `FAILED` and `ABORTED` Legs release their hold; overdue PENDING Legs are timed out first. Allocations for the same supplier-item are processed one at a time under a PostgreSQL transaction-scoped advisory lock (no lock is held during LLM calls), so two procurements never double-book a supplier.

Committed Legs of a `COMMITTED` request are the scheduled receipts (one per Leg). An `AGREED` Leg that is not committed never counts as a scheduled receipt.

### `purchasing_agent.decision_audit`

Purchasing's own decision audit (same shape as `audit.decision_audit`, no cross-schema FK).

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Audit ID |
| `procurement_request_id` | UUID | FK → `purchasing_agent.procurement_requests.id`, NULL allowed | Related request |
| `decision_type` | VARCHAR | NOT NULL | e.g. `SUPPLIER_SELECTION`, `REALLOCATION`, `RESPONSE_VALIDATION`, `RESPONSE_DEADLINE`, `APPROVAL`, `MANUAL_ABORT` |
| `context` | JSONB | NOT NULL | Options/combinations considered, prices or `Not Registered`, exclusions |
| `decision` | JSONB | NOT NULL | Deterministic decision |
| `reasoning_summary` | TEXT | NOT NULL | Deterministic rationale |
| `llm_explanation` | TEXT | NULL | LLM explanation, stored as explanation, never as evidence |
| `created_at` | TIMESTAMPTZ | NOT NULL | Decision time |

```text
supplier_service.suppliers ──< supplier_service.supplier_items
        : (logical refs)
purchasing_agent.purchasing_contracts
        :
purchasing_agent.procurement_requests ──< purchasing_agent.purchase_requisitions (Legs) .. negotiation_engine.negotiation_sessions
        └──< purchasing_agent.decision_audit
```

---

# 6. Production Schema

> **Legacy / not built:** no migration creates this schema (`app/models/production.py` is empty). There is no separate Production agent (decided 2026-10-18, `DECISIONS.md` O-9); production orders and scheduling belong to Planning (RD-3, `planning_agent/4_planning_agent_database.md` on `origin/master`).

## `production.machines`

Stores manufacturing machines/resources.

| Column             | Type    | Constraint | Description    |
| ------------------ | ------- | ---------- | -------------- |
| `id`               | UUID    | PK         | Machine ID     |
| `machine_code`     | VARCHAR | UNIQUE     | Machine code   |
| `name`             | VARCHAR | NOT NULL   | Machine name   |
| `capacity_per_day` | DECIMAL |            | Daily capacity |
| `status`           | VARCHAR |            | Machine status |

---

## `production.production_orders`

Stores production orders.

| Column     | Type    | Constraint                      | Description         |
| ---------- | ------- | ------------------------------- | ------------------- |
| `id`       | UUID    | PK                              | Production order ID |
| `order_id` | UUID    | FK → `sales.customer_orders.id` | Customer order      |
| `item_id`  | UUID    | FK → `core.items.id`            | Product             |
| `quantity` | DECIMAL | NOT NULL                        | Production quantity |
| `priority` | INTEGER | NOT NULL                        | Production priority |
| `status`   | VARCHAR |                                 | Production status   |

---

## `production.production_schedule`

Stores machine-level production schedules.

| Column                | Type      | Constraint                             | Description      |
| --------------------- | --------- | -------------------------------------- | ---------------- |
| `id`                  | UUID      | PK                                     | Schedule ID      |
| `production_order_id` | UUID      | FK → `production.production_orders.id` | Production order |
| `machine_id`          | UUID      | FK → `production.machines.id`          | Machine          |
| `start_time`          | TIMESTAMP | NOT NULL                               | Start time       |
| `end_time`            | TIMESTAMP | NOT NULL                               | End time         |
| `status`              | VARCHAR   |                                        | Schedule status  |

---

# 7. Agent Schema

## `agent.agents`

Stores autonomous agents participating in the MRPII system.

| Column       | Type      | Constraint | Description      |
| ------------ | --------- | ---------- | ---------------- |
| `id`         | UUID      | PK         | Agent ID         |
| `agent_code` | VARCHAR   | UNIQUE     | Agent identifier |
| `agent_type` | VARCHAR   | NOT NULL   | Agent type       |
| `name`       | VARCHAR   | NOT NULL   | Agent name       |
| `status`     | VARCHAR   |            | Agent status     |
| `created_at` | TIMESTAMP |            | Creation time    |

### 25% Agents

```text
PRODUCTION_PLANNING_AGENT
INVENTORY_AGENT
PURCHASING_AGENT
```

---

## `agent.agent_state`

Stores the agent's internal operational and negotiation state.

| Column                   | Type      | Constraint                 | Description                  |
| ------------------------ | --------- | -------------------------- | ---------------------------- |
| `agent_id`               | UUID      | PK, FK → `agent.agents.id` | Agent                        |
| `current_goal`           | JSONB     |                            | Current objective            |
| `preferred_terms`        | JSONB     |                            | Preferred negotiation terms  |
| `reserved_limits`        | JSONB     |                            | Hard/acceptable limits       |
| `initial_proposal`       | JSONB     |                            | Initial proposal             |
| `own_offer_history`      | JSONB     |                            | Agent's previous offers      |
| `opponent_offer_history` | JSONB     |                            | Offers received              |
| `dialogue_history`       | JSONB     |                            | Negotiation dialogue/context |
| `negotiation_rules`      | JSONB     |                            | Rules/policies               |
| `current_task`           | JSONB     |                            | Current task                 |
| `updated_at`             | TIMESTAMP |                            | Last update                  |

> `preferred_terms`, `reserved_limits`, and `initial_proposal` are MRPII-specific adaptations of negotiation inputs such as preferred/reserved/initial values identified in the automated-negotiation literature. For MRPII, these can represent quantity, delivery date, priority, and other relevant terms.

### Important Design Rule

The agent state stores **decision-making and negotiation state**. It should NOT duplicate the complete inventory, supplier, production, or planning databases.

---

# 8. Negotiation Engine Schema

> **Legacy:** the `negotiation` schema was created by legacy migrations. It is left untouched and is **not** used by the new Negotiation Engine.

## `negotiation_engine` schema

Owned by the **Negotiation Engine** (`backend/app/negotiation_engine/`). It holds conversation and protocol state only (sessions, participants, messages, rounds, deadlines) and makes no business decisions. It currently hosts only Purchasing ↔ supplier sessions; agent-to-agent sessions come later via `session_type`.

### `negotiation_engine.negotiation_sessions`

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Session ID |
| `session_type` | VARCHAR | NOT NULL | `PURCHASING_SUPPLIER` (only type now) |
| `status` | VARCHAR | NOT NULL | Engine status (below) |
| `status_reason` | TEXT | | e.g. `round_limit_exceeded`, `supplier_rejected`, `timeout`, `split_failed`, `approval_rejected` |
| `correlation_id` | UUID | NOT NULL | Business correlation (Procurement Request ID) |
| `objective` | JSONB | NOT NULL | What is negotiated (item, quantity, required date); never price |
| `round_count` | INTEGER | NOT NULL, DEFAULT 0 | Rounds used; raised when Purchasing sends an offer or counter-offer (first offer = round 1) |
| `max_rounds` | INTEGER | NOT NULL, DEFAULT 3 | Round limit; CHECK 0 ≤ `round_count` ≤ `max_rounds` |
| `response_deadline` | TIMESTAMPTZ | NULL | Deadline for the pending response; moved by each agent message awaiting a reply; checked lazily on read/act (working default 24h) |
| `started_at` | TIMESTAMPTZ | NOT NULL | Start time |
| `completed_at` | TIMESTAMPTZ | NULL until an end status | Completion time |

Engine statuses (separate from Purchasing's Leg status):
- `OPEN` — negotiation is ongoing.
- `AGREED` — the supplier accepted the terms. `AGREED → OPEN` only when Purchasing explicitly reopens the Leg.
- `REJECTED` — ended without agreement (supplier reject, or `round_limit_exceeded`).
- `TIMED_OUT` — the response deadline passed.
- `CANCELLED` — Purchasing cancelled the session (from `OPEN` or `AGREED`, e.g. a Leg ABORTED `split_failed`). Purchasing's `CANCEL` message is the only message accepted on an `AGREED` session.

One round = one Purchasing offer/counter-offer + the supplier's response. Clarifications do not count as rounds.

### `negotiation_engine.negotiation_participants`

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Participant record |
| `session_id` | UUID | FK → `negotiation_engine.negotiation_sessions.id` | Session |
| `participant_type` | VARCHAR | NOT NULL | `AGENT` or `SUPPLIER` |
| `participant_ref` | VARCHAR | NOT NULL | Agent code or supplier ID; validated to exist on write (no FK) |
| `role` | VARCHAR | NOT NULL | `INITIATOR` or `RESPONDENT` |
| `joined_at` | TIMESTAMPTZ | NOT NULL | Join time |

UNIQUE (`session_id`, `participant_type`, `participant_ref`).

### `negotiation_engine.negotiation_messages`

Free-text chat messages plus the structured terms behind them. There is no separate offers table: offer terms are stored on the message.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Row ID |
| `session_id` | UUID | FK → `negotiation_engine.negotiation_sessions.id` | Session |
| `message_id` | UUID | UNIQUE (across all sessions), NOT NULL | Sender-supplied ID; a duplicate in the same session is ignored, one already used in another session is refused (409) |
| `sequence_number` | INTEGER | NOT NULL | Order within session; UNIQUE (`session_id`, `sequence_number`) |
| `round_number` | INTEGER | NOT NULL | Round the message belongs to |
| `sender_type` | VARCHAR | NOT NULL | `AGENT` or `SUPPLIER` |
| `sender_ref` | VARCHAR | NOT NULL | Sender reference |
| `message_type` | VARCHAR | NOT NULL | See below |
| `text` | TEXT | NOT NULL | Chat text shown in the WhatsApp-like UI. An agent message awaiting a reply is stored with template text; the LLM wording may replace it later, only while it is still the session's latest message (terms never change) |
| `terms` | JSONB | NULL | Structured terms: `quantity`, `delivery_date` (never price). A supplier COUNTER_OFFER read by the LLM may have one of them `null` (not stated; never invented) |
| `interpretation_source` | VARCHAR | NULL | Supplier messages only: `LLM` or `FALLBACK_PARSER` |
| `causation_id` | UUID | NULL | `message_id` this message responds to: a supplier reply → the offer or clarification it answers; Purchasing's messages caused by a reply (also on other Legs, e.g. a revised offer or a `split_failed` CANCEL) → that reply; a timeout `CONFIRMATION` → the unanswered offer; a `CANCEL` from abort or approval-reject → the Leg's latest message |
| `created_at` | TIMESTAMPTZ | NOT NULL | Creation time |

Message types:
- Purchasing: `OFFER`, `COUNTER_OFFER`, `CLARIFICATION_REQUEST`, `CANCEL`, `CONFIRMATION` (closes the negotiation from Purchasing's side after agreement or Leg failure and echoes its reading of the last reply; no round; added by migration `005`).
- Supplier (interpreted from free text, then validated by Purchasing): `ACCEPT`, `COUNTER_OFFER`, `REJECT`, `UNCLEAR`.

Purchasing's outbound terms are computed deterministically; the LLM writes only the `text` (predefined template on failure). For supplier messages, the LLM (or the fallback parser) extracts action and terms; Purchasing validates them and echoes its interpretation in its next message.

---

# 9. Simulation Schema

The Simulation module provides the **What-If environment** for testing disruptions without directly representing a real-world event.

## `simulation.simulation_scenarios`

Stores What-If scenarios.

| Column          | Type      | Constraint | Description            |
| --------------- | --------- | ---------- | ---------------------- |
| `id`            | UUID      | PK         | Scenario ID            |
| `name`          | VARCHAR   | NOT NULL   | Scenario name          |
| `description`   | TEXT      | NOT NULL   | Scenario description   |
| `configuration` | JSONB     | NOT NULL   | Scenario configuration |
| `created_at`    | TIMESTAMP |            | Creation time          |

---

## `simulation.simulation_events`

Stores disruptions/events triggered inside a scenario.

| Column        | Type      | Constraint                                | Description          |
| ------------- | --------- | ----------------------------------------- | -------------------- |
| `id`          | UUID      | PK                                        | Event ID             |
| `scenario_id` | UUID      | FK → `simulation.simulation_scenarios.id` | Scenario             |
| `event_type`  | VARCHAR   | NOT NULL                                  | Event type           |
| `event_time`  | TIMESTAMP | NOT NULL                                  | Simulated event time |
| `parameters`  | JSONB     | NOT NULL                                  | Event parameters     |
| `status`      | VARCHAR   |                                           | Event status         |

### Example Events

```text
SUPPLIER_DELAY
SUDDEN_DEMAND_INCREASE
SUPPLIER_QUANTITY_REDUCTION
NEW_CUSTOMER_ORDER
CUSTOMER_DUE_DATE_CHANGE
INVENTORY_RESERVATION
MULTI_DISRUPTIONS
```

### Simulation Flow

```text
Simulation Scenario
        │
        ↓
Simulation Event
        │
        ↓
Change system condition
        │
        ↓
Agents detect/re-evaluate
        │
        ↓
Communication + Negotiation
        │
        ↓
Revised Plan
```

---

# 10. Audit Schema

## `audit.decision_audit`

Stores structured records of agent decisions for traceability.

| Column              | Type      | Constraint             | Description                |
| ------------------- | --------- | ---------------------- | -------------------------- |
| `id`                | UUID      | PK                     | Audit ID                   |
| `agent_id`          | UUID      | FK → `agent.agents.id` | Agent                      |
| `decision_type`     | VARCHAR   | NOT NULL               | Type of decision           |
| `context`           | JSONB     | NOT NULL               | Relevant decision context  |
| `decision`          | JSONB     | NOT NULL               | Final decision             |
| `reasoning_summary` | TEXT      | NOT NULL               | Concise decision rationale |
| `created_at`        | TIMESTAMP |                        | Decision time              |

> Store a concise structured rationale rather than hidden chain-of-thought.

The Purchasing Agent writes to its own `purchasing_agent.decision_audit` instead (section 5.2), as Sales uses its own audit log.

---

**Design principle:** PostgreSQL remains the shared source of truth, but the **agents own their goals, constraints, preferences, negotiation state, and decisions**. The deterministic MRPII calculations and database operations remain outside the agents, accessed through domain services/tools.