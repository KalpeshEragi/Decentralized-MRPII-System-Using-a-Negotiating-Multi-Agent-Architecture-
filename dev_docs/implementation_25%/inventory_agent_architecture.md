# 1. Purpose
Determines how much available inventory can be allocated to production requirements while respecting inventory constraints and safety-stock policies, and starts procurement negotiation when stock is insufficient.
## Main responsibility:
decide how much material can be provided, when it can be provided, what allocation is feasible, and detect shortages.

# 2. Works With
- Production Planning Agent
- Purchasing Agent
- Negotiation Engine
- Simulation / Scenario Manager
- Inventory Service
## NOTE:
The agent does not directly control production plans, suppliers, machines, or PostgreSQL.

# 3. Core Flow
```text
Material Requirement (from Production Planning)
      ↓
Inventory Agent
      ↓
Inventory Service
      ↓
Available Quantity = on_hand − reserved − safety_stock
      ↓
Enough?  ── yes ──► allocation proposal to Production Planning
      │
      no (shortage)
      ↓
Inventory → Purchasing negotiation (REQUEST with shortage context)
      ↓
Agreement (AGREEMENT_PROPOSED) or FAILED → result to Production Planning
      ↓
After human approval: COMMIT → reserve through the Inventory Service
      ↓
Simulation Disruption → Re-evaluate + Reallocate → Revised Material Allocation
```

# 4 . Tools / Services
get_inventory_balance(...)
get_inventory_reservations(...)
calculate_available_quantity(...)
get_safety_stock(...)
get_inventory_constraints(...)
propose_allocation(...)
reserve_inventory(...)
release_inventory(...)
start_negotiation(...)
validate_allocation(...)
apply_allocation(...)

How Planning's allocation request reaches this agent (plain service request or negotiation session) is open: P1-06 in `docs/DECISIONS.md`.

# 5. Separation
- Agent: inventory decisions, goals, constraints, allocation policy, shortage detection, negotiation initiation
- Inventory Service: deterministic availability and allocation calculations
- Database: repository/domain layer
- Negotiation Engine: protocol, messages, session state

# 6. Multi-Factor Decision Making
Evaluate allocation alternatives using a combination of:
- Requested quantity
- Available inventory
- Safety-stock constraints
- Existing reservations
- Production priority
- Required date
- Competing material requirements
- Expected incoming supply (projected availability only; never counted as currently available)
## NOTE:
The decision must not depend on one factor alone. Cost/price is out of scope for the 25% milestone.

# 7. Negotiation Role
The Inventory Agent detects the shortage and initiates procurement negotiation with the Purchasing Agent (P0-02).
```text
Inventory Agent
      ↓ REQUEST (shortage: item, quantity, required date, priority, inventory impact)
Purchasing Agent ◄──► supplier form (≤ 3 rounds)
      ↓
AGREEMENT_PROPOSED ──► Inventory Agent        or   session REJECTED / FAILED
      ↓
Result (agreement or FAILED) ──► Production Planning
```
## NOTE:
The agent never selects suppliers or negotiates supplier terms; Purchasing does. Reservation happens only after `COMMIT`, which follows human approval.

# 8. Simulation / Replanning
Simulation only injects a What-If event; the agent decides how to react.
```text
Initial Allocation
       ↓
Simulation Event
       ↓
Changed Inventory Condition
       ↓
Re-evaluate Availability
       ↓
Reallocate; start a new Inventory → Purchasing negotiation if a new shortage appears
       ↓
Revised Material Allocation
```

# 9. LLM Role
Use the LLM for contextual reasoning, comparing multi-factor allocation alternatives, and generating structured proposals.
## Keep these deterministic (Inventory service):
- Available quantity calculations
- Reserved quantity calculations
- Safety-stock calculations
- Allocation validation
- Inventory reservation/release operations
## Final allocation validation:
LLM output must be structured and validated against actual inventory constraints before execution.

# 10. 25% Definition of Done
The agent can:
- Receive material requirements from the Production Planning Agent.
- Check current inventory availability.
- Calculate allocatable quantity.
- Consider reservations and safety-stock constraints.
- Propose a feasible material allocation.
- Detect a shortage and initiate Inventory → Purchasing negotiation.
- Pass the negotiated result (agreement or `FAILED`) to Production Planning.
- Reserve inventory after `COMMIT` (after human approval).
- Receive a simulated inventory-related disruption.
- Re-evaluate and, if needed, start a new negotiation.
- Produce and record a revised material allocation.
