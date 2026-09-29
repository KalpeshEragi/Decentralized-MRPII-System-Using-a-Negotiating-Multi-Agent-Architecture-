# Decentralized MRPII — Project Status

Snapshot from a read-only inspection of the repository (no application files were changed). Graphify is not installed or configured, so it was not used.

## Current implementation state

The repository holds a **deterministic MRPII engine exposed through FastAPI, plus LLM-only agent stubs**. There are no database, negotiation, simulation, audit or frontend layers. The 25% vertical slice is not yet functional end-to-end.

## Technologies actually in use

| Area | Evidence |
| --- | --- |
| Backend | Python + FastAPI. `backend/app/main.py` mounts one router, `/planning`, plus `/health`. |
| Data models | Pydantic in `backend/app/models/*` (in-memory, not ORM). |
| Data source | Hard-coded seed data in `backend/app/data/seed_data.py`, exposed by `scenarios.get_default_scenario()`. |
| Agent framework | `openai-agents` (OpenAI Agents SDK). `agents/base.py` wraps it. |
| LLM runtime | Local Ollama at `localhost:11434/v1`, model `qwen3.5:4b`, hard-coded in `agents/base.py`. |
| Database | PostgreSQL is documented only. No SQLAlchemy, psycopg, asyncpg or Alembic in code or requirements. |
| Frontend | None. `frontend/` holds only an empty README. |
| Infra | `docker-compose.yml`, `.env.example` and the root and backend READMEs are all 0 bytes. |
| Tests | pytest (installed globally, **not in `.venv`**). |

## Status by area

| # | Area | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Repo structure | IMPLEMENTED | `backend/app/{agents,api,mrpii,models,services,negotiation,simulation,llm,schemas,core,data}` |
| 3 | Backend entry / architecture | PARTIAL | `main.py` plus `api/planning.py` (5 POST endpoints and 1 GET, no request bodies). Other API files are empty. |
| 4 | Frontend | MISSING | Only a README (0 bytes). |
| 5 | DB models / migrations / data access | DOCUMENTED ONLY | `database_schema.md` (multi-schema Postgres). Code has only Pydantic models, and no migrations or persistence. |
| 6 | Deterministic MRPII logic | PARTIAL | See below. |
| 7 | Production Planning Agent | PARTIAL | Prompt-only agent, no tools, no state, no negotiation. |
| 8 | Inventory Agent | PARTIAL | Prompt-only agent. |
| 9 | Purchasing Agent | PARTIAL | Prompt-only agent. |
| 10 | Negotiation / communication | MISSING | `negotiation/{messages,protocol,session}.py` are 0 bytes. `workflow.py` says A2A and Contract Net are "added later". |
| 11 | LLM integration | PARTIAL | Client wired in `agents/base.py`. `llm/{client,prompts,reasoning}.py` are empty. There is no structured-output validation. |
| 12 | Simulation / disruption | MISSING | `simulation/*`, `schemas/simulation.py` and `api/simulation.py` are empty. `data/scenarios.py` only returns the seed data. |
| 13 | Audit / decision logging | MISSING | `core/logging.py` is empty. There is no audit table or code. |
| 14 | Tests | PARTIAL | 7 tests pass: `python -m pytest -q tests app/mrpii` from `backend/`. They cover MPS, BOM explosion and netting only. |

### Deterministic MRPII (area 6)
- Implemented and working: MPS (`mrpii/mps.py`, aggregates by product and due date), BOM explosion, inventory netting, time-phased planned orders (`mrp.py`), capacity (`capacity.py`), scheduling (`scheduling.py`) and schedule validation (`validator.py`). `services/planning_service.py` composes them, and `/planning/run` runs the full flow.
- Empty stubs: `services/bom_service.py`, `inventory_service.py` and `capacity_service.py`.
- Not present: reservations, safety-stock handling, any supplier data or service, and persistence.

## Implemented for the 25% slice
- Customer order → MPS → BOM explosion → inventory netting → planned procurement orders, all deterministic and exposed over HTTP.
- Capacity, scheduling and schedule validation. These are useful, but they are outside the milestone's core path.

## Partial
- The three milestone agents exist only as system prompts with no tools. `agents/workflow.py` chains agents sequentially through free-text LLM output and prints the results. There is no negotiation, no tool access to the deterministic services, and no structured output.
- The LLM connection is hard-coded (URL and model), with no config.

