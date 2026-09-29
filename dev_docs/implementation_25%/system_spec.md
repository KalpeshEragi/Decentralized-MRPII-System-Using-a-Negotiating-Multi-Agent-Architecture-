# System Spec — 25% Milestone

Compact implementation reference. Sources: supplied design context, plus `agent_operations.md`, `database_schema.md` and `table_relations.md` for terminology. `scenarios.md` is the source of truth for §7. Anything not established is marked **UNRESOLVED**. This file does not resolve contradictions.

Milestone: one vertical slice with exactly three autonomous agents (Production Planning, Inventory, Purchasing).
Flow: Customer Order → BOM/MPS/MRP → Inventory check → Shortage/Requirement → Negotiation → Supplier data → Agreement → Initial Plan → Disruption → Re-evaluation → Negotiation → Revised Plan.

---

## 1. Architecture Principles

| # | Principle |
| --- | --- |
| P1 | Shared infrastructure is acceptable; centralized decision-making is not. Data centralization ≠ decision centralization. |
| P2 | No central decision-maker. Agents talk through the negotiation protocol (Agent A ↔ Protocol ↔ Agent B). |
| P3 | The negotiation engine MAY: create sessions, register participants, track state, validate messages/sender/receiver/sequence, route, manage timeout, persist messages/offers/agreements, enforce state transitions. It MUST NOT: choose a winner, decide outcomes, override agent preferences or constraints, or replace autonomy. |
| P4 | Each agent keeps its own goals, preferences, constraints, negotiation state, offers and decisions. |
| P5 | One agent must not silently take over another's business responsibility. Agents do not directly manipulate unrelated business tables. They use domain services and tools. |
| P6 | Business truth and calculations are deterministic (see §4). The LLM is not the system of record. Raw LLM output never mutates state. Structured output is validated before use. |
| P7 | Negotiation is multi-factor and cooperative. The goal is a mutually feasible plan, not a winner. |
| P8 | Simulation injects events only. Agents decide the response. |
| P9 | The supplier is a data/service, not an agent. No Supplier Agent in this milestone. |
| P10 | PostgreSQL is the shared source of truth. Audit stores a concise structured rationale, not chain-of-thought. |
| P11 | The design is modular but not over-engineered: no per-function microservices, no multiple databases, and no duplicated negotiation logic inside agents. |
| P12 | Future agents (Sales, Production, Warehouse, Supplier) are out of scope. |

UNRESOLVED (technology): agent framework (MESA/SPADE/PADE/OpenAI Agents SDK), LLM model/runtime, A2A transport and event bus, frontend (Next.js vs Streamlit/React), Docker/deployment, ORM/migrations, modular-monolith ratification.

---

## 2. Agent Responsibilities

### 2.1 Production Planning Agent

| Item | Content |
| --- | --- |
| Goal | Turn demand into a feasible production/material plan. Example goal: fulfil the order by its due date. |
| Responsibilities | MPS, MRP requirements, production priority, required quantities, required-by dates, shortage identification, initiating negotiation, replanning. |
| Knows | Customer order (product, qty, due date, priority), BOM, MPS, MRP requirements, current plan, inventory responses, procurement responses, negotiation results. It does NOT hold the inventory or supplier databases. |
| Decides | The outcome it needs, and whether received proposals satisfy its planning objectives. Accept/reject/counter. Whether to replan. |
| Cannot decide | Modify or reserve inventory. Select or modify suppliers. Create or approve purchase orders. Machine or warehouse operations. Override Inventory or Purchasing constraints. Write arbitrary tables. |
| Exchanges | → Inventory: REQUEST availability/allocation (item, qty, required-by). → Purchasing: REQUEST procurement (item, qty, required-by, priority). ← OFFER/COUNTER_OFFER/ACCEPT/REJECT from both. |

### 2.2 Inventory Agent

