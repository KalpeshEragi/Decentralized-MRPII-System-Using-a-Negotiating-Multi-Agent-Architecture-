# backend

FastAPI backend: a modular monolith holding the deterministic MRPII core, services, negotiation engine,
LLM client, the three agents (as A2A endpoints), simulation and API (roadmap Section 3).

## What exists now

| Folder | Content | Phase |
| --- | --- | --- |
| `app/schemas/`, `app/mrpii/`, `app/negotiation/`, `app/llm/`, `app/data/x1_fixture.py` | Pure deterministic core (C1 shapes, finished-goods netting, MPS, MRP, capacity, validation; C4 protocol; LLM proposer layer; X1 fixture). No database. | 1 |
| `app/models/`, `alembic/`, `app/data/seed_data.py` | 24-table ORM, migrations 001 and 002, X1 seed / reset. | 2 |
| `app/services/`, `app/api/`, `app/core/` | Persistence services, orders / plans / negotiations API with the C5 error format, A2A transport spike (three endpoints), Agents SDK + Ollama spike (`app/llm/agents_spike.py`). | 2 |
| `scripts/` | Manual verification scripts (see its README). | 1-2 |
| `tests/` | Written for Phases 1-2; see its README. Not all have been run. | 0-2 |

Start the API: `uvicorn app.main:app` from `backend/` (needs `DATABASE_URL` for anything but `/health` and the agent cards).

## Scaffold folders (empty placeholder files, filled in later phases)

| Folder | Planned content | Phase |
| --- | --- | --- |
| `app/agents/` | `base`, `planning/`, `inventory/`, `purchasing/` | 3-4 |
| `app/simulation/` | Scenario Manager and event handlers | 4 |

## Run tests

```bash
cd backend
.venv/Scripts/python -m pytest
```
