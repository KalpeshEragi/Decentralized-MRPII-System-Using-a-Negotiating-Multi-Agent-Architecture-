# Decentralized MRPII using Multi-Agent Systems & LLMs

A research prototype of a simulated MRPII manufacturing environment run by six autonomous agents — Sales, Planning,
Inventory, Purchasing, Warehouse and HR. Agents share facts through publish–subscribe events and negotiate privately
when they need to agree. Business calculations stay deterministic; a local LLM (Ollama) only assists agent reasoning.

**Status:** Phase 1 (agree on the design) — see `dev_docs/ROADMAP.md`. The backend still holds code from the earlier
three-agent design; it is reviewed in Phase 2. The Sales Agent (`backend/app/sales_agent/`) is the newest code.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI backend (Python). |
| `frontend/` | Next.js frontend. |
| `dev_docs/` | Design docs, decisions and roadmap. |
| `CLAUDE.md` | Rules for Claude Code sessions working on this repository. |

## Start here

1. `dev_docs/ROADMAP.md` — phases and the current phase.
2. `dev_docs/DECISIONS.md` — confirmed and open decisions.
3. `dev_docs/README.md` — index of the design docs.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pytest
```

Copy `.env.example` to `.env` in the repository root and fill in the Neon `DATABASE_URL`
(and `TEST_DATABASE_URL` for the database tests).
