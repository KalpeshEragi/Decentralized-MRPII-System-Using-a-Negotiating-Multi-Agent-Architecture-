# 1. Purpose
Converts customer demand into a feasible production plan and replans when conditions change.
## Main responsibility: 
decide what to produce, when to produce it, and what materials are required.

# 2. Works With
- Inventory Agent
- Purchasing Agent
- Negotiation Engine
- Simulation / Scenario Manager
- MPS and MRP services
## NOTE:
The agent does not directly control inventory, suppliers, machines, or PostgreSQL.

# 3. Core Flow
```text
Customer Orders
      ↓
Production Planning Agent
      ↓
MPS → MRP Service
      ↓
Material Requirements
      ↓
Inventory / Purchasing Agents
      ↓
Multi-Factor Negotiation
      ↓
Feasible Production Plan
      ↓
Simulation Disruption
      ↓
Re-evaluate + Replan + Renegotiate
      ↓
Revised Production Plan
```

# 4 . Tools / Services
get_customer_orders()
get_bom(item_id)
create_mps_plan(...)
run_mrp(...)
get_inventory_availability(...)
create_purchase_requisition(...)
start_negotiation(...)
send_offer(...)
send_counter_offer(...)
validate_plan(...)
apply_revised_plan(...)

# 5. Separation
- Agent: planning decisions, goals, constraints, negotiation strategy
- MPS/MRP: deterministic calculations
- Database: repository/domain layer
- Negotiation Engine: protocol, messages, session state

# 6. Multi-Factor Decision Making
Evaluate alternatives using a combination of:
- Quantity
- Delivery date / lead time
- Order priority
- Inventory availability
- Safety-stock constraints
- Procurement availability
- Production requirements
## NOTE:
The decision must not depend on one factor alone.

# 7. Negotiation Role
The Production Planning Agent usually initiates a requirement when the production plan needs material/resources.
```text
Production Planning
      ↓ REQUEST
Inventory / Purchasing
      ↓ OFFER / COUNTER-OFFER
Production Planning
      ↓
Accept / Counter / Reject
```
## NOTE:
If inventory is insufficient, the agent can create a procurement requirement and evaluate the Purchasing Agent's proposal against the production plan.

# 8. Simulation / Replanning
Simulation only injects a What-If event; the agent decides how to react.
```text
Initial Plan
   ↓
Simulation Event
   ↓
Changed condition
   ↓
Re-evaluate requirements
   ↓
Communicate + Renegotiate
   ↓
Revised Plan
```

# 9. LLM Role
Use the LLM for contextual reasoning, comparing multi-factor alternatives, and generating structured offer/counter-offer proposals.
## Keep these deterministic (Done MRPII service):
- BOM calculations
- MPS/MRP calculations
- Quantity calculations
- Constraint validation
## Final plan validation:
LLM output must be structured and validated before execution.


# 10. 25% Definition of Done
The agent can:
- Receive customer orders.
- Create/update an MPS.
- Run MRP and identify requirements/shortages.
- Request inventory information.
- Create procurement requirements.
- Negotiate using multiple factors.
- Produce an agreed feasible plan.
- Receive a simulated disruption.
- Re-evaluate and renegotiate.
- Produce and record a revised plan.