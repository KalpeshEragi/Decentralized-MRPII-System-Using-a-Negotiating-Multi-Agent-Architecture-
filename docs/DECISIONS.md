# Decentralized MRPII — Decisions

This file records confirmed decisions and unresolved choices.

Claude must not silently make a consequential architectural decision when it is unresolved.

## Confirmed

### Decentralization
Agents are autonomous decision-makers with their own goals, preferences, constraints, state, proposals, and decisions.

Shared infrastructure is allowed; centralized decision-making is not.

### Agent Ownership
- Production Planning Agent → planning, MPS/MRP requirements, priorities, replanning
- Inventory Agent → availability, allocation, reservations, safety stock
- Purchasing Agent → procurement, supplier evaluation, procurement negotiation

One agent must not silently take over another agent's responsibility.

### Deterministic Logic
BOM, MPS, MRP, inventory calculations, reservations, constraints, transactions, and persistence must remain deterministic.

### LLM Role
LLMs support reasoning, context interpretation, negotiation, proposals/counter-offers, coordination, and rationale.

LLMs are not business truth. Raw LLM output must not directly mutate business state; validate structured output first.

### Negotiation
Negotiation is multi-factor, not price-only.

Possible factors:
- quantity
- delivery/lead time
- priority
- availability
- safety-stock limits
- supplier capacity
- agent constraints/preferences

Goal: mutually feasible agreement, not a centralized winner.

### Supplier Scope
For the 25% milestone, suppliers are represented by data/services, not a Supplier Agent.

### Simulation
Simulation is a What-If environment. It injects disruptions; agents determine the response.

### 25% Scope
The 25% milestone is a vertical slice, not 25% of every module.

### 25% Implementation Decisions (finalized)
- **Stack:** FastAPI backend, OpenAI Agents SDK, Next.js + React frontend, PostgreSQL with SQLAlchemy + Alembic.
- **LLM:** `qwen3.5:4b` via Ollama is the default. Model name and Ollama URL must be configurable. Normal negotiation calls use fast/no-reasoning mode. The LLM only reasons and proposes.
- **Communication:** A2A for agent-to-agent negotiation, kept focused. No event bus, no extra microservices or distributed infrastructure.
- **Orders:** No Sales Agent. The tester creates customer orders through the application/API, which hands them to the Production Planning Agent.
- **Plan ownership:** The Production Planning Agent owns the production plan. It must not override other agents' decisions or constraints.
- **Negotiation path:** Inventory and Purchasing negotiate through the Negotiation Engine, which manages protocol, sessions, messages, offers and agreement records but makes no business decisions. The result goes back to Planning.
- **Factors (25% scope):** material quantity, required date, delivery date/lead time, inventory impact, production priority. Preferences/weights are designed at implementation time. The offer terms that travel in messages are only `quantity`, `required_date`, `delivery_date`, `priority` (P1-05); lead time comes from supplier data and inventory impact is calculated deterministically.
- **Cost/price is future scope.** For the 25% implementation there is no cost/price in negotiation factors, supplier forms, offers/counter-offers, acceptance/rejection criteria, or LLM negotiation reasoning. It will be revisited after the 25% milestone.
- **Supplier:** No Supplier Agent. The Purchasing Agent talks to a supplier communication interface. In the demo the tester plays the supplier through a UI and provides supplier-side responses only. Purchasing decides accept/reject/counter autonomously.
- **Agreement:** agents accept, hard constraints satisfied, preferences/bounds satisfied, feasible resolution of the shortage, recorded by the negotiation system. Deterministic validation is the authority on feasibility.
- **Failure:** A session can end `FAILED` (no feasible agreement after multiple rounds). `FAILED` is a distinct end status, not `REJECTED`, `ABORTED` or `EXPIRED`. The shortage stays unresolved, the plan is not updated, and the failure is recorded and visible in the dashboard/decision log.
- **Human approval:** After deterministic validation, the tester approves (execute/commit) or rejects (reconsider/replan) the plan. The human is not the planner or negotiator.
- **Purchase orders:** `purchase_orders` and `purchase_order_items` are out of scope. The negotiation agreement is the purchasing outcome. Approval and activity are recorded through agreement/audit records.
- **Parked code:** Sales, Production and Warehouse agent stubs are removed from the repository and are not rebuilt in the 25% (P0-01).
- **A2A:** Use the official A2A Python SDK with HTTP endpoints for the core agents. No fake/minimal A2A-compatible layer, no event bus.
- **Shortage flow:** The Inventory Agent detects a shortage and initiates procurement negotiation with the Purchasing Agent over A2A, sending the shortage/procurement context. Purchasing handles supplier interaction and negotiation. Planning receives the resulting agreement or `FAILED` result and uses it for replanning/plan evaluation.
- **Supplier UI:** Structured supplier-response form with quantity, delivery date/lead time and an optional message. **No price/cost field (see Cost/price above).** The tester acts only as the supplier, one response per round. Purchasing alone decides ACCEPT/REJECT/COUNTER. The tester does not end the negotiation.
- **Round limit:** Max 3 supplier rounds per negotiation session, shown as "Round N of 3". No agreement within 3 rounds → session ends `FAILED`.
- **Human rejection:** Rejecting a plan automatically triggers Planning to replan, and the new plan returns to human approval. Max 2 planning attempts (each with at most one negotiation session of ≤3 rounds). If attempt 2 yields no feasible plan/agreement, automatic replanning stops and human intervention is required. No infinite loops.
- **Available quantity:** `available_quantity = on_hand − reserved − safety_stock` (floored at 0). Incoming/scheduled receipts are not part of it. MRP netting adds them separately (`projected_available_quantity`).
- **Scenarios:** `implementation_25%/scenarios.md` is the unmodified source of truth for the seven finalized scenarios. **Scenario 5 (Supplier Price Increase) is future scope and out of scope for the 25% implementation**: no supplier price-increase behavior and no cost/price fields or negotiation logic to support it. Scenarios 1, 2, 3, 4, 6 and 7 are implemented. For Scenario 4, the "lead time/cost" constraint is implemented as lead time only, with no cost behavior.

