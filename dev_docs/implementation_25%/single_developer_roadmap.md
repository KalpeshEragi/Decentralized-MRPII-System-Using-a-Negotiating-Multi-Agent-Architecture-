# Single-Developer Implementation Roadmap — 25% Milestone

Persistent source of truth for taking the project from Phase 0 to the completed 25% milestone with **one developer**
(working with Claude Code). It replaces the earlier two-developer roadmap (2026-09-30). There is no Dev 1 / Dev 2 split.

This file is a **plan, not an implementation record**. What is actually built is in `dev_docs/PROJECT_STATUS.md`.

Related documents (read, do not duplicate): `CLAUDE.md`, `dev_docs/DECISIONS.md` (summary), `docs/DECISIONS.md`
(detailed decision record), `dev_docs/implementation_25%/system_spec.md`, `scenarios.md` (source of truth for the
scenarios, never modified), `agent_operations.md`, `database_schema.md`, `table_relations.md`, `docs/contracts/`.

---

## 1. Phase progress

Tick a phase only after its gate (§2) is met.

- [ ] **Phase 0** — Foundation and decisions
- [ ] **Phase 1** — Deterministic core (no database)
- [ ] **Phase 2** — Database, services and backend integration
- [ ] **Phase 3** — Agents, negotiation and A2A
- [ ] **Phase 4** — End-to-end workflow and scenarios
- [ ] **Phase 5** — Frontend, demo and polish

Decision log for this roadmap:

| Date | Decision / change |
| --- | --- |
| 2026-09-30 | Switched from the two-developer roadmap to this single-developer roadmap. All confirmed decisions (P0-01 to P0-17) are kept. |
| 2026-09-30 | "Phase 1" = deterministic core without a database; database is Phase 2 (resolves P1-08). |
| 2026-09-30 | Confirmed D2 single-level BOM, D3 minimal capacity check, D9 (Purchasing sends AGREEMENT_PROPOSED; COMMIT after human approval; no timers), round semantics (P1-07). Agent architecture docs aligned with P0-02. |

---

## 2. Working rules

- **One phase at a time.** Work only on the current phase. Do not build later-phase features early.
- **Workflow per step:** Claude implements → tests → shows the changes → stops. The developer reviews, then runs
  `git add` / `git commit` / `git push` personally. Claude never commits, pushes, merges or rewrites history unless
  explicitly asked for that exact operation.
- **Branches:** one short-lived branch per phase or topic, `phase-N-topic`, from `master`; merged into `master` by PR.
  `master` is the integration branch (P0-17, not renamed to `main`).
- **Contracts first:** a contract change (`docs/contracts/`) is made and reviewed before the code that depends on it.
- **Phase gate** (all must hold before ticking a phase):
  1. The phase's key work and deliverable exist and work.
  2. All tests pass, including the phase's new tests.
  3. Folder `README.md` files match the code; docs, contracts and decisions agree with it.
  4. The developer has reviewed the changes and can explain them.
  5. Merged to `master`, tagged `phase-N`, `PROJECT_STATUS.md` and §1 updated.

---

## 3. Architecture (unchanged)

A modular monolith: one FastAPI backend and one Next.js frontend. Neon PostgreSQL is the single database.

- `mrpii/`: pure deterministic MPS, BOM explosion, netting, shortage, capacity check, plan validation. No database or LLM.
- `services/`: business logic and transactions; the only path to the database. Agents call services, never tables.
- `negotiation/`: protocol, state machine, message validation, persistence, round limit. Makes no business decisions.
- `llm/`: configurable Ollama client; structured output is parsed and validated before use. The LLM only proposes.
- `agents/`: `base`, `planning/`, `inventory/`, `purchasing/`, exposed as A2A endpoints in the same FastAPI app.
- `simulation/`: the Scenario Manager injects events through the owning services; agents decide the response.
- `api/` routers, `models/` ORM, `alembic/` migrations, `data/` X1 fixtures and seed, `schemas/` shared shapes.