| Item | Content |
| --- | --- |
| Goal | Allocate material without violating its own inventory constraints. |
| Responsibilities | Availability assessment, allocation, safety-stock constraints, reservation/release (via service, after agreement), reporting shortages. |
| Knows | On-hand, reserved, safety stock, warehouse, availability, existing reservations, pending requests, requested qty/date, other agent's offers. |
| Decides | How much it can safely allocate. Counter-offer when the request cannot be met. |
| Cannot decide | Change MPS or run MRP. Choose suppliers or negotiate supplier terms. Create purchase decisions or orders. Alter schedules. Ignore its own safety-stock constraints. Modify another agent's state. |
| Exchanges | ← Planning REQUEST. → Planning OFFER (allocation) / COUNTER_OFFER / shortage report. Reservation confirmation after COMMIT. |

### 2.3 Purchasing Agent

| Item | Content |
| --- | --- |
| Goal | Secure required material within its own quantity, delivery and lead-time limits. |
| Responsibilities | Procurement requirements, supplier evaluation and comparison, procurement terms, quantity/delivery/lead-time trade-offs, purchase requisitions, reporting the procurement outcome. |
| Knows | Procurement requirement (item, qty, required-by, priority). Supplier data (lead time, MOQ, available qty, reliability). Negotiation state (offers, counters, agreement, deadline). |
| Decides | Which supplier option to pursue. Procurement quantity and delivery-date terms. Accept/reject/counter. |
| Cannot decide | Change production quantities/plans. Modify inventory. Run MRP. Reserve stock. Override planning constraints. Commit to a supplier without an agreed result. Write unrelated tables. |
| Exchanges | ← Planning REQUEST. → Planning OFFER/COUNTER_OFFER with procurement terms. Supplier data is read through the supplier service (not messages). |

---

## 3. Agent State

Persisted in `agent.agent_state` (1:1 with `agent.agents`). All three agents use the same fields. It stores decision and negotiation context only, and must not duplicate business tables.

| Field | Meaning |
| --- | --- |
| `current_goal` | Current objective |
| `preferred_terms` | Preferred qty/date/priority, etc. |
| `reserved_limits` | Hard/acceptable limits (e.g. latest delivery, minimum acceptable quantity/allocation) |
| `initial_proposal` | First proposal |
| `own_offer_history` | Own past offers |
| `opponent_offer_history` | Offers received |
| `dialogue_history` | Negotiation dialogue/context |
| `negotiation_rules` | Rules/policies |
| `current_task` | Current task |
| `updated_at` | Last update |

Agent-specific policy, kept inside each agent (from `agent_operations.md`):

| Agent | Policy items |
| --- | --- |
| Planning | `planning_preferences`, `planning_constraints`, `priority_policy`, `decision_context` |
| Inventory | `allocation_policy`, `safety_stock_policy`, `minimum_reserve`, `acceptable_allocation_range` |
| Purchasing | `procurement_strategy`, `delivery_preferences`, `supplier_evaluation_policy`, `acceptable_quantity_range`, `latest_acceptable_delivery` |

UNRESOLVED: whether these policy items are stored as columns or inside the JSONB fields, and their exact JSON shapes.

---

## 4. Tool Interfaces

Tools give agents access to deterministic services. Function signatures are **UNRESOLVED**. Only responsibilities are fixed.

### 4.1 Deterministic (services and logic, never the LLM)

| Capability | Used by | Notes |
| --- | --- | --- |
| BOM explosion; gross/net requirements; MPS and MRP calculation | Planning | Run through the deterministic MRP service |
| Shortage detection | Planning | From net requirement |
| Available quantity = `on_hand − reserved − safety_stock` | Inventory | Inventory service |
| Reserve / release inventory | Inventory | Transaction via inventory service, only after agreement |
| Supplier lookup (lead time, MOQ, available qty) | Purchasing | Supplier service/data |
| Create purchase requisition | Purchasing | `purchasing.purchase_requisitions`. Purchase orders: UNRESOLVED. |
| Constraint / business-rule validation of any proposal or agreement | All | Quantity, dates, supplier capacity, inventory and safety-stock limits, production feasibility |
| Capacity calculation and production feasibility | Planning (as needed) | Deterministic |
| Persistence and transactions (plans, agreements, reservations) | Services | Agents call services, not tables |
| Negotiation protocol operations (session, route, validate, persist, timeout) | Shared engine | See P3 |
| Audit write | All | `audit.decision_audit` |
| Simulation event injection | Scenario Manager | Injects only |

