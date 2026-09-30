# backend/alembic

Alembic migrations for the C2 subset (25% tables only, D7). Hand-written, so they do not depend on the ORM.
The database URL is `DATABASE_URL` (repository-root `.env`), or `-x url=...`.

| Revision | Content |
| --- | --- |
| `001` | Schemas (all nine), `agent.agents`, then `core`, `sales`, `inventory`, `planning`, `purchasing`, `agent.agent_state`. |
| `002` | `negotiation.*` (5 tables), `simulation.*` (2), `audit.decision_audit`. References `agent.agents` from 001. |

Run from `backend/`:

```bash
alembic upgrade head
alembic downgrade base
```

`downgrade base` drops every table and schema created here. Load the X1 baseline afterwards with `python -m app.data.seed_data`
(this also resets an existing database to the baseline).
