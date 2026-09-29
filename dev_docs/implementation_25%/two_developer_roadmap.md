# Two-Developer Implementation Roadmap — 25% Milestone

Persistent source of truth for planning and executing the 25% implementation with two developers, each using an independent Claude Code session.

This file is a **plan, not an implementation record**. Sections marked **UNRESOLVED** are open decisions and must not be assumed.

Related documents (do not duplicate them here, read them): `CLAUDE.md`, `dev_docs/DECISIONS.md`, `dev_docs/PROJECT_STATUS.md`, `dev_docs/IMPLEMENTATION_PLAN.md`, `dev_docs/implementation_25%/system_spec.md`, `scenarios.md` (source of truth for the scenarios), `agent_operations.md`, `database_schema.md`, `table_relations.md`.

---

## 0. How to use this roadmap

1. **Both developers must read this document before starting work**, together with `CLAUDE.md`, `DECISIONS.md` and `system_spec.md`. A fresh Claude Code session should be told to read this file first.
2. Each developer follows **their assigned work package** in the current phase (Section 7). Work not assigned to you is not yours to build.
3. **Check completed work against the phase gate** (Section 7 and Section 9) before declaring a phase done.
4. **Update this roadmap after each completed phase**: tick the checklist in Section 1, and record any decision made or contract change.
5. **Architecture, documentation and code must stay synchronized.** Every PR that adds or changes files in a folder updates that folder's `README.md`. Nothing is documented that does not exist.
6. **Neither developer silently changes a contract, another developer's assigned work, or the architecture.** A contract change is a small reviewed PR (Section 8).
7. Where this file and the finalized project documents disagree, do not resolve it silently. Surface it to both developers.
8. Do not build anything not required by the 25% scope or as a dependency of it (Sections 4 and 5).

---

## 1. Phase Progress Tracking

Update after each phase gate is met.

- [ ] **Phase 0** — Collaborative architecture and contracts
- [ ] **Phase 1 / M1** — Deterministic MRPII core ‖ negotiation protocol
- [ ] **Phase 2 / M2** — Persistence swap ‖ A2A spike ‖ frontend skeleton
- [ ] **Phase 3 / M3** — Two vertical slices (order → plan → shortage; negotiation/supplier interaction)
- [ ] **Phase 4 / M4** — Inventory and Purchasing agents
- [ ] **Phase 5 / M5** — Scenario 1 end to end (Planning Agent, approval, replanning)
- [ ] **Phase 6 / M6** — Simulation and scenarios 2, 3, 4, 6, 7
- [ ] **Phase 7** — Audit views and dashboard
- [ ] **Phase 8 / M7** — Hardening, review and demo

Decision log for this roadmap (append entries as decisions are made):

| Date | Decision / change | Made by |
| --- | --- | --- |
| 2026-09-30 | Phase 0 coordination items P0-01 to P0-17 confirmed and recorded in `DECISIONS.md` (see `docs/decisions/phase0_coordination.md`). Includes PostgreSQL on Neon, no local container (P0-03) and `master` as integration branch (P0-17). | Dev 1 (confirmed by team) |

---

## 2. Current repository state (at time of writing)

- `master` is clean. Last commit `b1f42da` removed the prototype code and added the scaffold.
- `backend/app/{agents,api,core,data,llm,models,mrpii,negotiation,schemas,services,simulation}` and `backend/tests/{agents,mrpii,negotiation,simulation}` exist. **Every source file is 0 bytes.**
- `backend/tests/mrpii/test_mrp.py` is stale (imports removed modules) and will fail collection.
- `requirements.txt` is the old full freeze. It includes the OpenAI Agents SDK, but not the A2A SDK, SQLAlchemy, Alembic or a Postgres driver. `pytest.ini`, `.env.example`, `docker-compose.yml` and all READMEs are empty.
- `frontend/` holds only an empty README.
- `dev_docs/` is complete. `docs/{api,architecture,decisions}` are empty.
- Nothing exists for the database, negotiation, LLM, A2A, agents, simulation or frontend.

Verify this state at the start of Phase 0. It may have changed.

---

## 3. Project understanding

```
Tester -> creates order (web app) -> API
  -> Production Planning Agent: MPS -> deterministic MRP -> shortage?
  -> Inventory Agent: checks availability (on_hand - reserved - safety_stock)
       -- shortage --> Inventory Agent initiates negotiation (A2A) --> Purchasing Agent
       Purchasing <-> supplier communication interface <-> tester acting as supplier
       (quantity + delivery date/lead time + optional message; max 3 rounds;
        the Purchasing Agent alone decides ACCEPT / REJECT / COUNTER)
  -> Agreement or FAILED -> back to Planning Agent -> updated plan
  -> deterministic validation -> human approval
       approve -> execute/commit      reject -> automatic replan (max 2 attempts, then human intervention)
Simulation injects a disruption on an existing plan -> agents re-evaluate -> re-negotiate
  -> agreement/FAILED -> updated plan
```