### Phase 0 Decisions (confirmed 2026-09-30)
This is a summary. The detailed, authoritative record of each P0 item (problem, options, rationale, status) and the open Phase 1 prerequisites (P1-xx) is `docs/DECISIONS.md`.

- **P0-01 Parked stubs:** the empty Sales/Production/Warehouse agent files are deleted.
- **P0-02 Negotiation initiation:** the Inventory Agent detects the shortage and initiates Inventory → Purchasing negotiation over A2A. Planning receives the negotiated result (agreement or `FAILED`). Planning's MRP net requirement and Inventory's shortage detection both come from the same deterministic services. This supersedes the Planning → Purchasing REQUEST in `system_spec.md` §2.
- **P0-03 Database hosting:** PostgreSQL hosted on **Neon** (serverless), as in `database_schema.md`. No local Postgres container. The backend connects through the configurable `DATABASE_URL`. How tests get an isolated database is decided in Phase 2 (C2).
- **P0-04:** `negotiation_sessions.completed_at` is nullable; set only when the session reaches an end status.
- **P0-05 Message types vs session statuses:** message types are `REQUEST`, `OFFER`, `COUNTER_OFFER`, `ACCEPT`, `REJECT`, `AGREEMENT_PROPOSED`, `COMMIT`. Session statuses are `INITIATED`, `NEGOTIATING`, `AGREEMENT_PROPOSED`, `COMMITTED`, `REJECTED`, `ABORTED`, `EXPIRED`, `FAILED`.
- **P0-06:** `negotiation_offers.valid_until` is nullable; if timeouts are adopted (D9) it is set from the round/session deadline.
- **P0-07:** `PROJECT_STATUS.md` describes the actual repository state.
- **P0-08:** `CLAUDE.md` paths point at `dev_docs/`.
- **P0-09 Agent policy storage:** per-agent policy items are stored in `agent_state.negotiation_rules.policy` (JSONB); no extra columns.
- **P0-10 Fixture data (D1):** one SmartPhone X1 fixture spec is written jointly in `docs/`, with values chosen so scenarios 1, 2, 3, 4, 6, 7 yield their expected outcomes. No fixture values are invented before it exists.
- **P0-11 Production lead time:** a per-product production lead time is needed to derive MPS start and component required-by dates. Storage (`core.items` column or fixture/config value) is chosen in C2.
- **P0-12 Scheduled receipts:** committed negotiation agreements (agreed quantity and delivery date) are the scheduled receipts used for projected availability. Purchase orders stay out of scope. Read path defined in C2/C4.
- **P0-13 MRP columns:** `planning.mrp_requirements` gains `scheduled_receipts` and `projected_available_quantity`; `available_inventory` holds `available_quantity`.
- **P0-14 Capacity data:** if D3 keeps a minimal capacity check, capacity is one `capacity_per_day` value per product in the fixture/config. No `production.*` tables.
- **P0-15 Priority scale:** integer 1–5, `1` = highest.
- **P0-16 Dates:** the domain plans in whole days (`DATE`). Column mapping (`DATE` columns or midnight UTC timestamps) is chosen in C2.
- **P0-17 Git:** `master` is the integration branch (not renamed to `main`). Work happens on short-lived branches from `master`, merged by PR (since 2026-09-30 single-developer: `phase-N-topic`).
- **Single developer (2026-09-30):** the project continues with one developer under `dev_docs/implementation_25%/single_developer_roadmap.md`, which replaces the two-developer roadmap. All decisions above are unchanged.