### 4.2 Agent logic (goal-oriented, not business truth)

Goals, preferences and local constraints. Offer generation and evaluation. Accept/reject/counter. Coordination.

### 4.3 LLM-assisted reasoning (advisory)

Interpret negotiation context. Multi-factor reasoning. Generate structured proposals/counter-offers. Concise rationale.

Pattern: `collect state → deterministic constraints → LLM reasoning → structured proposal → validation → agent decision → negotiation message`.

The LLM is not authoritative for inventory, BOM, suppliers, capacity, order status, DB state or constraint enforcement.

---

## 5. Message & Negotiation Schema

### 5.1 Message types (first prototype)
`REQUEST`, `OFFER`, `COUNTER_OFFER`, `ACCEPT`, `REJECT`, `AGREEMENT_PROPOSED`, `COMMIT`.
`WITHDRAW` and `ABORT` are possible extensions and are not needed for the prototype.

### 5.2 Envelope (proposed; final serialized schema is UNRESOLVED)
`protocol_version`, `message_id`, `negotiation_id`, `sender{agent_id, agent_type}`, `receiver{agent_id, agent_type}`, `message_type`, `sequence_number`, `timestamp`, `correlation_id`, `payload`.

### 5.3 Offer terms (multi-factor)
Example: `{quantity, delivery_date, priority}`.
Finalized 25% factors: material quantity, required date, delivery date/lead time, inventory impact, production priority. Cost/price is future scope and must not appear in offers, forms, acceptance criteria or LLM reasoning. Other candidate factors from the design context (not in the finalized list): availability, safety-stock limits, supplier capacity, production requirement, deadline, agent preferences/constraints.

### 5.4 Session lifecycle
`INITIATED → NEGOTIATING → (OFFER / COUNTER_OFFER)* → AGREEMENT_PROPOSED → COMMITTED`. End states: `REJECTED`, `ABORTED`, `EXPIRED`, `FAILED` (no feasible agreement after multiple rounds; distinct from the others. The shortage stays unresolved and the plan is not updated).

### 5.5 Flow
1. The initiator sends a REQUEST.
2. The responder sends an OFFER, or REJECT.
3. Either side sends a COUNTER_OFFER within its own `reserved_limits`, or sends ACCEPT.
4. A party sends AGREEMENT_PROPOSED.
5. The agreed terms are validated deterministically (`validated`).
6. COMMIT. The state change happens through the owning service (`committed`). It is never done by the LLM or the engine.

Persistence: `negotiation.negotiation_sessions`, `_participants`, `_messages`, `_offers`, `_agreements`.

See `DECISIONS.md` for the finalized shortage flow (Inventory initiates → Purchasing), the supplier form (no price field), the 3-round limit and the 2-attempt replanning limit.

UNRESOLVED:
- Who may send AGREEMENT_PROPOSED and COMMIT.
- Timeout values.
- Session topology: Planning↔Inventory and Planning↔Purchasing as separate sessions, or multi-party. The context implies pairwise, but this is not stated.
- Transport (A2A/event bus).
- Who "initiates" for Inventory↔Purchasing coordination. The supplied context only specifies Planning as initiator.

---

## 6. Database Ownership

PostgreSQL is shared. "Owner" means the agent/domain whose decisions and service writes change the data. Agents write only through services.

