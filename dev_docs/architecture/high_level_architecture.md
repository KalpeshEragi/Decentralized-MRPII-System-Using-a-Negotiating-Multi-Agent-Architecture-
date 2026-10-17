# High-Level Architecture

**Status:** APPROVED by the developer (2026-10-17). Nothing new here is implemented.
**Related:** `pubsub_event_channel.md` (event details), `negotiation.md` (protocol details), `quantity_accounting.md`,
the agent folders, `../DECISIONS.md`.

## 1. Purpose

A simulated manufacturing world in which six autonomous agents each manage their own responsibility, share facts
through events, negotiate privately when they must agree, react to changes, and process many orders safely.
The database and the simulator represent the factory; there is no real factory, supplier, machine or HR system.

## 2. The six agents and what they own

| Agent | Owns (only this agent changes it) | Typical needs from others |
| --- | --- | --- |
| Sales | Customer conversations, inquiries, options shown, confirmations, customer-facing order status | Feasible options from Planning |
| Planning | MPS, BOM explosion, MRP requirements, machine capacity, schedule, the production plan, procurement requests | Stock (Inventory), supply (Purchasing), space (Warehouse), workers (HR) |
| Inventory | Stock quantities, reservations, safety stock, stock receipts and issues | Material movements (Warehouse), plan changes (Planning, via events) |
| Purchasing | Supplier options, supplier commitments (quantity, delivery date), supplier delay handling | Receiving slots (Warehouse) |
| Warehouse | Receiving capacity per day, storage space, physical movement, issue to production, finished goods, shipment hand-off | Delivery dates (Purchasing), finished-goods dates (Planning); no HR workers (WH-3) |
| HR | Workers, skills, shifts, absences, workforce commitments (hours per day) | — |

Suppliers are **simulated adapters** used only by Purchasing. There is no Supplier Agent.

### Resource ownership map (used to find negotiation partners, §6)

| Resource | Owner |
| --- | --- |
| Customer commitment (what the customer was told) | Sales |
| Production plan, MPS, machine capacity, production dates | Planning |
| Stock on hand, reservations, safety stock | Inventory |
| Supplier quantity and delivery date | Purchasing |
| Receiving slots, storage space | Warehouse |
| Worker hours, skills, shifts | HR |

## 3. Runtime (decided)

One FastAPI backend program contains all six agents as separate modules (`backend/app/<agent>_agent/`, same layout
as `sales_agent/`). Agents never call another agent's code or tables directly. They use only:

| Shared infrastructure | Does | Never does |
| --- | --- | --- |
| Event channel | Stores events, delivers them to subscribers, retries, deduplicates | Decide anything, change business data |
| Negotiation layer | Sessions, participants, message validation, round limits, timeouts, persistence | Pick an outcome, override an agent's limits |
| Read functions | Each agent exposes a few read-only functions for authorized data, as one in-process module `<agent>/reads.py` (IB-2) | Allow writes |
| Simulator | Sets the starting state; triggers events through the normal path | Tell agents what to answer |
| LLM connector | One shared Ollama model for all agents | Store or decide business facts |
| Audit log | Records every decision, event and negotiation step | — |

Because agents only talk through these, splitting an agent into its own program later stays possible.

**Read-module rule (IB-2, 2026-10-17):** an agent may import exactly one thing from another agent: its read-only
module `<agent>/reads.py`. A read function opens its own read-only session and returns plain data. A test enforces
the import rule. Writes always go through negotiation (A2A) or events. The same reads are also offered as HTTP GET
doors for the demo and the team.

## 4. Data (decided)

One Neon PostgreSQL database. Each agent has its own schema: `sales_agent`, `planning`, `inventory`, `purchasing`,
`warehouse`, `hr`. Shared reference data (products, BOM) sits in one shared schema, read by all.
Infrastructure has its own schemas (events, negotiation, simulation, audit).

- An agent writes only its own schema.
- Others read through that agent's read functions, never its tables.
- A business change and the event that announces it are saved in one transaction.

## 5. Communication (two mechanisms)

| | Publish–subscribe events | Private negotiation |
| --- | --- | --- |
| Used for | Announcing a fact or an agreed outcome | Reaching an agreement on a resource |
| Who sees it | Every agent subscribed to that event type | Only the participants |
| Example | `SupplierDeliveryDelayed`, `ReservationCommitted` | Planning ↔ Purchasing about an earlier delivery |
| Shape | One-way, no reply expected | Request → Offer/Counter-offer → Accept/Reject → Agreement |

Sales ↔ Planning keeps the two doors from the Sales design (request out, result back) plus the confirmation notice.

## 6. Who negotiates with whom (rule-governed, dynamic)

There is **no fixed list of negotiation pairs**. Any two agents may negotiate when a real need arises.
The partner is derived from rules, not hard-coded.

### 6.1 When an agent opens a negotiation

All three must hold:
1. **Trigger:** a fact changed (an event arrived, or its own state changed), and one of its own commitments or plans
   is now broken or at risk.
