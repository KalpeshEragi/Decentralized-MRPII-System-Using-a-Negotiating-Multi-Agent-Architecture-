# backend/app/models

SQLAlchemy ORM for the C2 subset: 24 tables in 9 PostgreSQL schemas. Importing `app.models` registers all of them on
`Base.metadata`. Columns follow the earlier 25% schema design (doc removed 2026-10-16), with the Phase 2 decisions below.

| File | Tables |
| --- | --- |
| `core.py` | `items`, `bom`, `bom_items` |
| `sales.py` | `customers`, `customer_orders`, `customer_order_items` |
| `inventory.py` | `warehouses`, `inventory_balance`, `inventory_reservations` |
| `planning.py` | `mps_plans`, `mrp_requirements` |
| `purchasing.py` | `suppliers`, `supplier_items`, `purchase_requisitions` (no purchase orders) |
| `agent.py` | `agents`, `agent_state` |
| `negotiation.py` | `negotiation_sessions`, `negotiation_participants`, `negotiation_messages`, `negotiation_offers`, `negotiation_agreements` |
| `simulation.py`, `audit.py` | `simulation_scenarios`, `simulation_events`; `decision_audit` |

Phase 2 decisions applied: `planned_start`, `planned_end` and `required_by` columns are `DATE` (P0-16); TIMESTAMP columns are
`timestamptz`; `negotiation_messages` has `sender_type` / `receiver_type` and nullable agent ids because the supplier
interface and approval workflow are not agents (P1-07); no cost/price columns; production lead time and capacity per day are
not columns (P0-11, P0-14).

`bom.py`, `demand.py`, `machine.py`, `material.py`, `product.py`, `production.py` are empty Phase 0 placeholders and are unused.
