# Decentralized MRPII using Multi-Agent Systems & LLMs

A manufacturing planning (MRPII) research prototype. Six autonomous domain agents (Sales, Planning, Inventory,
Purchasing, Warehouse, HR; no separate Production agent) own their data and decisions and coordinate by negotiation
and published events instead of one central planner. Business calculations stay deterministic; a shared local LLM
(Ollama) only helps with wording and reasoning.

**Status (branch `purchasing-agent`, 2026-10-18):** Sales Agent implemented; Purchasing Agent implemented standalone
(with the Supplier Service, supplier test chat and Negotiation Engine). Other agents and multi-agent integration are
not built. Details: `dev_docs/PROJECT_STATUS.md`.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI backend (Python): `app/sales_agent/`, `app/purchasing_agent/`, `app/supplier_service/`, `app/negotiation_engine/`, shared `app/core/`, `app/llm/`; older modules are legacy. |
| `frontend/` | Legacy Next.js demo console for the old SmartPhone X1 flow. |
| `dev_docs/` | Specs, decisions, status and per-agent design notes. Start at `dev_docs/README.md`. |
| `.scratch/` | Feature specs and tickets (e.g. `.scratch/purchasing-agent/`). |
| `GLOSSARY.md` | Domain terms. |
| `CLAUDE.md` | Rules for Claude Code sessions. |

## Start here

1. `dev_docs/README.md`: doc index and what is built.
2. `dev_docs/PROJECT_STATUS.md`: what is actually in the repository.
3. `dev_docs/DECISIONS.md` and `dev_docs/adr/`: confirmed and open decisions.
4. Agent notes: `dev_docs/sales_agent/`, `dev_docs/purchasing_agent/`, `dev_docs/supplier/`.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m app.purchasing_agent.seed          # optional: Purchasing fixture (resets its three schemas)
.venv/Scripts/python -m uvicorn app.main:app
```

Copy `.env.example` to `.env` in the repository root and fill in `DATABASE_URL` (Neon PostgreSQL),
`TEST_DATABASE_URL` (DB tests; wiped by test resets) and optionally the Ollama settings. Supplier chat:
`http://localhost:8000/purchasing/test-channel`.

Tests: `.venv/Scripts/python -m pytest` from `backend/`. DB tests need `TEST_DATABASE_URL`; run one suite at a time
(parallel runs on the shared test DB interfere).