---

## Unresolved

### Phase 1 Prerequisites
Detailed in `docs/DECISIONS.md`.
- **Confirmed (2026-09-30):** P1-02 single-level BOM; P1-03 minimal capacity check (`planned_quantity <= capacity_per_day × production_lead_time_days`); P1-04 Purchasing sends `AGREEMENT_PROPOSED`, `COMMIT` only after human approval, no timers or automatic expiry (bounded by 3 rounds and 2 planning attempts); P1-07 round semantics (one round = Purchasing offer/counter + supplier response, max 3; supplier interface or Purchasing `REJECT`, even before round 3, ends the session `REJECTED`; round limit without agreement → `FAILED`; both → outcome `FAILED` for Planning; sender type `SUPPLIER_INTERFACE` is the supplier form, not an agent); P1-05 `OfferTerms` = quantity, required_date, delivery_date, priority; P1-04 `COMMIT` only by the approval workflow after human approval; P1-08 Phase 1 = deterministic core without database.
- **Proposed:** P1-01 SmartPhone X1 fixture (awaiting approval).
- **Phase 2 (2026-09-30, P2-01):** DATE columns for day buckets; production lead time / capacity as fixture/config; nullable agent ids + type columns for supplier-side messages; 25% tables only; `TEST_DATABASE_URL` for DB tests; committed agreements are the scheduled receipts; A2A spike = three endpoints in one app.
- **Phase 3 (2026-09-30, P3-01, PROPOSED):** Planning → Inventory is an interim in-process call; the result reaches Inventory then Planning through routing; round exhaustion always ends `FAILED`; split procurement not supported in one session (open for Phase 4); LLM failure → recorded, agent's own deterministic policy decides; `OllamaClient` as runtime proposer (Agents SDK not in the path, D13); C6 state = the agent's latest negotiation; working audit types and requisition statuses.
- **Unresolved:** P1-06 Planning ↔ Inventory allocation semantics (interim in P3-01); P1-07 supplier message storage (Phase 2); the approval workflow that performs `COMMIT` (C8, Phase 4).

### Event Bus
**Status: Unresolved.** Introduce only if required.

---

## Decision Rule

When a choice is unresolved:

1. Inspect the code and project docs.
2. Preserve the existing implementation where reasonable.
3. Avoid unnecessary dependencies or architectural changes.
4. Surface material unresolved choices before making consequential changes.
5. Record important final decisions here.