Guiding rules:
- Decentralized decisions; shared infrastructure only.
- Deterministic business truth: LLM proposes, deterministic validation decides.
- The Negotiation Engine manages protocol only; it never decides outcomes.
- The Production Planning Agent owns the production plan but must not override other agents' constraints.

---

## 4. Finalized decisions (from `DECISIONS.md` and project documents)

- **Agents:** exactly three: Production Planning, Inventory, Purchasing. No Sales Agent, no Supplier Agent. The tester creates orders through the application/API. Sales, Production, Warehouse and Supplier agents are future scope.
- **Stack:** FastAPI backend, OpenAI Agents SDK, Next.js + React frontend, PostgreSQL with SQLAlchemy + Alembic.
- **A2A:** official A2A Python SDK over HTTP endpoints for the core agents. No fake or minimal A2A-compatible layer. No event bus.
- **LLM:** Ollama `qwen3.5:4b` by default. Model name and Ollama URL configurable. Fast/no-reasoning mode for normal negotiation calls. The LLM only reasons and proposes.
- **Shortage flow:** the Inventory Agent detects a shortage and initiates procurement negotiation with the Purchasing Agent over A2A. Purchasing handles supplier interaction. Planning receives the agreement or `FAILED` result.
- **Supplier interaction:** no Supplier Agent. The Purchasing Agent talks to a supplier communication interface. In the demo the tester acts as supplier through a structured form (quantity, delivery date/lead time, optional message). The tester provides supplier-side responses only and does not decide when negotiation ends. Purchasing alone decides ACCEPT/REJECT/COUNTER.
- **Negotiation factors (only):** material quantity, required date, delivery date/lead time, inventory impact, production priority.
- **Limits:** max 3 supplier rounds per session, shown as "Round N of 3". No agreement within 3 rounds -> session ends `FAILED`. `FAILED` is a distinct end status (not `REJECTED`, `ABORTED` or `EXPIRED`). After `FAILED` the shortage stays unresolved, the plan is not updated, and the failure is recorded and visible.
- **Agreement:** agents accept; hard constraints satisfied; preferences/bounds satisfied; feasible resolution of the shortage; recorded by the negotiation system. Deterministic validation is the authority on feasibility.
- **Human approval:** after deterministic validation, the tester approves (execute/commit) or rejects (replan). The human is not the planner or negotiator.
- **Replanning:** rejection triggers automatic replanning, and the new plan returns to human approval. Max 2 planning attempts (each with at most one negotiation session of at most 3 rounds). If attempt 2 cannot produce a feasible plan/agreement, automatic replanning stops and human intervention is required. No infinite loops.
- **Available quantity:** `available_quantity = on_hand - reserved - safety_stock` (floored at 0). Incoming/scheduled receipts are not part of it; MRP netting adds them separately.
- **Purchase orders:** `purchase_orders` and `purchase_order_items` are out of scope. The negotiation agreement is the purchasing outcome; approval and activity are recorded via agreement/audit records.
- **Cost/price:** completely out of scope for the 25% (see Section 5).
- **Scenarios:** `scenarios.md` is the unmodified source of truth for the seven finalized scenarios. Scenario 5 is out of scope. Scenarios 1, 2, 3, 4, 6, 7 are required. For Scenario 4 the "lead time/cost" constraint is implemented as lead time only.
- **Parked code:** old Sales, Production and Warehouse agent stubs were removed from the repository and are not to be rebuilt in the 25%.

---

## 5. Out of scope — must not be built in the 25%

- **Cost/price in any form:** no price fields, no cost in negotiation factors, supplier forms, offers/counter-offers, acceptance/rejection criteria or LLM reasoning. Future scope, to be revisited after the 25% milestone.
- **Scenario 5 (Supplier Price Increase):** future scope. No supplier price-increase behavior and no cost/price fields or logic to support it. `scenarios.md` is not modified.
- Sales, Production, Warehouse and Supplier agents.
- `purchase_orders`, `purchase_order_items` and `production.*` tables.
- Event bus, message queues, background job systems, additional microservices, multiple databases.
- Multi-level BOM and advanced scheduling/optimization (single-level BOM is the recommended default, D2).
- Real supplier channels (email, WhatsApp, supplier APIs). The interface is designed so they can replace the tester later, but they are not built.
- Authentication and user management.
- Any fallback optimization after `FAILED`.
- Any component that is neither required by the 25% scope nor a dependency of something inside it.

---

## 6. Target architecture and folder structure

**Architecture.** A modular monolith: one FastAPI backend and one Next.js frontend.
- `mrpii/`: pure deterministic calculation (MPS, BOM explosion, netting, shortage, capacity check, plan validation). No database or LLM dependency.
- `services/`: business logic and transactions. The only path to the database. Agents call services, never tables.
- Negotiation Engine: protocol, state machine, message validation, routing, persistence, round limit. Makes no business decisions.
- Agents: three A2A endpoints mounted in the same FastAPI app. LLM proposes; deterministic validation decides.
- Simulation: the Scenario Manager injects events through the owning services. Agents decide the response.

