# Decentralized MRPII — Implementation Plan

> High-level plan. The phase-by-phase execution plan is `dev_docs/implementation_25%/single_developer_roadmap.md`; where they differ, follow the roadmap.

## Goal

Build and validate the 25% vertical slice of the decentralized MRPII system before expanding to the full architecture.

Core flow:

Customer Order
→ Planning
→ MPS/MRP
→ Inventory
→ Procurement/Negotiation
→ Agreement
→ Initial Plan
→ Disruption
→ Re-evaluation
→ Revised Plan

## Phase 1 — Understand the Existing System

- Inspect repository structure and entry points.
- Inspect backend, frontend, database, agents, negotiation, LLM, simulation, and tests.
- Compare actual code with `dev_docs/implementation_25%/`.
- Identify implemented, partial, planned, and missing components.
- Record findings in `PROJECT_STATUS.md`.

Do not modify application code during this phase.

## Phase 2 — Align Architecture

Validate the actual implementation against the documented architecture.

Preserve existing working structure unless a change is clearly required.

Do not introduce frameworks or infrastructure merely because they appear in the target architecture.

## Phase 3 — Deterministic MRPII Foundation

Implement or refine:

- BOM explosion
- MPS
- MRP
- Inventory availability/reservations
- Material requirements
- Constraint validation
- Database transactions/state persistence

Business calculations must remain deterministic.

## Phase 4 — Milestone Agents

Implement/refine:

### Production Planning Agent
Owns planning, MPS/MRP requirements, priorities, shortages, and replanning.

### Inventory Agent
Owns availability, allocation, reservations, and safety-stock constraints.

### Purchasing Agent
Owns procurement, supplier evaluation, and procurement negotiation.

Agents must respect each other's responsibilities.

## Phase 5 — Negotiation

Implement agent-to-agent negotiation using the project's chosen communication approach.

Negotiation should consider multiple factors such as quantity, delivery, lead time, priorities, constraints, and availability.

The negotiation layer may manage communication and protocol state, but must not centrally decide outcomes.

## Phase 6 — Initial 25% Flow

Demonstrate:

Customer Order
→ Planning
→ MPS/MRP
→ Inventory Evaluation
→ Procurement
→ Negotiation
→ Agreement
→ Feasible Plan

Validate the final result using deterministic business rules.

## Phase 7 — Disruption & Replanning

Introduce a What-If disruption such as supplier delay, demand change, quantity reduction, or due-date change.

Expected flow:

Disruption
→ Affected Agents Re-evaluate
→ Communicate
→ Negotiate
→ Validate
→ Revised Plan

Agents decide the response; the simulation layer only injects the event.

## Phase 8 — Audit & Testing

Record important agent actions, messages, offers, agreements, decisions, and replanning events.

Test deterministic logic, agent boundaries, negotiation, disruption handling, and the complete 25% flow.

## Phase 9 — Review

Remove unnecessary complexity and duplication.

Verify:

- Decentralized decision-making
- Agent boundaries
- Deterministic business logic
- Validated LLM outputs
- Negotiation correctness
- Documentation/code alignment