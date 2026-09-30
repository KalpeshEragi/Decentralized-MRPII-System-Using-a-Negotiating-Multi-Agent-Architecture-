Decentralized MRPII — Claude Code Guide

Project

Decentralized MRPII system with autonomous negotiating multi-agents and LLM-assisted reasoning.
Goal: distribute manufacturing-planning decisions across autonomous agents rather than one centralized planner.

The project is a manufacturing planning system—not merely a chatbot, workflow automation system, or conventional centralized ERP/MRP application.

System Overview

Target system

Frontend → Application/API → MRPII Domain → Autonomous Agents
                         ↘ Negotiation / Communication
Deterministic Services ←→ PostgreSQL ←→ Simulation / Audit
LLM layer supports agent reasoning; it is not business truth.

Target business functions: Sales, Production Planning, Inventory, Purchasing, Warehouse, Production.
Frontend covers dashboards, orders, planning/monitoring, agent activity, negotiation views, and simulation/what-if views.

Current 25% vertical slice

Customer Order → Planning → BOM/MPS/MRP → Inventory
→ Procurement/Negotiation → Agreement → Initial Plan
→ Disruption → Re-evaluation → Negotiation → Revised Plan

Current agents: Production Planning, Inventory, Purchasing.
Supporting scope: PostgreSQL, orders/BOM, MPS/MRP, inventory availability, supplier data/service, multi-factor negotiation, LLM reasoning, simulation/disruptions, audit/decision logging, basic dashboard.
Supplier = data/service, not an autonomous agent for this milestone. Sales, Warehouse, Production, Supplier, and expanded functionality are future scope unless explicitly requested.

Project Knowledge

Before non-trivial MRPII, agent, database, negotiation, simulation, or architecture work, inspect the relevant repository docs, especially:

dev_docs/implementation_25%/
  single_developer_roadmap.md (execution roadmap: phases, current phase, working rules)
  system_spec.md
  scenarios.md               (source of truth for scenarios; do not modify)
  agent_operations.md
  database_schema.md
  table_relations.md
dev_docs/
  DECISIONS.md               (confirmed and unresolved decisions)
  tech_stack.md              (early plan; superseded by DECISIONS.md)
  System Architecture.png
  Relational Database Schema Diagram.png
docs/contracts/              (shared contracts between the two developers)

Use these detailed specifications instead of guessing or duplicating them in CLAUDE.md.

Source of Truth

Prefer: actual source code/current repository → current repository docs → architecture/schema plans → research notes.
A planned or diagrammed component is not automatically implemented.
When code and docs disagree: inspect both, preserve working behavior, and surface the discrepancy. Never silently invent a resolution.
For project-specific architecture/schema/status, use repository evidence first. Do not use web search as a substitute; external research is only for explicitly requested or genuinely necessary separate research.

Decentralization Invariants

Shared infrastructure is acceptable; centralized decision-making is not.
Agents retain their own goals, preferences, constraints, negotiation state, proposals/offers, and decisions.
A shared negotiation layer may handle sessions, participants, routing, validation, protocol state, persistence, and timeouts—but must not centrally decide outcomes, override agent constraints/preferences, or replace autonomy.
One agent must not silently take ownership of another agent's business responsibility.

Agent Boundaries

Production Planning Agent: owns MPS/MRP requirements, production priorities, material requirements, planning objectives. Can plan, identify shortages, request inventory/procurement, propose quantities/dates, negotiate, and replan. Cannot directly modify inventory, select suppliers for Purchasing, alter another agent's state, or bypass constraints.

Inventory Agent: owns availability, allocation, safety-stock constraints, and inventory negotiation constraints. Can check stock, calculate availability, propose allocation, negotiate quantities, and reserve/release through the appropriate service. Cannot change production planning, select suppliers, or make purchasing decisions.

Purchasing Agent: owns procurement, supplier evaluation/negotiation, procurement terms, and quantity/delivery/lead-time trade-offs. Can evaluate supplier data, compare offers, negotiate, and create procurement requirements/results through the appropriate service. Cannot directly modify inventory, directly change production plans, or override another agent's constraints.

Deterministic vs LLM

Keep business truth/calculations deterministic.
Deterministic services/domain logic: BOM explosion; MPS/MRP; inventory/reservation calculations; capacity calculations; constraint/business-rule validation; database transactions/state persistence.
Agents/LLMs: contextual and goal-oriented reasoning; negotiation; multi-factor proposals/counter-offers; negotiation-context interpretation; coordination; concise decision rationale.
LLMs are not authoritative for inventory, BOM, suppliers, capacity, orders, database state, or hard constraints. Never let raw LLM output directly mutate business state; validate structured output first.

