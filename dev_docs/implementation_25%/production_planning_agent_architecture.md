# 1. Purpose
Converts customer demand into a feasible production plan and replans when conditions change.
## Main responsibility: 
decide what to produce, when to produce it, and what materials are required.

# 2. Works With
- Inventory Agent
- Purchasing Agent (indirectly: receives the negotiated procurement result)
- Negotiation Engine
- Simulation / Scenario Manager
- MPS and MRP services
- Human approval (the tester approves or rejects the validated plan)
## NOTE:
The agent does not directly control inventory, suppliers, machines, or PostgreSQL.
It does not start procurement negotiation and does not create purchase requisitions; those belong to Inventory and Purchasing (P0-02).

# 3. Core Flow
```text
Customer Order
      ↓
Production Planning Agent
      ↓
MPS → MRP Service (deterministic)
      ↓
Material Requirements
      ↓
Inventory Agent (availability; detects shortage)
      ↓  shortage
Inventory → Purchasing negotiation (supplier form, max 3 rounds)
      ↓
Agreement / FAILED  →  Production Planning Agent
      ↓
Updated Production Plan → Deterministic Validation
      ↓
Human Approval
      ├─ approve → COMMIT / execute
      └─ reject  → automatic replan (max 2 planning attempts, then human intervention)
      ↓
Simulation Disruption → Re-evaluate + Replan → Revised Production Plan
```

# 4 . Tools / Services
get_customer_orders()
get_bom(item_id)
create_mps_plan(...)
run_mrp(...)
get_inventory_availability(...)
get_negotiation_result(...)
validate_plan(...)
submit_plan_for_approval(...)
apply_revised_plan(...)

How Planning's availability request to Inventory is exchanged (plain service request or negotiation session) is open: P1-06 in `docs/DECISIONS.md`.

# 5. Separation
- Agent: planning decisions, goals, constraints, evaluation of negotiated results
- MPS/MRP: deterministic calculations
- Database: repository/domain layer
- Negotiation Engine: protocol, messages, session state

# 6. Multi-Factor Decision Making
Evaluate alternatives using a combination of:
- Quantity
- Required date
- Delivery date / lead time
- Inventory availability and safety-stock constraints
- Production priority
- Production capacity (minimal check, `capacity_per_day`)
## NOTE:
The decision must not depend on one factor alone. Cost/price is out of scope for the 25% milestone.

# 7. Negotiation Role
The Production Planning Agent does not negotiate procurement itself. It computes requirements and receives the result of the Inventory → Purchasing negotiation.
```text
Production Planning
      ↓ material requirements (availability request)
Inventory Agent ── shortage ──► REQUEST ──► Purchasing Agent ◄──► supplier form (≤ 3 rounds)
      ↓
Agreement (AGREEMENT_PROPOSED) or FAILED
      ↓
Production Planning: update plan, validate, submit for human approval
```
## NOTE:
After `FAILED` the shortage stays unresolved and the plan is not updated. `COMMIT` happens only after the human approves the plan.

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
Inventory / Purchasing re-negotiate where a shortage appears
   ↓
Revised Plan → validation → human approval
```
Human rejection triggers automatic replanning, at most 2 planning attempts in total.

# 9. LLM Role
Use the LLM for contextual reasoning, comparing multi-factor alternatives, and generating structured proposals.
## Keep these deterministic (MRPII service):
- BOM calculations
- MPS/MRP calculations
- Quantity calculations
- Capacity check and constraint validation
## Final plan validation:
LLM output must be structured and validated before execution.


# 10. 25% Definition of Done
The agent can:
- Receive customer orders.
- Create/update an MPS.
- Run MRP and identify requirements/shortages.
- Request inventory availability.
- Receive the negotiated result (agreement or `FAILED`).
- Produce an updated plan and validate it deterministically.
- Submit the plan for human approval; replan on rejection (max 2 attempts).
- Receive a simulated disruption.
- Re-evaluate and replan.
- Produce and record a revised plan.
