# backend/alembic

Alembic migrations (001–002 are the old 25% tables, retired in Phase 2; 003 Sales Agent; 004 onward the six-agent design). Hand-written, so they do not depend on the ORM.
The database URL is `DATABASE_URL` (repository-root `.env`), or `-x url=...`.

| Revision | Content |
| --- | --- |
| `001` | Schemas (all nine), `agent.agents`, then `core`, `sales`, `inventory`, `planning`, `purchasing`, `agent.agent_state`. |
| `002` | `negotiation.*` (5 tables), `simulation.*` (2), `audit.decision_audit`. References `agent.agents` from 001. |
| `003` | `sales_agent.*` (9 tables of the Sales Agent). |
| `004` | Platform foundation (step 1): `core.items.sourcing` / `space_per_unit`, `core.routings`; `events.events`, `events.event_deliveries`; `simulation.clock`, `simulation.settings`; `observability.llm_calls`. |
| `005` | Negotiation v2 (step 3): `negotiation.sessions` (with `case_id`, NG-5 partial unique index), `negotiation.messages` (inbox queue), `negotiation.outbox`. |
| `006` | Retires the old 25% tables (sales, old inventory/planning/purchasing, agent, audit, old negotiation and simulation tables); `core` stays. Not reversible. |
| `007` | Owner agents' tables (Inventory, HR, Warehouse), created from their ORM models. |

Run from `backend/`:

```bash
alembic upgrade head
alembic downgrade base
```

`downgrade base` drops every table and schema created here. Load the X1 baseline afterwards with `python -m app.data.seed_data`
(this also resets an existing database to the baseline).