2. **Can't fix alone:** the agent has checked whether it can solve it with its own resources only.
3. **Needs someone else's resource:** the fix requires a change or commitment of a resource owned by another agent.
   The partner is the **owner of that resource** in the ownership map (§2).

If the agent only needs information, it reads the owner's read function or waits for an event. That is not a negotiation.

### 6.2 Who starts

**The agent with the problem starts; the owner of the resource responds.** An owner never opens a negotiation to
offer its own resource. This keeps two agents from opening the same negotiation at the same time.

### 6.3 Several owners for one problem

If one problem needs resources from several owners, the agent opens **one two-party negotiation per owner**, in
parallel, all tied to one **case id** (the cause). It combines the results itself. Multi-party sessions are not used
unless a later need appears.

### 6.4 Guards

- At most one open negotiation per (case, resource, starter, owner).
- A closed negotiation is not reopened for the same cause unless a new fact arrives (a new event version).
- Follow-up chains are limited: an outcome may trigger further negotiations, up to a fixed depth (starting value 3);
  beyond that the case escalates to a human.
- Round limits and timeouts per session (in `negotiation.md`).
- Sales negotiates only with Planning. Only Purchasing talks to the simulated suppliers.
- Hard constraints are never traded away; priority only orders the owner's queue (`negotiation.md`).

### 6.5 Example: supplier delay (material arrives 5 days late)

1. The supplier adapter reports to Purchasing. Purchasing updates its supplier commitment and publishes
   `SupplierDeliveryDelayed` (case id = this delay).
2. Subscribers react, each for its own responsibility:
   - **Warehouse:** the old receiving slot is freed. It checks its own space on the new date. Space available →
     it books it and publishes the fact; no negotiation. No space → it needs a different delivery date, which
     Purchasing owns → **Warehouse ↔ Purchasing**.
   - **Inventory:** projected stock for the affected days drops. It recalculates and publishes
     `StockAvailabilityChanged`. It does not open procurement (Planning does, §7).
   - **Planning:** the production start is at risk. It checks its own schedule first (moving work that has slack).
     If that is not enough, in parallel: **Planning ↔ Purchasing** (earlier or split delivery),
     **Planning ↔ Inventory** (use stock reserved for a later order), **Planning ↔ HR** (extra shift to catch up).
3. Each outcome is published as an event. Planning revises the plan and publishes `PlanRevised` or `PlanAtRisk`.
   Sales hears the change and informs the customer only with validated information.

## 7. Normal order flow (high level)

1. Customer ↔ Sales: details collected and validated. Sales → Planning: feasibility request.
2. Planning runs MPS/BOM/MRP/capacity/schedule and checks resources owned by others, negotiating where needed
   (stock with Inventory; **procurement with Purchasing — Planning starts procurement**; space with Warehouse;
   workers with HR). Tentative holds may be used and may expire.
3. Planning → Sales: feasible options, or "nothing feasible". Sales presents only these.
4. Customer accepts → `OrderConfirmed`. Planning re-validates and owners commit their resources →
   `PlanCommitted` (or `PlanCommitFailed`). Acceptance, commitment and production start are separate states.
5. Simulated receiving, production progress, finished goods and shipment advance through events.
6. Changes and cancellations trigger review of commitments, replanning and customer updates.

## 8. Decisions recorded

| ID | Decision | Status |
| --- | --- | --- |
| HA-1 | One backend program, six agent modules, communication only via shared infrastructure | Decided 2026-10-16 |
| HA-2 | One database, one schema per agent, shared reference schema, cross-agent reads via read functions | Decided 2026-10-16 |
| HA-3 | Planning starts procurement (replaces the old "Inventory starts" design; existing code must change in Phase 2) | Decided 2026-10-16 |
| HA-4 | Dynamic, rule-governed negotiation partners (§6) instead of fixed pairs | Decided 2026-10-17 |
| HA-5 | Problem-holder starts, owner responds; one two-party session per owner, linked by case id | Decided 2026-10-17 |
| HA-6 | Follow-up depth limit 3, then human escalation | Decided 2026-10-17 (starting value) |

## 9. Open (decided in later docs)

Event storage technology and catalogue (`pubsub_event_channel.md`); negotiation transport, rounds, holds, priority
(`negotiation.md`); exact quantity rules (`quantity_accounting.md`); the execution policy that replaces per-plan
human approval.

## 10. Diagram checklist (for the developer's drawing)

- Six agent boxes, each listing what it owns (§2).
- Shared infrastructure band: event channel, negotiation layer, simulator, LLM connector, audit log.
- One database with one schema per agent, plus shared reference and infrastructure schemas.
- Solid arrows: agent → event channel (publish) and event channel → agent (subscribed events).
- Dashed arrows: private negotiation through the negotiation layer, labeled "any two agents, by ownership rule".
- Sales ↔ Planning doors (request, result, confirmation notice).
- Purchasing ↔ simulated supplier adapter. Customer ↔ Sales (test channel).
- Note: "problem-holder starts, owner responds; only outcomes are published".