Every meaningful folder has a concise `README.md` describing the actual code in it (template in `docs/README.md`).

---

## 4. Phases

**Order.** Pure negotiation protocol and the LLM client sit in Phase 1 next to the MRPII core because they need no
database and can be tested with exact values and a fake model. The A2A spike is in Phase 2 so the riskiest integration
(D13) is proven before agents depend on it. The frontend comes last, on an API already proven end to end in Phase 4
(supplier and approval steps are driven through the API and tests until then).

### Phase 0 — Foundation and decisions
- **Goal:** one consistent set of decisions and contracts to implement against.
- **Key work:** merge the pending Phase 0 documentation fixes; adopt this roadmap; fix the three
  `*_agent_architecture.md` docs (remove cost/price, Inventory → Purchasing initiation, requisition creation owned by
  Purchasing); finalize the decisions in §5 "Before Phase 1"; confirm C1, C4, C5, C6.
- **Deliverable:** consistent repository and docs, confirmed contracts, the SmartPhone X1 fixture spec, green baseline tests, tag `phase-0`.
- **Dependencies:** none.

### Phase 1 — Deterministic core (no database)
- **Goal:** trusted pure logic.
- **Key work:** `schemas/` domain (C1) and negotiation (C4) shapes; `mrpii/` (MPS with order traceability and priority,
  single-level BOM explosion, time-phased netting with `projected_available_quantity`, shortage detection, minimal
  capacity check, plan validator); `negotiation/` pure protocol (envelope and sequence validation, state machine
  including `FAILED`, 3-round limit); `llm/` (configurable Ollama client, no-reasoning mode, structured-output parsing and
  validation, tested with a fake model); X1 fixtures in `data/`.
- **Deliverable:** a script computes MPS → MRP → shortage on the X1 fixture with exact expected quantities; a fake-agent
  exchange reaches agreement or `FAILED`.
- **Dependencies:** Phase 0 (D1, D2, D3, D9, C4 terms and envelope, round semantics).

### Phase 2 — Database, services and backend integration
- **Goal:** persistent business truth on Neon, reachable only through services; A2A proven.
- **Key work:** SQLAlchemy ORM for the C2 subset; Alembic migrations 001 (core, sales, inventory, planning, purchasing,
  agent) then 002 (negotiation, simulation, audit); X1 seed loader and reset (re-seed) function; services for orders,
  planning (persist MPS/MRP), inventory availability and reserve/release, supplier lookup, negotiation persistence,
  audit writing; FastAPI routers for orders, plans and supplier responses ("Round N of 3") with the C5 error format;
  C3 service signatures; A2A spike (three endpoints in one FastAPI app exchanging the C4 envelope, with the OpenAI
  Agents SDK and Ollama no-reasoning mode).
- **Deliverable:** clean migrations on Neon and seeded data; an order created through the API produces a persisted MRP
  shortage; a persisted negotiation session accepts supplier responses within 3 rounds; A2A echo works.
- **Dependencies:** Phase 1; P0-11 and P0-16 storage choices, D7, test-database isolation on Neon, D10.

### Phase 3 — Agents, negotiation and A2A
- **Goal:** autonomous shortage negotiation.
- **Key work:** `agents/base` (agent state per C6, tool binding to services, audit writer per C7, LLM wrapper with
  validation before any decision); Inventory Agent (availability tool, shortage detection, initiates negotiation with
  Purchasing over A2A); Purchasing Agent (supplier options tool, quantity/date/lead-time proposals — LLM proposes,
  deterministic validation decides ACCEPT / REJECT / COUNTER_OFFER — supplier round handling); Planning Agent core
  (order intake, runs MRP, requests availability, receives the agreement or `FAILED` result).
- **Deliverable:** a shortage triggers Inventory → Purchasing negotiation over A2A with a scripted supplier, ending in
  agreement or `FAILED`, with audit records and agent state persisted; agent boundary tests pass.
- **Dependencies:** Phase 2; P1-06, P1-07, D5, D13 (answered by the spike).

