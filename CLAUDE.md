# Decentralized MRPII — Claude Code Guide

## Project

A research prototype of a **simulated MRPII manufacturing environment** run by six autonomous, negotiating agents
with LLM-assisted reasoning. Planning decisions are distributed across agents instead of one central planner.

This is a manufacturing planning system, not a chatbot, a workflow script, or a conventional centralized ERP/MRP.
There is no real factory: the database and the simulation logic represent the factory state.

## The six agents

| Agent | Owns | Must not |
| --- | --- | --- |
| **Sales** | Customer conversation, order details, customer records, inquiries/options shown, explicit confirmation, customer-facing order status | Calculate dates/quantities/feasibility, invent commitments, contact Inventory/Purchasing |
| **Planning** | MPS, BOM explosion, MRP/material requirements, capacity, scheduling, feasibility, replanning, the production plan | Change stock, storage, supplier or workforce records directly; act as messenger for every message |
| **Inventory** | Stock records, availability, reservations, safety stock, receipts/issues to stock | Change the plan, choose suppliers, promise storage space |
| **Purchasing** | Supplier options, procurement negotiation, procurement commitments, supplier delays | Change stock or the plan directly |
| **Warehouse** | Receiving capacity, storage space, material movement, issue to production, finished goods, shipment hand-off | Change stock quantities it does not own, change the plan |
| **HR** | Worker availability, skills, shifts, absences, workforce commitments | Change the plan or other agents' records |

Details per agent: `dev_docs/<agent>_agent/`. Suppliers are **simulated adapters, not agents**.
Do not add agents beyond these six.

## Decentralization invariants

- Shared infrastructure is fine; centralized decision-making is not.
- Each agent keeps its own goals, preferences, constraints, negotiation state, offers and decisions.
- Each agent owns its domain data. Others may read authorized data; they never write another agent's records.
- One agent never silently takes over another agent's responsibility.
- Infrastructure (event channel, negotiation layer, simulator) routes, validates, stores and times out.
  It never decides outcomes or overrides an agent's constraints.

## Communication

Two different mechanisms. Do not mix them.

1. **Publish–subscribe events** for shared facts: an event announces something that happened
   (for example `OrderConfirmed`, `SupplierDeliveryDelayed`). Only subscribed agents receive it.
   Subscriptions are a static, documented list.
2. **Private negotiation** among the relevant agents only: Request, Offer, Counter-offer, Accept/Reject,
   Agreement. Individual negotiation messages are never broadcast; only the agreed outcome is published as an event.

Event rules (details in `dev_docs/architecture/`):
- Save the event before delivering it; save a business change and its event in one transaction.
- Delivery can happen more than once: every consumer is idempotent (deduplicates by event id).
- Track delivery and retry state per subscriber; nothing is silently lost after a restart.
- A common envelope: event id, type, time, publisher, entity ids, version, correlation id.
- Consumers ignore events older than the state they already hold.

Event storage/delivery technology is an **open decision** (PostgreSQL events table is the leading option).
Do not add Kafka, RabbitMQ, Redis or similar without explaining why and getting approval.

## Resource commitments

- The agent that owns a resource is the only one that commits it, with an atomic check-and-update:
  Inventory (stock), Warehouse (space/receiving), Purchasing (supplier quantity), HR (workforce), Planning (plan/MPS).
- Never double-commit stock, space, supplier quantity or workforce capacity.
- Tentative holds may expire. A commitment that changes facts publishes an event; negotiations built on
  stale facts are rechecked, reopened or expired.
- Keep three things separate: **hard constraints** (never violated, never outweighed), **dependencies**
  (work waits for another result), **priority** (orders ready work at a receiving agent).
- Priority is about competing requests at one agent, not about ranking customers or agents. The receiver checks
  urgency against trusted data, never a sender's claim. Independent negotiations run concurrently.
- Every quantity change follows the rules in `dev_docs/architecture/quantity_accounting.md`.

## Order lifecycle rule

Customer acceptance, resource/plan commitment, and production start are **separate states and events**.
Never tell a customer production is secured just because they accepted an option. Sales only repeats
validated, current information from Planning.

## Deterministic vs LLM

- Deterministic code owns business truth: BOM, MPS, MRP, quantities, reservations, capacity, workforce,
  storage, constraint validation, transactions.
- LLMs help agents with context, negotiation proposals, coordination and short rationales.
- LLM output never mutates business state directly: it is parsed, validated, and then applied by code.
- If the model fails or times out, the agent's deterministic policy keeps the result correct.

## Shared AI model

- One shared model via Ollama, configured in `backend/app/core/config.py` (currently `qwen3.5:4b`),
  model name and URL configurable. Six agents share it; no per-agent model instances.
- No custom model-resource allocator until measurements show a need. Log wait time, response time and failures.
- The AI request queue and an agent's negotiation-request queue are different things.

