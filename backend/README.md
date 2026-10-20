# backend

FastAPI backend of the six-agent prototype: one program (HA-1) holding the agents, the shared infrastructure (event
channel, negotiation layer, work runner, simulator) and the pure MRPII calculations. Design: `../dev_docs/`.

| Folder | Content |
| --- | --- |
| `app/core/` | Settings, database, RFC 9457 errors, door keys, the shared work runner and its registrations, owner table shapes, HTTP calls between doors. |
| `app/events/` | Publish-subscribe event channel. |
| `app/negotiation/` | Private negotiation: envelope, state machine, outbox/inbox, A2A endpoints. |
| `app/mrpii/` | Pure calculations: multi-level MRP, hours scheduling, ATP, ranking. |
| `app/simulation/` | The simulator: clock, factory settings, day cycle with Play / Pause, simulated shop floor and suppliers, triggers. |
| `app/observer/` | Read-only views for the demo frontend: orders, one order's story, timeline, factory state. |
| `app/observability/` | AI-call log table. |
| `app/models/` | Shared reference data (`core`: items, BOM, routings). |
| `app/sales_agent/`, `app/planning_agent/`, `app/inventory_agent/`, `app/hr_agent/`, `app/warehouse_agent/` | The agents on the shared platform (events, negotiation v2, work runner). |
| `app/purchasing_agent/` | Purchasing Agent (another contributor), standalone for now: schema `purchasing_agent`, migrations `009`, `010` (its `README.md`, `dev_docs/purchasing_agent/`). |
| `app/supplier_service/` | Simulated supplier data, not an agent (schema `supplier_service`, `dev_docs/supplier/`). |
| `app/negotiation_engine/` | Purchasing's supplier-negotiation state (schema `negotiation_engine`); separate from `app/negotiation/` (agent-to-agent negotiation). |
| `app/llm/` | Ollama client and structured-output parsing. |
| `alembic/` | Migrations (see its README). |
| `tests/` | See its README. |

Start the API from `backend/`: `uvicorn app.main:app` (needs `DATABASE_URL`; background workers start with it unless
`BACKGROUND_WORKERS=false`; agents send A2A messages to `A2A_BASE_URL`, which must point at this running server).

Run tests: `.venv/Scripts/python -m pytest` (database tests need `TEST_DATABASE_URL`).
