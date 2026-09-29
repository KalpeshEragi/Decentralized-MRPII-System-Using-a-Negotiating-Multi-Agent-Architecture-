# C2 — Database Schema Subset and Migration Order

## Status

**Status:** DRAFT

**Owner:** Dev 2

**Reviewed By:** Pending (Dev 1)

## Purpose

Defines which tables of `dev_docs/implementation_25%/database_schema.md` are built for the 25% milestone
and the order in which their migrations are created and applied.

## Scope

- The 25% table subset, grouped by migration.
- Tables that are explicitly not built.
- Database conventions shared by all tables.
- Migration ownership and order.

**Implemented in (Phase 2):** `backend/app/models/` (SQLAlchemy ORM), `backend/alembic/` (migrations 001 and 002), seed loader in `backend/app/data/`.

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

### 2. Migration 001 — Dev 2

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

### 3. Migration 002 — Dev 1

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

1. Migration 001 is created and merged first (Dev 2).
2. Migration 002 is created after 001 is merged (Dev 1), because negotiation and audit tables reference `agent.agents`. Dev 1 may write the ORM models before that.
3. Only one migration is created at a time, by the developer whose tables it holds.
4. Integration check: both migrations apply to a clean database and the seed loads.

Source: roadmap Phase 2.

### 6. Open Items

- **PENDING D7:** Alembic covers the 25% tables only (roadmap recommendation, not yet confirmed).
- **PENDING P0-11:** storage of the per-product production lead time (`core.items` column or fixture/config value).
- **PENDING P0-16:** mapping of day-bucket dates to columns (`DATE` or midnight UTC `TIMESTAMP`) for `mps_plans.planned_start`, `mps_plans.planned_end`, `mrp_requirements.required_by`, `purchase_requisitions.required_by`.
- **PENDING P0-12:** read path from committed `negotiation_agreements` to scheduled receipts (with C4).
- **PENDING P0-03:** how tests get an isolated database (Phase 2).
- **PENDING P0-10:** whether inventory positions are per warehouse or aggregated (affects seed and queries).
- **PENDING C8:** where approval state and the planning-attempt counter are stored.
- **To confirm:** which values each `VARCHAR` status column holds (for example C1 `OrderStatus`, `PlanStatus`, `RequirementStatus`), and the values of `negotiation_sessions.negotiation_type` and `negotiation_participants.role` (C4).
- **Discrepancy to resolve:** `negotiation_sessions.deadline` is `NOT NULL`, but timeout values are still open (D9). Compare P0-06.
- **Discrepancy to resolve:** `negotiation_messages.sender_agent_id` / `receiver_agent_id` reference `agent.agents`, but the supplier communication interface is not an agent. How supplier-side messages are stored is not defined (see C4).