| Schema.table(s) | Owner | Written by / notes |
| --- | --- | --- |
| `core.items`, `core.bom`, `core.bom_items` | Reference data | Seed/master data. Read via BOM service. Agents don't write. |
| `sales.customers`, `customer_orders`, `customer_order_items` | Sales domain (no Sales Agent in 25%) | Order creation via API/order service. Planning reads. |
| `planning.mps_plans`, `planning.mrp_requirements` | **Production Planning Agent** | Via the MPS/MRP services |
| `inventory.warehouses`, `inventory_balance`, `inventory_reservations` | **Inventory Agent** | Reserve/release only through the inventory service, after agreement. Planning and Purchasing never write. |
| `purchasing.suppliers`, `supplier_items` | Supplier data/service (read by Purchasing) | Data, not an agent. Changed by simulation events via the injector. |
| `purchasing.purchase_requisitions` | **Purchasing Agent** | `created_by_agent` FK |
| `purchasing.purchase_orders`, `purchase_order_items` | Out of scope for 25% | The negotiation agreement is the purchasing outcome |
| `production.*` | Out of 25% active scope (no Production Agent) | Documented as target only |
| `agent.agents`, `agent.agent_state` | Each agent owns its own state row | No agent modifies another's state |
| `negotiation.*` | Shared protocol layer (persistence only) | Stores protocol facts. Does not decide outcomes. |
| `simulation.*` | Scenario Manager | Injects events only |
| `audit.decision_audit` | Each agent (own decisions) | Append-only rationale summary |

UNRESOLVED: how a simulation event applies its "system condition change" to the owning tables (directly or through the owning service), and how state is reset after a scenario.

---

## 7. Demonstration Scenarios (seven finalized; six in 25% scope)

Source of truth: `scenarios.md` (finalized). Condensed here without reinterpretation. Consult that file for the full wording. Across all scenarios, the affected agents are Planning, Inventory and Purchasing. The first-listed agent is the one `scenarios.md` names first. Simulation only injects the trigger (P8).

| # | Scenario | Initial conditions | Trigger | Affected agents (order as in source) | Expected negotiations | Constraints | Expected final outcome | Proves |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Normal Production Planning: 1,000 SmartPhone X1 | Inventory holds some components. The rest must be procured. | New customer order, 1,000 units, defined due date | Planning, Inventory, Purchasing | Planning requests allocation from Inventory. Purchasing gets supplier options and negotiates terms for shortages. | No over-allocation. Safety stock respected. Supplier lead times respected. Quantities available before production. | Validated procurement and production plan for 1,000 units | Baseline MRPII workflow and 3-agent autonomous coordination |
| 2 | Supplier Delivery Delay | Plan exists and depends on the supplier delivery | Supplier delivery date delayed | Planning, Purchasing, Inventory | Purchasing evaluates revised availability/terms. Planning evaluates production impact. Inventory reports availability. Agents negotiate an alternative. | Delayed material unusable before its new date. Inventory constraints stay valid. Customer due date respected where feasible. | Revised, feasible procurement/production plan | Re-planning after an external disruption |
| 3 | Demand Increase: 1,000 → 1,300 units | The 1,000-unit plan exists | Demand +300 units | Planning, Inventory, Purchasing | Planning recalculates requirements. Inventory checks additional availability. Purchasing handles new shortages and negotiates extra procurement. | Existing allocations respected. Valid supplier lead times. Capacity/production constraints respected. | Revised plan for the higher demand, or a clearly identified constrained quantity/date | Recalculation and coordination of extra resources |
| 4 | Supplier Quantity Reduction: 500 → 300 Display Assemblies | Plan depends on the original 500 | Supplier reduces committed quantity | Purchasing, Planning, Inventory | Purchasing evaluates alternative procurement. Planning determines the impact. Inventory reports available displays and other constraints. | Supplier cannot exceed the revised qty. Inventory not exceeded. No production on unavailable displays. Alternative supply respects lead time/cost. | Alternative procurement or a revised feasible plan | Responding to shortages and negotiating alternatives |
| 5 | **FUTURE SCOPE — NOT IMPLEMENTED IN 25%** Supplier Price Increase | Supplier was acceptable under the existing plan | Supplier raises component price | Purchasing, Planning, Inventory | Purchasing compares options on cost, quantity, lead time and availability. Planning evaluates the plan effect. | Production requirements still met. Lead times respected. Within business constraints. Cheapest is not the only criterion. | Procurement decision and feasible plan based on multiple factors | Multi-factor (not price-only) negotiation and trade-off reasoning |
| 6 | Inventory Reservation Change | Planning already counted that inventory as available | A reservation change reduces allocatable stock | Inventory, Planning, Purchasing | Inventory reports the new allocatable quantity. Planning evaluates the shortage. Purchasing procures if needed. | No double allocation of reserved stock. Safety stock valid. No consumption of unavailable inventory. | Revised allocation/procurement/production plan | Response to internal resource-state changes |
| 7 | Customer Due-Date Change: 30 → 20 days | A feasible 30-day plan exists | Customer requests earlier delivery | Planning, Inventory, Purchasing | Planning evaluates the compressed schedule. Inventory checks immediate availability. Purchasing checks whether suppliers can meet earlier dates and negotiates delivery/quantity. | Lead times not ignored. No over-allocation. Capacity respected. New deadline not assumed achievable. | Plan meeting the new deadline if feasible, else a validated alternative | Re-planning on changing deadlines under real constraints |

