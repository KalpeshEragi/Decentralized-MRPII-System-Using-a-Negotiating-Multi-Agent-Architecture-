# 1. Purpose
Converts procurement requirements into a feasible procurement agreement by evaluating supplier options and negotiating procurement terms with the supplier through the supplier communication interface.
## Main responsibility:
decide what quantity to procure, from which supplier option, and by when the material can be delivered.

# 2. Works With
- Inventory Agent (initiates the negotiation)
- Production Planning Agent (receives the result)
- Negotiation Engine
- Simulation / Scenario Manager
- Supplier / Procurement Service (supplier data)
- Supplier communication interface: the structured supplier form, where the tester acts as supplier. There is no Supplier Agent.
## NOTE:
The agent does not directly control inventory, production plans, suppliers, or PostgreSQL.

# 3. Core Flow
```text
REQUEST from Inventory Agent (shortage context)
      ↓
Purchasing Agent
      ↓
Check Supplier Options (Supplier / Procurement Service)
      ↓
Create purchase requisition
      ↓
Negotiate with supplier form: round N of 3
      ↓
Acceptable response ──► AGREEMENT_PROPOSED to Inventory
Supplier REJECT     ──► session REJECTED
No agreement in 3   ──► session FAILED
      ↓
Result (agreement or FAILED) reaches Production Planning
      ↓
Simulation Disruption → Re-evaluate + Re-negotiate → Revised procurement agreement
```

# 4 . Tools / Services
get_procurement_request(...)
get_supplier_options(...)
get_supplier_item_details(...)
compare_supplier_options(...)
create_purchase_requisition(...)
send_supplier_offer(...)
get_supplier_response(...)
propose_agreement(...)
validate_procurement_terms(...)

# 5. Separation
- Agent: procurement decisions, supplier evaluation, goals, constraints, preferences, negotiation strategy
- Supplier / Procurement Service: deterministic supplier data (lead time, minimum order quantity, available quantity)
- Database: repository/domain layer
- Negotiation Engine: protocol, messages, session state, round limit

# 6. Multi-Factor Decision Making
Evaluate supplier and procurement alternatives using a combination of:
- Required quantity
- Required date
- Delivery date / lead time
- Supplier available quantity
- Minimum order quantity
- Production priority
- Inventory impact
## NOTE:
The decision must not depend on one factor alone. Cost/price is out of scope for the 25% milestone: no price fields, no cost-based acceptance or rejection.

# 7. Negotiation Role
The Purchasing Agent receives a procurement REQUEST from the Inventory Agent when available inventory cannot cover the requirement (P0-02).
```text
Inventory Agent
      ↓ REQUEST
Purchasing Agent
      ↓ round 1: OFFER          ─► supplier form ─► ACCEPT / COUNTER_OFFER / REJECT
      ↓ rounds 2–3: COUNTER_OFFER ─► supplier form ─► ACCEPT / COUNTER_OFFER / REJECT
      ↓
AGREEMENT_PROPOSED ─► Inventory Agent  (COMMIT only after human approval of the plan)
```
## NOTE:
One round = one Purchasing offer/counter-offer + the supplier response; maximum 3 rounds. The supplier form carries quantity, delivery date / lead time and an optional message (no price). The tester only answers as supplier; the Purchasing Agent alone decides whether a response is acceptable. Supplier `REJECT` ends the session `REJECTED`; no agreement after 3 rounds ends it `FAILED`. In both cases Planning receives `FAILED`.

# 8. Simulation / Replanning

Simulation only injects a What-If event; the agent decides how to react.

```text
Initial Procurement Agreement
       ↓
Simulation Event (e.g. supplier delay, supplier quantity reduction)
       ↓
Changed Supplier / Procurement Condition
       ↓
Re-evaluate Supplier Options
       ↓
Re-negotiate through the supplier form
       ↓
Revised Procurement Agreement
```

# 9. LLM Role
Use the LLM for contextual reasoning, comparing multi-factor supplier alternatives, and generating structured offer/counter-offer proposals.
## Keep these deterministic (Procurement service):
- Supplier availability lookup
- Lead-time retrieval
- Supplier option comparison
- Quantity calculations
- Procurement constraint validation
## Final procurement validation:
LLM output must be structured and validated against actual supplier and procurement constraints before execution.

# 10. 25% Definition of Done
The agent can:
- Receive procurement requests from the Inventory Agent.
- Check available supplier options.
- Create a purchase requisition.
- Negotiate with the supplier form using multiple factors, within 3 rounds.
- Accept, counter or stop based on deterministic validation.
- Send `AGREEMENT_PROPOSED`, or end the session `REJECTED` / `FAILED`.
- Receive a simulated supplier/procurement disruption.
- Re-evaluate and re-negotiate.
- Produce and record a revised procurement agreement.