## Missing for the 25% milestone
1. PostgreSQL persistence and a data-access layer, with the schema from `database_schema.md`.
2. Supplier data and service (lead time, MOQ, available quantity; no price in 25% scope). Only `Material.lead_time_days` exists today.
3. Inventory service with reservation and safety-stock logic.
4. Agent tools that call the deterministic services. Agent state (`current_goal`, `reserved_limits`, offer histories and so on) is not implemented.
5. The negotiation layer: REQUEST / OFFER / COUNTER_OFFER / ACCEPT / REJECT / AGREEMENT_PROPOSED / COMMIT. It needs multi-factor offers, session persistence and validation of structured LLM output.
6. Agreement → initial plan.
7. The simulation: a scenario manager, a disruption injector and re-evaluation → revised plan.
8. Audit / decision logging.
9. A dashboard frontend.
10. Config, `.env`, Docker and a `pytest` entry in requirements.
11. Tests for agents, negotiation, disruption and the end-to-end flow.

## Code / documentation mismatches
- **Extra agents.** Sales, Production and Warehouse agents (and `workflow.py` uses all six) exist in code. `CLAUDE.md` and `DECISIONS.md` scope the 25% milestone to Planning, Inventory and Purchasing, and list the others as future scope. `workflow.py` also has the Planning Agent "coordinate" the other agents, which blurs the ownership boundaries.
- **Agent prompts overlap docs.** For example, the Inventory Agent prompt says it "coordinates material requirements with Purchasing", and the Planning prompt says it "coordinates replanning" for all agents. `agent_operations.md` defines narrower ownership.
- **Available-quantity formula.** `InventoryItem.available_quantity` is `on_hand − allocated + incoming`. `database_schema.md` and `agent_operations.md` define it as `on_hand − reserved − safety_stock`. Safety stock exists on `Material` but is not used in netting, and incoming stock is counted as available.
- **Netting simplification.** `calculate_net_requirements` and `generate_time_phased_requirements` compute netting separately and can differ. `generate_planned_orders` is dead code (it contains an empty loop and uses the earliest MPS date for every material).
- **Schema vs models.** The DB schema (`core.items`, `sales.*`, `planning.mrp_requirements` and so on) does not match the Pydantic model shapes (`Product`, `Material`, `InventoryItem`, `BOM`).
- **Tech-stack doc vs repo.** `dev_docs/tech_stack.md` (which is not under `implementation_25%/`) says Next.js API routes, Eve, A2A and Neon. The repo uses FastAPI and the OpenAI Agents SDK with Ollama. `CLAUDE.md` names the `implementation_25%/` folder as home of `tech_stack.md`, but it is one level up.
- **Requirements file.** `backend/requirements.txt` is UTF-16 encoded (pip will likely fail to parse it), is a full freeze that includes `pywin32`, and lacks `pytest`.
- **Test collection.** A bare `pytest` fails: `test_sales_agent.py` is a script that imports the agents SDK, which is not on the global Python, and it would call the LLM.
- **Empty `docs/`.** `docs/{api,architecture,decisions}` are empty. `CLAUDE.md` names a `docs/DECISIONS.md`, while the real one is `dev_docs/DECISIONS.md`.

## Unresolved technical questions
- **Agent framework.** The OpenAI Agents SDK is in use in code. Confirm it stays, or record it in `DECISIONS.md`.
- **Backend.** FastAPI is in use. Confirm it, since `tech_stack.md` says Next.js API routes.
- **LLM model.** `qwen3.5:4b` is hard-coded. Confirm the model and whether it is configurable.
- **Communication.** A2A vs an in-process message layer. This is undecided, and no A2A dependency is present.
- **DB access and migrations.** No ORM or migration tool is chosen (SQLAlchemy/Alembic, or raw SQL).
- **Purchase orders.** Whether the milestone needs `purchase_orders`. The current schema has only `purchase_requisitions`.
- **Milestone disruption scenario.** Which one (supplier delay is the natural fit) is not yet fixed.
- **Extra agents.** Whether to keep, park or remove the Sales/Production/Warehouse stubs.
- **Frontend.** Whether Next.js is confirmed.

## Recommended next implementation task

**Phase 3 foundation, then persistence.** Before adding agents or negotiation:
1. Reconcile the inventory availability formula with the docs (`on_hand − reserved − safety_stock`) and add tests. The change is small and deterministic.
2. Add a simple supplier data set plus a deterministic supplier-options service, which Purchasing will need.
3. Fix housekeeping: re-encode `requirements.txt` as UTF-8 with pytest, keep the LLM-calling script out of test collection, and remove dead code in `mrp.py`.

Then take PostgreSQL persistence and agent tools (Phase 4) as the next task. Both need your decisions on the open questions above first.
