# backend

FastAPI backend: a modular monolith holding the deterministic MRPII core, services, negotiation engine,
LLM client, the three agents (as A2A endpoints), simulation and API (roadmap Section 3).

## What exists now

| Folder | Content | Phase |
| --- | --- | --- |
| `app/schemas/`, `app/mrpii/`, `app/negotiation/`, `app/llm/`, `app/data/x1_fixture.py` | Pure deterministic core (C1 shapes, finished-goods netting, MPS, MRP, capacity, validation; C4 protocol; LLM proposer layer; X1 fixture). No database. | 1 |
| `app/models/`, `alembic/`, `app/data/seed_data.py` | 24-table ORM, migrations 001 and 002, X1 seed / reset. | 2 |
| `app/services/`, `app/api/`, `app/core/` | Persistence services, orders / plans / negotiations API with the C5 error format, A2A transport spike (three endpoints), Agents SDK + Ollama spike (`app/llm/agents_spike.py`). | 2 |
| `app/agents/`, `app/api/agents.py`, `app/core/a2a_client.py`, `app/services/requisition_service.py`, `app/services/supplier_interface_service.py` | Planning, Inventory and Purchasing Agents (C6 state, C7 audit, LLM proposer with deterministic validation); Inventory → Purchasing negotiation over the A2A endpoints; supplier interface service; agents API. | 3 |
| `scripts/` | Manual verification scripts (see its README). | 1-3 |
| `tests/` | Written for Phases 1-3; see its README. Not all have been run (Phase 3 tests have not been run). | 0-3 |

Start the API: `uvicorn app.main:app` from `backend/` (needs `DATABASE_URL` for anything but `/health` and the agent cards; the agents send A2A messages to `A2A_BASE_URL`, so
it must point at this running server; Ollama is optional: without it Purchasing's deterministic policy decides).

## Scaffold folders (empty placeholder files, filled in later phases)

| Folder | Planned content | Phase |
| --- | --- | --- |
| `app/simulation/` | Scenario Manager and event handlers | 4 |

## Run tests

```bash
cd backend
.venv/Scripts/python -m pytest
```
