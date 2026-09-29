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
- **Factors (25% scope):** material quantity, required date, delivery date/lead time, inventory impact, production priority. Preferences/weights are designed at implementation time.
- **Cost/price is future scope.** For the 25% implementation there is no cost/price in negotiation factors, supplier forms, offers/counter-offers, acceptance/rejection criteria, or LLM negotiation reasoning. It will be revisited after the 25% milestone.
- **Supplier:** No Supplier Agent. The Purchasing Agent talks to a supplier communication interface. In the demo the tester plays the supplier through a UI and provides supplier-side responses only. Purchasing decides accept/reject/counter autonomously.
- **Agreement:** agents accept, hard constraints satisfied, preferences/bounds satisfied, feasible resolution of the shortage, recorded by the negotiation system. Deterministic validation is the authority on feasibility.
- **Failure:** A session can end `FAILED` (no feasible agreement after multiple rounds). `FAILED` is a distinct end status, not `REJECTED`, `ABORTED` or `EXPIRED`. The shortage stays unresolved, the plan is not updated, and the failure is recorded and visible in the dashboard/decision log.
- **Human approval:** After deterministic validation, the tester approves (execute/commit) or rejects (reconsider/replan) the plan. The human is not the planner or negotiator.
- **Purchase orders:** `purchase_orders` and `purchase_order_items` are out of scope. The negotiation agreement is the purchasing outcome. Approval and activity are recorded through agreement/audit records.
- **Parked code:** Sales, Production and Warehouse agent stubs stay in the repo, unused and untouched.
- **A2A:** Use the official A2A Python SDK with HTTP endpoints for the core agents. No fake/minimal A2A-compatible layer, no event bus.
- **Shortage flow:** The Inventory Agent detects a shortage and initiates procurement negotiation with the Purchasing Agent over A2A, sending the shortage/procurement context. Purchasing handles supplier interaction and negotiation. Planning receives the resulting agreement or `FAILED` result and uses it for replanning/plan evaluation.
- **Supplier UI:** Structured supplier-response form with quantity, delivery date/lead time and an optional message. **No price/cost field (see Cost/price above).** The tester acts only as the supplier, one response per round. Purchasing alone decides ACCEPT/REJECT/COUNTER. The tester does not end the negotiation.
- **Round limit:** Max 3 supplier rounds per negotiation session, shown as "Round N of 3". No agreement within 3 rounds → session ends `FAILED`.
- **Human rejection:** Rejecting a plan automatically triggers Planning to replan, and the new plan returns to human approval. Max 2 planning attempts (each with at most one negotiation session of ≤3 rounds). If attempt 2 yields no feasible plan/agreement, automatic replanning stops and human intervention is required. No infinite loops.
- **Available quantity:** `available_quantity = on_hand − reserved − safety_stock` (floored at 0). Incoming/scheduled receipts are not part of it. MRP netting adds them separately (`projected_available_quantity`).
- **Scenarios:** `implementation_25%/scenarios.md` is the unmodified source of truth for the seven finalized scenarios. **Scenario 5 (Supplier Price Increase) is future scope and out of scope for the 25% implementation**: no supplier price-increase behavior and no cost/price fields or negotiation logic to support it. Scenarios 1, 2, 3, 4, 6 and 7 are implemented. For Scenario 4, the "lead time/cost" constraint is implemented as lead time only, with no cost behavior.

---

## Unresolved

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