Negotiation

Negotiation is multi-factor, not price-only. Relevant factors may include quantity, delivery date, lead time, priority, inventory availability, safety-stock limits, supplier capacity, production requirements, deadlines, and agent preferences/constraints.
Objective: a mutually feasible plan, not a centralized winner.
Core protocol concepts:

REQUEST / OFFER / COUNTER_OFFER / ACCEPT / REJECT
AGREEMENT_PROPOSED / COMMIT

Check current docs/implementation before changing protocol/message contracts.

Agent State

Agent state represents decision/negotiation context:

current_goal, preferred_terms, reserved_limits, initial_proposal,
own_offer_history, opponent_offer_history, dialogue_history,
negotiation_rules, current_task

Do not duplicate the whole business database inside agent state.

Simulation

Simulation is a What-If testing environment: Scenario → Disruption/Event → Agent Re-evaluation → Communication + Negotiation → Revised Plan.
Possible disruptions discussed: supplier delay, demand/new-order increase, supplier quantity change (price change is future scope), inventory reservation change, customer due-date change.
Use current repository/docs for exact milestone scenarios. The Scenario Manager injects events; agents decide the response.

Development Workflow

For non-trivial tasks: (1) inspect relevant code/docs and scope; (2) determine what already exists; (3) make a concise plan; (4) implement the smallest complete solution; (5) preserve unrelated behavior; (6) run relevant available tests/checks; (7) review for unnecessary complexity; (8) update docs when architecture/schema/protocol/scope materially changes.
Do not create or modify unrelated files. Do not build future architecture merely because it appears in a diagram.

Implementation Workflow

Single developer working with Claude Code. At session start, read dev_docs/implementation_25%/single_developer_roadmap.md, find the current phase in its Section 1 checklist, and work only on that phase.
Claude implements, tests, shows the changes and stops. The developer reviews and runs git add / commit / push. Claude never commits, pushes, merges or rewrites history unless explicitly asked for that exact operation.
Branches: short-lived phase-N-topic branches from master, merged by PR. Contracts in docs/contracts/ change before the code that depends on them.
Follow the roadmap's phase gate (Section 2). Do not start a phase before the previous gate is met.

Code Quality

Prefer simple, readable, modular, maintainable, efficient, extensible code.
Avoid unnecessary abstractions/classes/files, duplicated business or negotiation logic, premature microservices, speculative features, unnecessary infrastructure, or clever code that hurts clarity.
Do not optimize for line count alone. Prefer concise code when it remains clear and maintainable. Reuse existing utilities/patterns first.

Technology Decisions

Do not silently choose or replace unresolved technology. Verify repository/docs before deciding on agent framework, LLM/runtime/model, frontend, A2A/transport, event bus, ORM/migrations, or deployment/containerization.
Previously discussed alternatives include MESA/SPADE/PADE vs OpenAI Agents SDK, earlier UI approaches vs Next.js, and Llama/Ollama/Qwen. These are not interchangeable assumptions.
If a material choice remains unresolved, record it in dev_docs/DECISIONS.md when appropriate and ask before a consequential change.

Code Intelligence

If Graphify is installed/configured, use the repository's actual Graphify workflow for structural/code-dependency navigation. Treat it as code-structure information, not business truth. Do not invent Graphify commands/configuration.

Documentation

CLAUDE.md → stable rules/how Claude works
dev_docs/implementation_25%/ → detailed project/domain specifications and the single-developer roadmap
dev_docs/ → decisions (DECISIONS.md), project status (PROJECT_STATUS.md), high-level plan
docs/ → shared contracts (docs/contracts/) and the detailed decision record (docs/DECISIONS.md)
Every meaningful folder has a concise README.md describing the actual code in it.

Keep detailed specifications out of CLAUDE.md. Update the relevant doc when architecture, agent boundaries, database/protocol contracts, scope, or unresolved decisions materially change.

Non-Negotiables

Preserve decentralized decision-making and autonomous agent boundaries.

Keep negotiation multi-factor and cooperative.

Keep MRPII/business calculations deterministic.

Keep LLMs out of direct business-state control.

Simulation triggers changes; agents decide responses.

Treat the 25% milestone as a vertical slice.

No Supplier Agent for the 25% milestone.

Avoid unnecessary complexity and infrastructure.

When in doubt: inspect first, preserve boundaries, keep deterministic logic deterministic, and avoid assumptions.