**Target folder structure.** Ownership is per phase and rotates (Section 7). There is no permanent owner.

```
backend/app/
  core/          config, logging, error format
  schemas/       shared Pydantic contracts: domain data, API DTOs, negotiation messages, enums
  models/        SQLAlchemy ORM tables (25% subset)
  mrpii/         pure deterministic MPS / BOM / MRP / capacity / validation
  services/      order, planning, inventory, supplier lookup, negotiation persistence, approval, audit
  negotiation/   protocol state machine, message validation, persistence, round limit
  llm/           configurable Ollama client, structured-output parse + validate
  agents/        base (state + tool binding + audit writer + LLM wrapper), planning/, inventory/, purchasing/
  simulation/    Scenario Manager, event handlers
  api/           routers by slice
  data/          seed fixtures (SmartPhone X1 / Display Assemblies fixture set)
backend/alembic/ migrations (001 then 002, see Phase 2)
backend/tests/   mrpii, services, api, db, negotiation, agents, simulation, e2e
frontend/        Next.js app (route directories split by slice)
docs/            living status, contracts (docs/contracts/), architecture
dev_docs/        finalized specifications (stable)
```

**Folder documentation (mandatory).** Every meaningful folder has a concise `README.md` describing the ACTUAL implementation. It covers folder purpose and responsibility, important files (high-level: what each does, its major class/function/service, why it exists, how it relates to other files), relationships with other folders, important dependencies, and high-level data/control flow. It is not line-by-line and never describes functionality that does not exist yet. It must be simple enough for another student to follow and technical enough to defend in a viva.

---

## 7. Two-developer strategy, contribution matrix and phase plan

### 7.1 Strategy

**Philosophy.** Work is cut into vertical slices (logic, persistence, API and UI for one capability), not layers. Ownership of a slice is temporary: each developer implements one slice, then reviews and extends the other's. Neither developer becomes "the backend developer", "the frontend developer" or the owner of one subsystem.

**Rotation rule.** Whoever implements the pure logic of a domain in one phase implements its persistence or integration in the next phase, but never in the same phase as the other developer's logic. Each developer therefore writes persistence, services or integration against the other's logic before the project ends. Do not rotate ownership artificially where it would only add complexity.

**Where parallelism is real:** pure MRPII logic vs pure negotiation protocol (Phase 1), the two persistence sets (Phase 2), the two vertical slices (Phase 3), Inventory vs Purchasing agents (Phase 4), the two handler sets (Phase 6), audit views vs dashboard (Phase 7).

**Where work is sequential or paired** (do not force parallelism): contracts (Phase 0), migration order 001 then 002 (Phase 2), `agents/base` (start of Phase 4), the Planning Agent / approval interface (Phase 5), the Scenario Manager skeleton and C9 (start of Phase 6).

**Not a 50/50 file count.** The goal is that both developers contribute substantial technical work across the complete project, not equal numbers of files.

### 7.2 Contribution matrix

| Area | Phase(s) | Dev 1 | Dev 2 |
| --- | --- | --- | --- |
| MRPII (pure logic) | 1, 5 | Phase 1: MPS, BOM explosion, time-phased netting, shortage, plan validator. Phase 5: Planning Agent using them. | Phase 1: reviews and runs. Phase 2: persists it. Phase 3: builds order/plan services on it. Phase 5: approval and replan flow. |
| Database | 2, 3 | Negotiation, simulation and audit tables (migration 002). | Core, sales, inventory, planning, purchasing and agent tables (migration 001), seed loader. |
| Services | 3, 4 | Negotiation persistence service; supplier round handling. | Order, planning, inventory availability and reservation services. |
| Negotiation | 1, 3, 4 | Phase 3: persistence service. Phase 4: Purchasing Agent. Reviews the Phase 1 engine. | Phase 1: protocol state machine. Phase 4: Inventory Agent, which initiates negotiation. |
| LLM layer | 1 | Reviews and runs. | Configurable client and structured-output validation. |
| Agents | 4, 5 | Purchasing Agent (P4), Planning Agent (P5). | `agents/base` (paired with Dev 1), Inventory Agent (P4), approval/replan trigger (P5). |
| A2A | 2, 4 | Spike (P2), Purchasing side (P4). | Inventory side (P4). Reviews the spike. |
| Frontend | 2, 3, 5, 6, 7 | Negotiation timeline and supplier form (P3), simulation controls (P6), decision log page (P7). | Skeleton (P2), order form and plan view (P3), approval UI (P5), dashboard (P7). |
| Simulation | 6 | Manager skeleton, scenarios 3, 6, 7. | Supplier events for scenarios 2 and 4. |
| Testing | all | Tests for what it implements, plus an E2E test per scenario it owns. | Same. In Phase 8 each developer runs the other's E2E tests. |
| Docs and review | all | Per-folder READMEs for what it touches. Reviews Dev 2's slices. | Same. Reviews Dev 1's slices. |