## Simulation

- Two separate operations: **configure** the starting factory state, and **trigger** an event or scenario.
- A trigger changes simulated facts and publishes the event through the normal path. It never tells agents
  what to answer and never bypasses their decisions.
- Same state + same inputs = same result (good for tests). Different state must be able to give a different result.
- Randomness only if useful, controlled and seedable. Never to make the demo look smart.
- Reset/replay leaves no events, reservations or state from the previous run.

## Scope boundary

Inside: six agents, MRPII calculations, pub-sub events, private negotiation, end-to-end order flow
(request → feasibility → options → confirmation → commitment → production progress → delivery),
disruptions and cancellations, concurrency tests (1 → 10 → 20 → target 100 orders, measured, not promised),
demo control panel and timeline.

Outside: real suppliers or payments, physical machines/warehouse equipment, real HR/payroll systems,
dynamic AI-resource allocation, a general-purpose factory simulator, a Supplier Agent.

## Project knowledge (read before non-trivial work)

```
dev_docs/
  README.md            index of all docs
  ROADMAP.md           build phases, current phase, phase gates
  DECISIONS.md         confirmed and open decisions
  architecture/        high-level architecture, system design, backend API, pub-sub, negotiation,
                       quantity accounting, demo
  sales_agent/  planning_agent/  inventory_agent/  warehouse_agent/  hr_agent/  purchasing_agent/
  supplier/            Supplier Service and supplier chat (not an agent)
  PROJECT_STATUS.md    what is actually built and tested
  *.png                diagrams drawn by the developer
```

Source of truth order: current code → current `dev_docs/` → diagrams → research notes.
A documented or drawn component is not automatically implemented. When code and docs disagree, inspect both,
keep working behavior, and report the difference. Never silently pick a resolution.
Do not use web search for project facts; use it only for explicitly requested research.

## Purchasing Agent (built standalone)

- Built from scratch as an independently runnable, tested agent (`backend/app/purchasing_agent/`, with
  `supplier_service/` and the shared `negotiation_engine/`). Spec and tickets: `.scratch/purchasing-agent/`.
- Unfinished agents are replaced by test inputs/mocks. Do not claim real multi-agent integration until it exists.
- Rules: `dev_docs/purchasing_agent/`; price use in selection: `dev_docs/adr/ADR-002-price-in-supplier-selection.md`.

## Technology (confirmed)

FastAPI backend, PostgreSQL on Neon (SQLAlchemy + Alembic), Next.js + React frontend, Ollama for the LLM.
Open decisions live in `dev_docs/DECISIONS.md`. Do not silently choose or replace a technology
(event storage, agent framework, transport, ORM, deployment). Ask first.

## How Claude works here

**Session start:** read `dev_docs/ROADMAP.md`, find the current phase, and work only on that phase.

**Every non-trivial task:**
1. Inspect the relevant code and docs; find what already exists.
2. Explain the gap or conflict in plain language.
3. Recommend options with what we gain and lose. The developer decides.
4. Explain the small change before making it.
5. Implement the smallest complete step; preserve unrelated working behavior.
6. Run the relevant tests; never claim something works without running or checking it.
7. Update the relevant doc when architecture, boundaries, contracts, events or scope change.
8. Stop for review.

**Communication style:** plain, simple language. Introduce a technical term only when it helps, and explain it.

**Git:** Claude never commits, pushes, merges or rewrites history unless asked for that exact operation.
The developer reviews and runs `git add` / `commit` / `push`. Branches are short-lived, from `master`, merged by PR.

**Decisions:** never silently change an agreed decision. If you find a flaw, explain it and recommend a fix first.

## Code quality

- Simple, readable, modular code: meaningful names, small functions, useful comments, safe error handling.
- Reuse existing utilities and patterns first. Every new agent follows the Sales Agent's folder layout.
- No speculative features, premature microservices, unnecessary infrastructure, or duplicated business logic.
- Tests: a small set of strict, high-value tests per business rule; add more only for distinct failure modes.
- Every meaningful folder has a short `README.md` describing the code that actually exists.

## Documentation map

- `CLAUDE.md`: stable rules for how Claude works (keep under 200 lines, no detailed specs).
- `dev_docs/`: architecture, agent designs, decisions, roadmap.
- Folder `README.md` files: the actual code in that folder.

## Non-negotiables

- Decentralized decisions and strict agent ownership.
- Events for shared facts; private negotiation for deals; only outcomes are published.
- Owner-only, atomic resource commitments; no double booking.
- Deterministic business calculations; LLMs never control business state.
- Simulation changes conditions; agents decide responses.
- Customer acceptance ≠ commitment ≠ production start.
- No Supplier Agent; no new infrastructure without approval.
- When in doubt: inspect first, ask, keep it simple.
