# Decentralized MRPII using Multi-Agent Systems & LLMs

A manufacturing planning (MRPII) system in which three autonomous agents — Production Planning,
Inventory and Purchasing — negotiate over A2A to turn a customer order into a feasible plan.
Business calculations stay deterministic; an LLM (local Ollama) only assists agent reasoning.

**Status:** Phase 0 (architecture and contracts). No application logic yet — see `dev_docs/PROJECT_STATUS.md`.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI backend (Python). Scaffold and configuration only so far. |
| `frontend/` | Next.js frontend. Not started (Phase 2). |
| `docs/` | Shared contracts between the two developers and coordination records. |
| `dev_docs/` | Finalized specifications, decisions, status, and the two-developer roadmap. |
| `CLAUDE.md` | Rules for Claude Code sessions working on this repository. |

## Start here

1. `dev_docs/implementation_25%/two_developer_roadmap.md` — phases, who does what, workflow.
2. `dev_docs/DECISIONS.md` — confirmed decisions.
3. `dev_docs/implementation_25%/system_spec.md` and `scenarios.md` — what the 25% milestone must do.
4. `docs/contracts/` — shared data and interface contracts.

## Setup (current baseline)

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pytest
```

Copy `.env.example` to `.env` in the repository root and fill in the Neon `DATABASE_URL`
(not needed yet: nothing connects to the database before Phase 2).