The split above is a plan. If a phase turns out to be unbalanced, rebalance after Phase 3 by agreement and record it in the decision log.

### 7.3 Every phase ends with the same completion gate

**Mandatory phase-completion workflow** (both developers, every phase, in this order):

```
Implement -> Test -> Commit -> Push -> Integrate -> Both Pull
  -> Understand Other Developer's Work -> Explain/Review
  -> Run Integrated Tests -> Verify Docs -> Phase Gate
```

No step is skipped. A phase is not complete until every step is done by both developers.

All of the following must hold:
- Implementation complete for both developers' work packages.
- Relevant tests pass, including the other developer's tests on their machine.
- Integration works (the phase's integration point).
- Folder READMEs updated and match the code; code, documentation and architecture agree.
- The other developer has reviewed the work and can explain its purpose, boundaries, contracts and important design decisions (explain-back).
- Committed and merged to `master`; both developers pulled the new baseline and re-ran the test suite successfully.
- The Section 1 checklist and the decision log are updated.

Do not start a dependent phase before its gate is met.

### Phase 0 — Collaborative architecture and contracts
- **Objective:** shared understanding and stable contracts before any code.
- **Prerequisites:** none.
- **Both developers:** see Section 13 (Recommended Phase 0). Contract drafting is split for authorship but jointly reviewed.
- **Dev 1 drafts:** C1 (domain data shapes), C6 (agent state), the error format part of C5.
- **Dev 2 drafts:** C2 (schema subset and migration order), C4 (negotiation), C7 (audit).
- **Can run in parallel:** each drafts their contracts. **Must wait:** implementation, until all contracts are reviewed and D1–D13 are answered.
- **Coordination point:** a joint review meeting per contract.
- **Integration point:** the contracts land together on `master`.
- **Tests:** contract files parse. The stale test is removed and an empty suite runs.
- **Cross-review:** each developer reads and explains back the other's contracts.
- **Documentation:** `docs/contracts/`, root and backend READMEs, folder README template.
- **Git:** branches, merge by PR with the other's approval. Tag `phase-0`.
- **Gate:** contracts C1, C2, C4, C6, C7 stable; decisions recorded in `DECISIONS.md`; baseline installs and runs.
- **Provides next:** stable contracts and a working baseline.

### Phase 1 — Deterministic MRPII core ‖ negotiation protocol (parallel, M1)
- **Objective:** two independent pure-logic pieces with no database.
- **Prerequisites:** Phase 0.
- **Dev 1:** `schemas/` domain shapes; `mrpii/` (MPS with order traceability and priority, single-level BOM explosion, time-phased MRP netting using `projected_available_quantity`, shortage detection, minimal capacity check, plan validator); X1 fixtures in `data/`.
- **Dev 2:** `negotiation/` pure protocol (envelope validation, message-type and sequence checks, state machine including `FAILED`, 3-round limit); `llm/` (configurable client, no-reasoning mode, structured-output parsing and validation, tested with a fake model).
- **Can run in parallel:** all of it (different folders). **Must wait:** nothing.
- **Coordination point:** `schemas/` has two files, one per developer (`schemas/domain.py`, `schemas/negotiation.py`). Neither edits the other's.
- **Integration point:** none needed this phase; both merge to `master`.
- **Tests, Dev 1:** exact-number tests (gross, net, shortage, dates, validator failures). **Tests, Dev 2:** state-machine transitions, round-limit `FAILED`, invalid messages rejected, LLM output validation with a fake model.
- **Cross-review:** each reads the other's code, writes a short summary of it, and runs its tests. The reviewer of the negotiation engine specifically checks that it contains no business decisions.
- **Documentation:** READMEs for `mrpii/`, `schemas/`, `data/`, `negotiation/`, `llm/`.
- **Git:** parallel pattern; merge order does not matter.
- **Gate / M1:** a script computes MPS -> MRP -> shortage for the X1 fixture with exact expected quantities, and a fake-agent exchange reaches agreement or `FAILED`.
- **Provides next:** trusted pure logic and protocol for persistence.

### Phase 2 — Persistence swap ‖ transport spike ‖ frontend skeleton (M2)
- **Objective:** each developer persists the other's domain; the riskiest integration is de-risked early.
- **Prerequisites:** Phase 1.
- **Dev 2 (persists Dev 1's domain):** ORM for core, sales, inventory, planning, purchasing and agent tables; migration 001; seed loader for the X1 fixture; the Next.js skeleton (layout, typed API client with mocks).
- **Dev 1 (persists Dev 2's domain):** ORM for negotiation, simulation and audit tables (migration 002); the A2A spike (three endpoints in one FastAPI app exchanging the negotiation envelope; verifies A2A SDK + OpenAI Agents SDK + Ollama no-reasoning mode, D13).
- **Can run in parallel:** ORM files, A2A spike, frontend skeleton.
- **Must wait:** Dev 1's migration 002 waits for Dev 2's 001 to merge, because of foreign keys (negotiation -> `agent.agents`). Dev 1 can write the ORM meanwhile.
- **Coordination point:** migration order (001 then 002). Only one migration is created at a time, by the developer whose tables it holds.
- **Integration point:** both migrations apply to a clean Postgres and the seed loads.
- **Tests, Dev 2:** DB integration tests (constraints, seed values match fixtures). **Tests, Dev 1:** negotiation-table persistence round trip, A2A echo round trip.
- **Cross-review:** each reviews the other's ORM mapping against `database_schema.md`; both run the A2A spike.
- **Documentation:** READMEs for `models/`, `alembic/`, `frontend/`, and the A2A location.
- **Git:** parallel pattern, then a dependent step: Dev 2 merges 001, Dev 1 rebases and merges 002.
- **Gate / M2:** clean-database setup works, seeded data is queryable, A2A echo works, frontend skeleton runs.
- **Provides next:** database, seed, transport and UI shell.

### Phase 3 — Two vertical slices (parallel, M3)
- **Objective:** two end-to-end slices (service -> API -> UI).
- **Prerequisites:** Phase 2.
- **Dev 2, Slice A "order -> plan -> shortage":** order, planning and inventory (availability, reserve/release) services on the database; `api/orders.py`, `api/plans.py`; order form and plan pages.
- **Dev 1, Slice B "negotiation record and supplier interaction":** negotiation persistence service; supplier lookup (lead time, MOQ, available quantity); supplier response API (one response per round, "Round N of 3"); supplier form and negotiation timeline pages.
- **Can run in parallel:** both slices; separate services, routers and frontend directories. **Must wait:** nothing.
- **Shared contracts:** C5 per slice, drafted by the slice owner at the start and reviewed by the other before the UI is built. C3 (service signatures) is finalized here.
- **Coordination points:** `main.py` router registration (one line each). The frontend API client (skeleton owner is Dev 2; Dev 1 adds its own client module instead of editing Dev 2's file).
- **Integration point:** each developer cross-runs the other's slice; Dev 1's timeline can display a stub session created in the database.
- **Tests, Dev 2:** service unit and DB integration tests with exact values, API tests, frontend component tests. **Tests, Dev 1:** engine persistence and round-limit tests, API tests for the supplier response, frontend component tests.
- **Cross-review:** each explains the other's slice back and verifies that no agent-facing logic bypasses services.
- **Documentation:** READMEs for `services/`, `api/`, and the touched frontend directories.
- **Git:** parallel; merge after cross-review.
- **Gate / M3:** an order created in the UI produces an MRP shortage from the database; a persisted negotiation session accepts supplier responses within 3 rounds.
- **Provides next:** all services and stores the agents need.

### Phase 4 — Inventory and Purchasing agents (M4)
- **Objective:** the shortage negotiation between two autonomous agents over A2A.
- **Prerequisites:** Phase 3.
- **Step 0, paired (sequential, short):** both write `agents/base` (agent state persistence, tool binding, audit writer, LLM call wrapper). Deliberately shared; neither builds it alone.
- **Dev 2:** Inventory Agent (availability tool, shortage detection, initiating negotiation with Purchasing).
- **Dev 1:** Purchasing Agent (supplier options tool, quantity/date/lead-time proposals with LLM proposing and deterministic validation deciding ACCEPT/REJECT/COUNTER, supplier round handling).
- **Can run in parallel:** the two agents, after step 0. **Must wait:** step 0.
- **Shared contracts:** C4, C6 and C7 (stable since Phase 0).
- **Coordination point:** the shortage-context message content. Inventory (Dev 2) drafts it, Purchasing (Dev 1) reviews before coding.
- **Integration point:** the two agents negotiate over A2A with a scripted supplier.
- **Tests, Dev 2:** boundary tests (Inventory never writes another agent's state or tables), shortage detection, fake-LLM proposal validation. **Tests, Dev 1:** invalid LLM output is rejected, a decision never changes business state directly, a 3-round `FAILED` case.
- **Cross-review:** each reviews the other agent, focusing on autonomy and boundary checks.
- **Documentation:** `agents/` and per-agent READMEs.
- **Git:** paired step merges first, then parallel.
- **Gate / M4:** a shortage produces an agreement or `FAILED` with audit records.
- **Provides next:** working agent negotiation for the Planning flow.

### Phase 5 — Scenario 1 end to end (M5)
- **Objective:** the complete baseline flow, including human approval and replanning.
- **Prerequisites:** Phase 4.
- **Dev 1:** Planning Agent (order intake, calls MRP, requests availability, receives the agreement or `FAILED` result, updates and validates the plan, replan entry point).
- **Dev 2:** approval service and API (approve -> commit per D8; reject -> triggers replan, tracking the attempt counter, stops after 2 attempts and requires human intervention); approval UI; the Scenario 1 E2E test harness.
- **Can run in parallel:** partly. The Planning Agent (Dev 1) and approval flow (Dev 2) can proceed once the replan contract is agreed. **Must wait:** the final E2E run needs both.
- **Shared contract:** C8 (approval and attempt-counter state, and the replan entry point), drafted by Dev 2, reviewed by Dev 1 before coding.
- **Coordination point:** who owns the attempt counter. Proposed: it lives with the plan record, updated by the Planning Agent through the plan service. **UNRESOLVED until agreed at the start of Phase 5.**
- **Integration point:** Scenario 1 runs from the UI through approval and replanning.
- **Tests, Dev 1:** Planning Agent behavior (`FAILED` leaves the plan unchanged, plan validated before approval). **Tests, Dev 2:** attempt limit (max 2), approval and rejection paths, E2E Scenario 1 (agreement path, `FAILED` path, reject -> replan).
- **Cross-review:** each explains the other's part and confirms Planning does not override other agents' constraints.
- **Documentation:** update `agents/planning`, `services/`, `api/`, and the frontend approval directory.
- **Git:** parallel pattern with a mid-phase pull to align on C8.
- **Gate / M5:** Scenario 1 works end to end in the UI.
- **Provides next:** the base on which disruption scenarios run.

### Phase 6 — Simulation and scenarios 2, 3, 4, 6, 7 (M6)
- **Objective:** disruptions injected by the Scenario Manager, with agents deciding the response. Scenario 5 is excluded.
- **Prerequisites:** Phase 5.
- **Step 0, paired (short):** C9 (event types and parameters) and the Scenario Manager skeleton.
- **Dev 1:** Scenario Manager; scenarios 3 (demand increase), 6 (reservation change) and 7 (due-date change); the simulation controls page.
- **Dev 2:** supplier events for scenarios 2 (delay) and 4 (quantity reduction), in a separate handler module.
- **Can run in parallel:** the two handler sets, after step 0. **Must wait:** step 0.
- **Coordination point:** the manager's handler registration, edited by Dev 1 first, with Dev 2 adding only its own module.
- **Integration point:** each scenario runs through the existing agents.
- **Tests:** one E2E test per scenario with exact expected outcomes, written by the developer who implemented it.
- **Cross-review:** each runs and explains the other's scenarios, since these span Planning, Inventory and Purchasing behavior.
- **Documentation:** `simulation/` README and the simulation page.
- **Git:** paired step merges first, then parallel.
- **Gate / M6:** all six in-scope scenarios pass end to end.
- **Provides next:** the full behavior that audit views and the dashboard present.

### Phase 7 — Audit views and dashboard
- **Objective:** make agent decisions, negotiations and failures visible.
- **Prerequisites:** Phase 6.
- **Dev 1:** decision-log API and page. **Dev 2:** dashboard overview, agent activity and `FAILED` views.
- **Can run in parallel:** fully independent. **Must wait:** nothing.
- **Shared contract:** C5 additions (reviewed).
- **Tests:** API and component tests for each. **Cross-review:** each checks that every decision type appears in the UI.
- **Documentation:** the touched API and frontend directories.
- **Git:** parallel pattern.
- **Gate:** every agent decision is visible.

### Phase 8 — Hardening and review (M7)
- **Objective:** a clean, understood, demonstrable system.
- **Both developers:** each runs and explains the other's scenarios and subsystems, verifies that code, docs and architecture agree, runs the full suite, and prepares the demo script.
- **Documentation:** `docs/` status updated to describe what is actually implemented (planned vs implemented vs future scope clearly separated).
- **Gate / M7:** the full test suite is green and the demo runs.

---

## 8. Shared contracts

Only contracts required by the architecture. Assignments are the plan from the roadmap and can be changed by agreement in Phase 0.

| # | Contract | Drafted by | Reviewed by | Stable when | Depends on it | Change handling |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | Domain data shapes and enums (order, plan, requirement, shortage) | Dev 1 | Dev 2 | End of Phase 0 | Phase 1 onward, all services, API | Contract PR |
| C2 | Database schema (25% subset of `database_schema.md`) and migration order | Dev 2 | Dev 1 | End of Phase 0 | Phase 2 onward | Contract PR; migrations follow Phase 2 order |
| C3 | Service function signatures (inventory, supplier lookup, planning, validation, negotiation persistence, audit) | Slice owners (Dev 2: order/planning/inventory; Dev 1: negotiation/supplier) | The other | Finalized at end of Phase 3 | Agents (Phase 4+) | Contract PR |
| C4 | Negotiation envelope, offer terms (five factors), message types, session statuses incl. `FAILED` | Dev 2 | Dev 1 | End of Phase 0 | Phases 1, 3, 4 and later | Contract PR |
| C5 | API request/response models and error format | Slice owner per router; error format by Dev 1 | The other | Per slice, after the other developer's review at the start of Phase 3; additions in Phase 7 | Frontend, API tests | Contract PR |
| C6 | Agent state JSON shapes (`agent_state` fields) | Dev 1 | Dev 2 | End of Phase 0 | Phase 4 onward | Contract PR |
| C7 | Audit record shape | Dev 2 | Dev 1 | End of Phase 0 | Agents, decision-log API | Contract PR |
| C8 | Approval and replan state, attempt counter, replan entry point | Dev 2 | Dev 1 | Start of Phase 5, after review | Phase 5 (Planning Agent, approval flow) | Contract PR |
| C9 | Simulation event types and parameters for scenarios 2, 3, 4, 6, 7 | Paired, start of Phase 6 | Both | Start of Phase 6 step 0 | Phase 6 handlers | Contract PR |

**Contract rule.** Both developers must understand a contract before implementing dependent work. A contract change is a small PR that touches only the contract file and the relevant docs, is reviewed and merged before any dependent code changes, and is announced to the other developer. No one changes a contract silently.

---

## 9. Knowledge-sharing strategy

- **Explain-back:** the reviewer must be able to explain a subsystem's purpose, boundaries, contracts and important design decisions to the author before approving. Review is technical understanding, not formatting checks.
- **Persistence swap (Phase 2):** each developer writes persistence for the other's logic.
- **Integration swap (Phases 4–6):** each developer's later work builds on the other's earlier code.
- **Tests as specification:** the reviewer reads the tests first, then runs them.
- **Paired steps:** `agents/base` and the Scenario Manager skeleton are written together so neither is a silo.
- **Phase 8 rehearsal:** each developer presents and defends the subsystems they did not build.

**Cross-review checklist** (for every major subsystem or vertical slice; Developer A implements, Developer B reviews, runs and understands it, A addresses issues, then a shared baseline):
- architecture and responsibility boundaries (no agent takes over another's responsibility; the negotiation layer makes no decisions)
- correctness against the specs and `scenarios.md`
- contracts respected
- tests verify actual behavior (exact expected values for deterministic logic; LLM behavior through constrained interfaces and deterministic validation)
- documentation matches the code
- no unintended coupling
- no scope creep (no cost/price, no Scenario 5, no future-scope components)

---

## 10. Git and integration strategy

- **Branches:** protected `master` (not renamed to `main`, P0-17); short-lived branches `dev1/phase-N-topic` and `dev2/phase-N-topic`, rebased on `master` before a PR.
- **Parallel case:** both branch from the phase baseline, work independently with tests, open PRs, and merge in either order after review. The second developer rebases and re-runs tests.
- **Dependent case:** the first developer implements the foundation, tests, merges; the second developer pulls and then builds the dependent work. Use this pattern **only** where a real dependency exists (paired step 0 items, migrations 001 then 002, Phase 5 contract alignment).
- **Reviews:** every PR is reviewed by the other developer, including a local test run. A `/code-review` pass may assist but does not replace human review.
- **Baseline:** after both merges and a full test run on `master`, tag `phase-N`.
- **Coordination files** (edit only via small, quick PRs): `backend/app/main.py` (router registration), `requirements.txt`, Alembic `versions/`, `CLAUDE.md`, `DECISIONS.md`, this roadmap.
- **Claude Code sessions:** each session edits only files in its assigned work package. Anything else is a request to the other developer.
- **Git workflow specifics:** protected shared `master`, merge by PR reviewed by the other developer (P0-17). Who is Dev 2 is still to be recorded (D12).

---

## 11. Folder and documentation ownership

- The author of a change to a folder updates its `README.md` in the same PR; the reviewer checks it against the code.
- Ownership is per phase and rotates. Example: `negotiation/` belongs to Dev 2 in Phase 1 (protocol) and to Dev 1 in Phase 3 (persistence service).
- A README is never left describing code that does not exist yet, and a removed component is removed from its README.
- At every phase gate: code, documentation and architecture must agree.
- Project-level documents: do not rewrite the finalized specification. Keep planned architecture, implemented architecture and future scope clearly distinguished. `docs/` status describes what is actually built. Update `DECISIONS.md` when a decision is finalized and this roadmap's checklist and decision log after each phase.

---

## 12. Risks

| Risk | How the roadmap handles it |
| --- | --- |
| One developer blocked waiting | Phases are dependency-cut; waits are limited to named items (migration order, paired steps). |
| Divergent implementations of a shared piece | Paired or contract-first steps (`agents/base`, C8, C9). |
| Migration conflicts | Ordered 001/002 with one author each, created one at a time. |
| Shallow reviews | Explain-back plus running the other's tests. |
| A2A / Ollama incompatibility (D13) | Spike in Phase 2, before agents depend on it. |
| Unequal load in a phase | Slices sized to be comparable; rebalance after Phase 3 if needed. |
| Small local model unreliability | Fake-LLM tests plus deterministic validation; one bounded real-Ollama smoke test. |
| Doc drift | READMEs updated in each PR and checked at every gate. |
| Frontend merge conflicts | Separate route directories and separate API client modules. |
| Contract drift | Contracts settled in Phase 0; changes via reviewed contract PRs only. |
| Scope creep (cost/price, Scenario 5, future agents) | Section 5 checked in every review. |
| Scenario fixture data undefined | D1: fixture spec agreed in Phase 0. |

---

## 13. Recommended Phase 0

Both developers work through these together. Nothing is implemented until it is done.

1. **Joint read-through:** both read `CLAUDE.md`, `DECISIONS.md`, `system_spec.md`, `scenarios.md`, `agent_operations.md` and `database_schema.md`, then each explains the end-to-end flow back to the other.
2. **Answer D1–D13** (Section 14) and record them in `DECISIONS.md`. D8 (what approval executes), D9 (who sends AGREEMENT_PROPOSED/COMMIT, timeouts), D12 (Git workflow and PR rules) and D1 (the X1 fixture spec) are the most important.
3. **Contracts:** Dev 1 drafts C1, C6 and the error format; Dev 2 drafts C2, C4 and C7; each reviews the other's. C3, C5, C8, C9 are assigned drafting points as scheduled in Section 8.
4. **Baseline repo (small and shared, taking turns: one drives, the other reviews):** remove the stale test, pin dependencies (adding SQLAlchemy, Alembic, a Postgres driver and the A2A SDK as agreed), add `pytest.ini` and `.env.example` (no `docker-compose.yml` database: Postgres is on Neon, P0-03), and `core/config.py` (database URL, Ollama URL and model name configurable).
5. **Documentation and workflow:** write the folder README template, agree branch/PR/tag conventions, and agree the Claude Code rule that a session edits only files in its assigned work package.

---

## 14. Open decisions (all UNRESOLVED until answered)

| # | Decision | Recommendation from the roadmap (not yet approved) |
| --- | --- | --- |
| D1 | Seed data: SmartPhone X1 / Display Assemblies data matching `scenarios.md`. Who defines the exact BOM and quantities? | The team writes one small fixture spec in `docs/`, agreed in Phase 0. |
| D2 | BOM depth | Single-level |
| D3 | Basic capacity check in scope (scenarios 3 and 7 mention capacity) | Keep a minimal check |
| D4 | Postgres deployment | **Resolved (P0-03):** PostgreSQL on Neon; no Docker Compose database |
| D5 | A2A layout | Three A2A endpoints in one FastAPI app, not three processes |
| D6 | Folder documentation file name | `README.md` in every folder |
| D7 | Alembic scope | The 25% tables only |
| D8 | What "approve -> execute/commit" does (e.g. commit reservations, mark plan approved) | Needs your definition |
| D9 | Who sends AGREEMENT_PROPOSED / COMMIT, and round/attempt timeouts | Propose in the Phase 0 negotiation contract, then confirm |
| D10 | How scenario state resets between demo runs | Re-seed function |
| D11 | Frontend tooling: package manager; whether to add browser E2E tests | Vitest for units, plus an API-level E2E test in pytest; browser E2E only if wanted |
| D12 | Git workflow: protected branch, PR review rules, who is Dev 1 and Dev 2 | **Partly resolved (P0-17):** PR-reviewed protected `master`. Dev 2 identity still to record |
| D13 | Whether the A2A SDK works cleanly with the OpenAI Agents SDK and Ollama's no-reasoning mode | Verify in the Phase 2 spike, not by assumption |

Other items still open from the project documents: how a simulation event applies its change to owning tables (directly or through the owning service), and the attempt-counter owner (Phase 5, C8).

---

## 15. Milestones

| M | After | How both developers contribute | Demonstrable |
| --- | --- | --- | --- |
| M1 | Phase 1 | Dev 1: MRPII flow. Dev 2: negotiation protocol and LLM client. | Deterministic MPS -> MRP -> shortage on the X1 fixture; fake-agent exchange reaches agreement or `FAILED`. |
| M2 | Phase 2 | Each persists the other's domain; Dev 1 proves A2A, Dev 2 proves seed and UI shell. | Clean-DB setup, seeded data, A2A echo, frontend skeleton. |
| M3 | Phase 3 | Dev 2: order -> plan slice. Dev 1: negotiation/supplier slice. | UI order -> MRP shortage from the database; persisted, round-limited negotiation. |
| M4 | Phase 4 | Dev 2: Inventory Agent. Dev 1: Purchasing Agent. Paired base. | Agents negotiate a shortage to agreement or `FAILED` with audit records. |
| M5 | Phase 5 | Dev 1: Planning Agent. Dev 2: approval and replan. | Scenario 1 in the UI with approval and replanning. |
| M6 | Phase 6 | Dev 1: scenarios 3, 6, 7. Dev 2: scenarios 2, 4. | Six in-scope scenarios pass end to end. |
| M7 | Phase 8 | Joint review, cross-run tests, demo. | Complete 25% demo with audit, docs and tests. |

The end-to-end flow both developers must eventually understand: Customer Order -> Production Planning -> MRP -> Inventory -> Shortage -> Negotiation -> Agreement / FAILED -> Updated Plan -> Deterministic Validation -> Human Approval -> Execute / Replan -> Simulation / Scenarios -> Audit / UI.
