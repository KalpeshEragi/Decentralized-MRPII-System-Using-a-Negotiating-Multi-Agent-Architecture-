# backend

FastAPI backend: a modular monolith holding the deterministic MRPII core, services, negotiation engine,
LLM client, the three agents (as A2A endpoints), simulation and API (roadmap Section 6).

## What exists now (Phase 0)

| File / folder | Purpose |
| --- | --- |
| `requirements.txt` | Pinned direct dependencies (FastAPI, OpenAI Agents SDK, A2A SDK, SQLAlchemy, Alembic, psycopg, pytest). Coordination file. |
| `pytest.ini` | Runs `tests/` with `backend/` on the import path, so tests import `app.…`. |
| `app/core/` | Settings (`config.py`). See its README. |
| `tests/` | Test suite. See its README. |

## Scaffold folders (empty placeholder files, filled in later phases)

| Folder | Planned content | Phase |
| --- | --- | --- |
| `app/schemas/` | Shared Pydantic contracts (C1, C4) | 1 |
| `app/mrpii/` | Pure deterministic MPS / BOM / MRP / validation | 1 |
| `app/negotiation/` | Protocol state machine | 1 |
| `app/llm/` | Ollama client, structured-output validation | 1 |
| `app/data/` | SmartPhone X1 fixtures (D1) | 1 |
| `app/models/` | SQLAlchemy ORM | 2 |
| `app/services/`, `app/api/` | Business services and routers | 3 |
| `app/agents/` | `base`, `planning/`, `inventory/`, `purchasing/` | 4–5 |
| `app/simulation/` | Scenario Manager and event handlers | 6 |

Each folder gets its own README when it gets real code.

## Run tests

```bash
cd backend
.venv/Scripts/python -m pytest
```
