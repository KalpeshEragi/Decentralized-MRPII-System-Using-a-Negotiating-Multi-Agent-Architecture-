# C2 — Database Schema Subset and Migration Order

## Status

**Status:** CONFIRMED

**Owner:** Project developer

**Reviewed:** 2026-09-30 (see Review)

## Purpose

Defines which tables of `dev_docs/implementation_25%/database_schema.md` are built for the 25% milestone
and the order in which their migrations are created and applied.

## Scope

- The 25% table subset, grouped by migration.
- Tables that are explicitly not built.
- Database conventions shared by all tables.
- Migration ownership and order.

**Implemented in (Phase 2, not yet run against a live database):** `backend/app/models/` (SQLAlchemy ORM), `backend/alembic/` (migrations 001 and 002), seed loader in `backend/app/data/`.

## Does Not Define

- Column-level definitions. `database_schema.md` is the source for columns, types and constraints; this contract does not duplicate them.
- In-memory domain shapes (C1).
- JSONB content: offer terms, session objective and message payload (C4), agent state (C6), audit context and decision (C7).
- Service function signatures (C3).
- Approval state and the planning-attempt counter (C8).
- Simulation event parameters (C9).
- Seed values (D1 fixture spec, P0-10).

## Specification

Items marked **PENDING** must not be guessed during implementation. See `docs/DECISIONS.md` for each `P0-xx` item.

### 1. Conventions

| Topic | Rule | Source |
| --- | --- | --- |
| Database | One PostgreSQL database hosted on Neon, reached through the configurable `DATABASE_URL`. No local Postgres container. | P0-03 |
| ORM / migrations | SQLAlchemy + Alembic. | `dev_docs/DECISIONS.md` (Stack) |
| Logical schemas | `core`, `sales`, `inventory`, `planning`, `purchasing`, `agent`, `negotiation`, `simulation`, `audit`. | `database_schema.md` |
| Primary keys | UUID. | `database_schema.md` |
| Quantities | `DECIMAL`. | `database_schema.md` |
| Priority | Integer 1–5, `1` = highest. | P0-15 |
| Cost / price | No cost or price columns. | `dev_docs/DECISIONS.md` (Cost/price) |
| Access | Agents never access tables directly; all reads and writes go through services. | `system_spec.md` §6, roadmap §6 |
| Ownership | Table ownership per `system_spec.md` §6 (Database Ownership). | `system_spec.md` §6 |

### 2. Migration 001

Tables, as defined in `database_schema.md`:

| Schema | Tables |
| --- | --- |
| `core` | `items`, `bom`, `bom_items` |
| `sales` | `customers`, `customer_orders`, `customer_order_items` |
| `inventory` | `warehouses`, `inventory_balance`, `inventory_reservations` |
| `planning` | `mps_plans`, `mrp_requirements` |
| `purchasing` | `suppliers`, `supplier_items`, `purchase_requisitions` |
| `agent` | `agents`, `agent_state` |

Also delivered with 001: the seed loader for the SmartPhone X1 fixture (**PENDING D1 / P0-10** for values).

`planning.mrp_requirements` includes `scheduled_receipts` and `projected_available_quantity`, and
`available_inventory` holds C1 `available_quantity` (P0-13, already in `database_schema.md`).

`agent.agent_state` has no extra policy columns. Policy items live in `negotiation_rules.policy` (P0-09).

### 3. Migration 002

Tables, as defined in `database_schema.md`:

| Schema | Tables |
| --- | --- |
| `negotiation` | `negotiation_sessions`, `negotiation_participants`, `negotiation_messages`, `negotiation_offers`, `negotiation_agreements` |
| `simulation` | `simulation_scenarios`, `simulation_events` |
| `audit` | `decision_audit` |

25% column rules already reflected in `database_schema.md`:

- `negotiation_sessions.completed_at` is nullable and set only when the session reaches an end status (P0-04).
- `negotiation_offers.valid_until` is nullable; set from the round/session deadline if timeouts are adopted (P0-06, D9).
- `negotiation_sessions.status` holds the session statuses; `negotiation_messages.message_type` holds the message types (P0-05, C4).

### 4. Not Built in the 25%

| Tables | Reason | Source |
| --- | --- | --- |
| `purchasing.purchase_orders`, `purchasing.purchase_order_items` | The negotiation agreement is the purchasing outcome. | `dev_docs/DECISIONS.md` (Purchase orders) |
| `production.machines`, `production.production_orders`, `production.production_schedule` | No Production Agent in the 25%. Capacity, if kept, is a fixture/config value (P0-14). | Roadmap §5, `system_spec.md` §6 |

### 5. Migration Order

1. Migration 001 is created and applied first.
2. Migration 002 is created after 001, because negotiation and audit tables reference `agent.agents`.
3. Only one migration is created at a time.
4. Integration check: both migrations apply to a clean database and the seed loads.

Source: roadmap Phase 2.

### 6. Open Items

- **Decided (P2-01):** Alembic covers the 25% tables only (D7); production lead time and `capacity_per_day` are fixture/config values (P0-11, P0-14); `planned_start`, `planned_end`, `mrp_requirements.required_by` and `purchase_requisitions.required_by` are `DATE` (P0-16); inventory is aggregated per item (P0-10); committed agreements are read as scheduled receipts (P0-12); DB tests use `TEST_DATABASE_URL`.
- **PENDING C8:** where approval state and the planning-attempt counter are stored.
- **To confirm:** which values each `VARCHAR` status column holds (for example C1 `OrderStatus`, `PlanStatus`, `RequirementStatus`), and the values of `negotiation_sessions.negotiation_type` and `negotiation_participants.role` (C4).
- **Resolved (P1-04):** `negotiation_sessions.deadline` stays `NOT NULL` and holds the shortage's required-by date (validation only, no expiry); `negotiation_offers.valid_until` stays `NULL`.
- **Decided (P2-01):** `negotiation_messages.sender_agent_id` / `receiver_agent_id` are nullable and `sender_type` / `receiver_type` are added, because the supplier interface and the approval workflow are not agents. This is a deliberate difference from `database_schema.md`, which still shows the two columns as required foreign keys. Supplier rounds belong to the same Inventory-initiated session (C4 §6).

## Review

**Result: CONFIRMED.** The table subset, excluded tables, conventions and migration order (001, then 002)
agree with `database_schema.md`, `dev_docs/DECISIONS.md` and the roadmap (Phase 2). Neon (P0-03) and no cost/price
columns are stated. The open items in §6 are listed explicitly and stay **PENDING**; they must be answered before the
migration that needs them (Phase 2), not guessed:

- P0-11 and P0-16 storage choices are needed by migration 001.
- `negotiation_sessions.deadline` is settled by P1-04 (required-by date); supplier-message storage (P1-07) is still needed by migration 002.
- Test-database isolation on Neon (P0-03) is needed before DB integration tests (Phase 2).
