# 1. Purpose
Determines how much available inventory can be allocated to production requirements while respecting inventory constraints and safety-stock policies.
## Main responsibility:
decide how much material can be provided, when it can be provided, and what allocation is feasible.

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
Material Requirement
      ↓
Inventory Agent
      ↓
Inventory Service
      ↓
Available Quantity / Constraints
      ↓
Production Planning Agent
      ↓
Multi-Factor Negotiation
      ↓
Feasible Material Allocation
      ↓
Simulation Disruption
      ↓
Re-evaluate + Reallocate + Renegotiate
      ↓
Revised Material Allocation
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
send_offer(...)
send_counter_offer(...)
validate_allocation(...)
apply_allocation(...)

# 5. Separation
- Agent: inventory decisions, goals, constraints, allocation policy, negotiation strategy
- Inventory Service: deterministic availability and allocation calculations
- Database: repository/domain layer
- Negotiation Engine: protocol, messages, session state

# 6. Multi-Factor Decision Making
Evaluate allocation alternatives using a combination of:
- Requested quantity
- Available inventory
- Safety-stock constraints
- Existing reservations
- Order priority
- Required delivery date
- Competing material requirements
- Expected incoming supply
## NOTE:
The decision must not depend on one factor alone.

# 7. Negotiation Role
The Inventory Agent usually responds when the Production Planning Agent requests material allocation.
```text
Production Planning
      ↓ REQUEST
Inventory Agent
      ↓ OFFER / COUNTER-OFFER
Production Planning
      ↓
Accept / Counter / Reject
```
## NOTE:
If the requested quantity cannot be provided, the agent can propose a lower feasible allocation and communicate the remaining requirement so that the Purchasing Agent can handle procurement.

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
Reallocate + Communicate + Renegotiate
       ↓
Revised Material Allocation
```

# 9. LLM Role
Use the LLM for contextual reasoning, comparing multi-factor allocation alternatives, and generating structured offer/counter-offer proposals.
## Keep these deterministic (Done Inventory service):
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
- Negotiate using multiple factors.
- Accept/reject/counter allocation proposals.
- Reserve inventory after an agreement.
- Receive a simulated inventory-related disruption.
- Re-evaluate and renegotiate.
- Produce and record a revised material allocation.