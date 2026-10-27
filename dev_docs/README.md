# dev_docs

Start here. Operating rules for Claude: `/CLAUDE.md`. Terms: `/GLOSSARY.md`.

## What the project is

A decentralized **MRPII** (Manufacturing Resource Planning) research prototype. Autonomous domain agents own their own
data and decisions and coordinate by negotiation and published events, instead of one central planner deciding.
Shared infrastructure (database, Negotiation Engine, LLM runtime) is allowed; it never makes business decisions.
LLMs help with wording and reasoning but are never the source of business truth.

## What is built (branch `purchasing-agent`, 2026-10-18)

| Part | State | Code / main doc |
| --- | --- | --- |
| Sales Agent | Implemented | `backend/app/sales_agent/`, `sales_agent/` |
| Purchasing Agent | Implemented standalone (tickets 01–11); runs and is tested on its own, with test inputs instead of other agents | `backend/app/purchasing_agent/` (README), `purchasing_agent/` |
| Supplier Service | Read-only supplier data service + supplier-facing test chat. **Not an agent** | `backend/app/supplier_service/`, `supplier/` |
| Negotiation Engine | Shared infrastructure: sessions, messages, rounds, deadlines; no business decisions. Hosts only Purchasing ↔ supplier sessions today (hard-coded) | `backend/app/negotiation_engine/` |
| Planning, Inventory, Warehouse, HR (roster final: six agents, no separate Production agent, `DECISIONS.md` O-9) | Designed (4 notes each), **not built** in the new architecture. Older agent code in `backend/app/agents/` etc. is legacy/provisional | `planning_agent/`, `inventory_agent/`, `warehouse_agent/`, `hr_agent/` |
| Multi-agent integration (A2A, Pub/Sub, cross-agent commit) | **Not built**; open decisions | `adr/ADR-001.md` §10, `DECISIONS.md` |

Details and test results: `PROJECT_STATUS.md`.

## Where each doc lives

| Path | Contents |
| --- | --- |
| `PROJECT_STATUS.md` | What is actually in the repository (per ticket), known risks, tests |
| `ROADMAP.md` | Build plan and steps for the six-agent design (a plan, not a record) |
| `DECISIONS.md` | Confirmed and open decisions for the six-agent design |
| `adr/ADR-001.md` | Architecture discussion, rationale, pending decisions; Purchasing-only confirmations |
| `adr/ADR-002-price-in-supplier-selection.md` | Price is used in supplier selection only, never negotiated |
| `OVERALL_DATABASE_SCHEMA.md` | All schemas; §5 Supplier Service + Purchasing, §8 Negotiation Engine (migrations `004`, `005`) |
| `purchasing_agent/OVERVIEW.md` | Manual test guide: setup, run, fixture IDs, step-by-step scenarios, troubleshooting |
| `purchasing_agent/1_purchasing_agent_high_architecture.md` | Purchasing system boundary, doors, outcomes, rules |
| `purchasing_agent/2_purchasing_agent_functions.md` | Purchasing role, methods, functions, LLM control steps |
| `purchasing_agent/3_purchasing_agent_backend.md` | Purchasing layers, API, flows, settings, errors and tests |
| `purchasing_agent/4_purchasing_agent_database.md` | Purchasing tables, statuses, DB vs code rules |
| `purchasing_agent/purchasing_agent_architecture.md` | Purchasing rules: selection, splits, negotiation, approval, LLM guardrails (detailed reference) |
| `purchasing_agent/seed_data.md` | Purchasing test fixture (PA-v1) and scenario IDs |
| `purchasing_agent/diagrams/` | Purchasing diagrams |
| `supplier/1`–`4` | Supplier (not an agent): overview and boundaries, test-channel chat, Supplier Service backend, `supplier_service` tables and seed |
| `sales_agent/1`–`4` | Sales Agent design notes (architecture, functions, backend, database) |
| `planning_agent/`, `inventory_agent/`, `warehouse_agent/`, `hr_agent/` | Design notes for the other agents (4 notes each) |
| `research/real_manufacturing_mrpii_research.md` | How real MRPII/ERP systems work; sources; gap analysis |
| `architecture/` | Six-agent design: high-level architecture, event channel, negotiation, quantity accounting, system design, backend API, demo; `quotes_and_agent_decisions.md` (approved 2026-10-26) — owners quote their own options, agents decide at fixed decision points with the LLM |
| `SCENARIOS.md` | Business scenarios (SmartPhone X1) |
| `TECH_STACK.md` | Original early stack plan (history; superseded by `DECISIONS.md`) |
| `*.png` | System and relational schema diagrams (to be redrawn by the developer) |
| `agents/` | How the engineering skills use this repo: issue tracker (`.scratch/`), triage labels, domain docs |
| `/.scratch/purchasing-agent/` | Purchasing spec and tickets 01–11 |


Each agent folder follows the Sales pattern: `1_high_level_architecture`, `2_functions`, `3_backend`, `4_database`.