**Scenario 5 is future scope and out of scope for the 25% implementation** (cost/price is not in 25% scope). Do not implement price-increase behavior or any cost/price fields or negotiation logic for it. Scenario 4's "lead time/cost" constraint is implemented as lead time only. `scenarios.md` is unchanged. Scenarios 1, 2, 3, 4, 6 and 7 are in scope.

Simulation event types (`database_schema.md` examples) are not mapped to scenarios in `scenarios.md`. The mapping is UNRESOLVED.

---

## 8. Acceptance Criteria

The milestone is complete when the following are demonstrably working.

| # | Criterion | Measurable check |
| --- | --- | --- |
| A1 | Order → plan | A customer order produces MPS and MRP requirements via deterministic services. Gross/net values match a hand calculation. |
| A2 | Availability | Inventory availability equals `on_hand − reserved − safety_stock` and is never negative-allocated. Reservations occur only after an agreed COMMIT. |
| A3 | Three agents | Exactly Planning, Inventory and Purchasing run, each with its own persisted `agent_state`. No Supplier Agent. |
| A4 | Boundaries | No agent writes another's state or tables. Tests or audit show each write goes through its owning service. |
| A5 | Multi-factor negotiation | At least one session exchanges REQUEST/OFFER/COUNTER_OFFER/ACCEPT with ≥2 factors (e.g. quantity + delivery date). It ends AGREEMENT_PROPOSED → COMMIT. All messages, offers and the agreement are persisted. |
| A6 | Constraint respect | No committed agreement violates a party's `reserved_limits`, safety stock or supplier capacity. Invalid proposals are rejected by deterministic validation. |
| A7 | No central decider | The engine only routes/validates/persists. Outcomes come from agent decisions (verifiable in the audit log). |
| A8 | LLM safety | LLM output is parsed to a structured schema and validated before use. An invalid or hallucinated output does not change business state. |
| A9 | Initial plan | The agreement yields an initial plan that passes deterministic validation. |
| A10 | Scenarios 1, 2, 3, 4, 6, 7 | Each in-scope scenario in §7 (`scenarios.md`; Scenario 5 is future scope) runs: its trigger causes agent re-evaluation and negotiation, and yields its expected final outcome as a deterministically validated plan (or the validated alternative/constrained result the scenario allows). The Scenario Manager makes no decisions. All six in-scope scenarios are required. |
| A11 | Audit | Each agent decision writes `audit.decision_audit` (agent, type, context, decision, concise `reasoning_summary`). |
| A12 | Dashboard | A basic dashboard shows orders, agent activity, negotiation timeline, initial and revised plan. Scope: UNRESOLVED (frontend technology). |
| A13 | Determinism | The same inputs give the same MRP/availability results, independent of the LLM. |

UNRESOLVED: test framework/coverage thresholds, and dashboard depth.