### Phase 4 — End-to-end workflow and scenarios
- **Goal:** the complete 25% behavior through the API.
- **Key work:** Planning Agent updates and validates the plan; approval service and API (C8): approve → execute/commit
  (D8), reject → automatic replan, maximum 2 planning attempts, then human intervention required; Scenario Manager (C9)
  injecting events through the owning services; scenarios 1, 2, 3, 4, 6 and 7.
- **Deliverable:** one API-level end-to-end test per in-scope scenario with exact outcomes, covering the agreement path,
  the `FAILED` path and reject → replan.
- **Dependencies:** Phase 3; D8, C8 (approval state and attempt-counter location), C9 (event types and parameters).

### Phase 5 — Frontend, demo and polish
- **Goal:** a demonstrable, defensible system.
- **Key work:** Next.js app: order form, plan view, supplier response form (quantity, delivery date / lead time,
  optional message, "Round N of 3", no price), negotiation timeline, approval screen, simulation controls, decision log,
  basic dashboard including `FAILED` visibility; one bounded real-Ollama smoke test; `PROJECT_STATUS.md` separating
  implemented, planned and future scope; demo script.
- **Deliverable:** Scenario 1 fully from the UI; all six in-scope scenarios runnable from the simulation page; full test
  suite green; rehearsed demo.
- **Dependencies:** Phase 4; D11.

---

## 5. Decisions to finalize

Details and options for each item are in `docs/DECISIONS.md`.

| When | Decisions |
| --- | --- |
| **Before Phase 1** (blocking) | D1 / P1-01 SmartPhone X1 fixture spec (proposed) · ~~P1-05 C4 `OfferTerms` and envelope~~ and ~~P1-07 early `REJECT`~~ (both decided 2026-09-30). Confirmed: D2 / P1-02, D3 / P1-03, D9 / P1-04, P1-07 round semantics |
| Before Phase 2 | P0-11 production lead time storage · P0-16 date column mapping · D7 Alembic scope · test-database isolation on Neon · D10 reset between demo runs |
| Before Phase 3 | P1-06 Planning ↔ Inventory allocation semantics · P1-07 rest (supplier messages in sessions and storage) · D5 A2A layout · D13 (spike result) |
| Before Phase 4 | D8 what approve → execute/commit does · C8 approval state and attempt counter · C9 simulation event types and parameters |
| Before Phase 5 | D11 frontend tooling |

## 6. Contracts

All contracts are owned by the single developer; "review" means the developer reads, understands and confirms them.

| # | Contract | Needed by |
| --- | --- | --- |
| C1 | Domain data shapes (`C1_domain.md`) | Phase 1 |
| C2 | Database schema subset and migration order (`C2_database_schema.md`) | Phase 2 |
| C3 | Service function signatures (to be written) | Phase 2 |
| C4 | Negotiation protocol (`C4_negotiation_protocol.md`) | Phase 1 |
| C5 | API error format (`C5_errors.md`) and per-router API models | Phase 2 |
| C6 | Agent state (`C6_agent_state.md`) | Phase 3 |
| C7 | Audit record (`C7_audit_record.md`) | Phase 3 |
| C8 | Approval and replan state, attempt counter (to be written) | Phase 4 |
| C9 | Simulation event types and parameters (to be written) | Phase 4 |

## 7. Out of scope for the 25% milestone

- Cost/price in any form (fields, factors, forms, acceptance criteria, LLM reasoning), and Scenario 5.
- Sales, Production, Warehouse and Supplier agents.
- `purchase_orders`, `purchase_order_items` and `production.*` tables.
- Multi-level BOM (unless D2 decides otherwise); advanced scheduling or optimization.
- Real supplier channels (email, WhatsApp, supplier APIs); only the tester-as-supplier form.
- Event bus, message queues, background job systems, extra microservices, multiple databases, local Postgres containers.
- Authentication and user management.
- Any fallback optimization after `FAILED`.
- Browser end-to-end tests (unless D11 adds them); production deployment and scaling.
