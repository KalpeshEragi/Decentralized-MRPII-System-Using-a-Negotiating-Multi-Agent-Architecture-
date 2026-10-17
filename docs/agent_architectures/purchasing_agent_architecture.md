# Purchasing Agent Architecture

# 1. Purpose
Converts procurement requirements into a feasible procurement agreement by evaluating supplier options and negotiating procurement terms with suppliers through the supplier communication interface.

## Main responsibility
Decide what quantity to procure, from which supplier or combination of suppliers, and by when the material can be delivered. Select only solutions that are feasible and provide the best overall result under the agreed purchasing rules.

# 2. Works With
- **Inventory Agent:** supplies procurement requests when available inventory cannot cover a requirement. The integration will be connected later. (Future Integration)
- **Production Planning Agent:** receives procurement outcomes. The integration will be connected later. (Future Integration)
- **Negotiation Engine / negotiation module:** manages negotiation messages, session state and round limits. Purchasing's supplier-facing negotiation flow will be developed independently first, behind a clear interface for later integration.
- **Simulation / Scenario Manager:** later supplies What-If changes from scenarios.md. (Future Integration)
- **Supplier / Procurement Service:** provides deterministic supplier and item data, availability, lead time, minimum order quantity (MOQ), and contract lookup.
- **Supplier-facing interface:** a WhatsApp-like chat interface for request/response between Purchasing and suppliers. It displays the supplier, item, requested quantity and delivery requirement, and lets a supplier respond with available quantity, delivery date/lead time, and an optional message. It is an interface for supplier interactions, not an additional MRPII agent.

## Separation
The Purchasing Agent does not directly control inventory, production plans, supplier master data, or PostgreSQL. It uses it's responsible services and repositories. The standalone version may use local/test inputs in place of other agents until integration.

# 3. Core Flow
```text
Procurement request 
      ↓
Purchasing Agent
      ↓
Read supplier options and active Purchasing Contracts
      ↓
Check feasibility and rank single-supplier options
      ↓
Can one supplier meet the requirement?
      ├─ Yes → select the best feasible option, unless a qualifying cost-saving split is better
      └─ No  → find the best feasible split across multiple suppliers
      ↓
Create a requisition and a supplier negotiation for each selected supplier
      ↓
Request/response through the WhatsApp-like supplier interface
      ↓
Validate every response and negotiate within the round limit
      ↓
All supplier legs succeed? ── No → fail the overall split; leave agreed legs uncommitted
      │
      Yes
      ↓
Create one combined procurement outcome / agreement proposal
      ↓
Await the required approval before commitment
      ↓
Return the outcome to Inventory / Planning through integration interfaces
```

Each supplier interaction is tracked separately. A split is successful only if every required supplier leg succeeds. The standalone version must be testable without live communication to the other agents.

# 4. Tools / Services
- `get_procurement_request(...)`
- `get_supplier_options(...)`
- `get_supplier_item_details(...)`
- `get_purchasing_contract(...)`
- `compare_supplier_options(...)`
- `find_optimal_supplier_combination(...)`
- `create_purchase_requisition(...)`
- `send_supplier_request(...)`
- `get_supplier_response(...)`
- `propose_agreement(...)`
- `validate_procurement_terms(...)`
- `record_supplier_selection_and_cost_summary(...)`

These are responsibility-level examples; final function names should follow the repository's existing conventions.

# 5. Separation
- **Purchasing Agent:** supplier selection, procurement decisions, negotiation strategy, split decisions and combined procurement outcome.
- **Supplier / Procurement Service:** deterministic supplier data, including lead time, MOQ, available quantity and Purchasing Contract lookup. It does not choose suppliers on the agent's behalf.
- **Purchasing database / repository layer:** stores Purchasing-owned contracts, requisitions, supplier-leg details, negotiation references, outcomes and audit records.
- **Negotiation module / Engine:** manages message format, session state, negotiation rounds and accepted/rejected/failed/aborted states. Supplier selection and feasibility remain Purchasing decisions.
- **Supplier-facing interface:** lets suppliers respond to requests; it does not set or invent a contract price.

# 6. Multi-Factor Decision Making
Evaluate supplier and procurement alternatives using:
- Required quantity and required delivery date
- Supplier delivery date / lead time
- Supplier available quantity
- Minimum order quantity (MOQ)
- Production priority and inventory impact
- Registered Purchasing Contract price and total purchasing cost
- Extra quantity caused by MOQ and any resulting surplus

## Purchasing Contracts
Use the `purchasing.purchasing_contracts` table with these columns:

`id, supplier_id, item_id, unit_price, valid_from, valid_until, is_active`

Rules:
- A contract applies to one supplier-item pair and provides a standing unit price in INR.
- `unit_price` must be greater than zero. Contract selection must respect `is_active` and the validity dates.
- No matching, active and currently valid contract means the price is **Not Registered**. Do not treat a missing price as zero or invent/estimate one.
- Keep the contract price separate from supplier negotiation terms. The supplier chat negotiates procurement quantity and delivery date, not the contract price.

## Supplier selection and splitting rules
1. **Check feasibility first.** A supplier can be used only if it meets the delivery deadline and its available quantity and MOQ constraints.
2. **Calculate order quantity and cost.** For a single supplier, calculate the quantity required under its MOQ and available-quantity limits. For priced options, `total purchasing cost = unit price × actual order quantity`, including MOQ surplus.
3. **Prefer the best feasible priced option.** Rank by lowest total purchasing cost, then earliest arrival, then larger available quantity, then supplier name.
4. **Handle missing prices transparently.** A supplier without a registered price remains visible as a fallback if no feasible priced supplier can be used. For a single supplier, rank fallback options by earliest arrival, then larger available quantity, then supplier name, and label the result `cost ranking unavailable`.
5. **When to split:**
   - Use a split when no single supplier can meet the full shortage and required date; or
   - Use a cost-saving split when the feasible multi-supplier combination has registered prices and saves at least 10% compared with the cheapest feasible single-supplier option.
6. **Use any feasible number of suppliers.** There is no fixed two-supplier maximum. Choose the number and quantities that best satisfy the constraints and produce a meaningful improvement; do not add suppliers without a reason.
7. **Optimise the whole combination.** Each supplier leg must respect its MOQ, available quantity and delivery deadline. Combined quantities must cover the shortage. Minimise total purchasing cost, including surplus, and avoid unnecessary over-purchasing.
8. **Missing-price split:** a necessary split may include an unpriced supplier only as a clearly labelled fallback. Rank such fallback combinations by the earliest possible latest arrival across their supplier legs, then use deterministic availability/name tie-breakers; label the result `cost ranking unavailable`. Do not claim that an unpriced supplier is cheaper or present an unsupported cost comparison. A cost-saving split requires registered prices for all included suppliers.
9. **Rank combinations deterministically.** Among fully priced feasible combinations, compare total purchasing cost first, then the latest delivery date among the selected supplier legs (earlier is better), followed by deterministic availability/name tie-breakers. Record the combinations considered so the selected result can be explained and reproduced.
10. **Keep the result explainable.** Record the options considered, feasibility, registered price or `Not Registered`, selected quantities, costs where known, arrival dates, and why the final solution was selected.

The deterministic backend selects the supplier or supplier combination. The LLM may explain the decision but cannot override the selection or fabricate price information.

# 7. Negotiation Role
The Purchasing Agent receives a procurement request when available inventory cannot cover the requirement. During independent development, the request may be supplied through a test API; the agreed Inventory Agent interface will be connected later.

```text
Procurement request
      ↓
Purchasing Agent selects one supplier or a multi-supplier combination
      ↓
Create a separate supplier negotiation for each selected supplier
      ↓
Purchasing sends OFFER / COUNTER_OFFER via the WhatsApp-like interface
      ↓
Supplier responds: ACCEPT / COUNTER_OFFER / REJECT
      ↓
Purchasing validates the response against the supplier/s and procurement constraints
      ↓
Repeat as needed, up to 3 rounds per supplier negotiation
      ↓
Every supplier leg succeeds? ── No → fail the overall split; abort successful legs without committing them
      │
      Yes
      ↓
Create a combined AGREEMENT_PROPOSED outcome
      ↓
Commit only after the required approval
```

## Negotiation rules
- One round means one Purchasing offer/counter-offer and the supplier's response; the maximum is three rounds per supplier negotiation.
- The supplier interface carries requested/proposed quantity, delivery date or lead time, and an optional message. It does not ask the supplier to negotiate the registered contract price.
- Purchasing alone decides whether a supplier response satisfies the constraints; a supplier's acceptance does not bypass deterministic validation.
- A supplier `REJECT`, or no acceptable agreement after three rounds, fails that supplier leg.
- If any required leg fails, the overall split fails. Any leg that had agreed is aborted and remains uncommitted; it must not create a scheduled receipt. Report and explain the quantity that could have been covered and why it failed.
- Create the combined proposal only after all required supplier legs succeed. Final plan approval and cross-agent commitment will be connected during integration; the Purchasing-side proposal and approval handling can be developed independently.

# 8. Simulation / Replanning (Future Integration)
Simulation only injects a What-If event; the owning agent/service applies the data change, and Purchasing decides how supplier changes affect procurement.

```text
Existing procurement outcome
      ↓
Simulation event (for example supplier delay or quantity reduction)
      ↓
Supplier / inventory / order data updated through its owning service
      ↓
Purchasing re-checks affected supplier legs and agreements
      ↓
Record invalidation where the commitment is no longer feasible
      ↓
Re-select supplier(s) and re-negotiate through the supplier-facing interface
      ↓
Revised procurement outcome
      ↓
Planning re-evaluation after integration
```

The Scenario Manager must not directly edit Purchasing agreements or make supplier-selection decisions. During independent development, Purchasing's supplier-change handler can be built and tested with supplied event data; connection to the shared Scenario Manager and Planning Agent comes later.

# 9. LLM Role
Use the LLM for contextual reasoning, preparing structured offer/counter-offer proposals, and explaining the deterministic supplier or supplier-combination decision.

## Keep these deterministic
- Supplier and Purchasing Contract lookup
- Contract validity checks and missing-price handling
- Supplier feasibility and ranking
- Combination search, quantity allocation and cost calculations
- MOQ, available-quantity and delivery-deadline checks
- Procurement-term validation and final supplier selection
- Agreement/leg state transitions and persistence

## Final procurement validation
LLM output must be structured and validated against actual supplier, contract and procurement constraints before execution. The LLM must never change the selected supplier or quantities, negotiate contract price, treat `Not Registered` as zero, or invent/estimate a price. Purchasing builds a deterministic cost-comparison summary for auditing; the LLM's rationale is stored as an explanation, not as evidence. Reject unsupported price claims and fall back to the deterministic decision policy.

# 10. Independent Development Scope and Integration

## Build as part of the Purchasing Agent now
- Purchasing Contracts and validity-aware contract lookup
- Supplier option evaluation, cost ranking and deterministic multi-supplier optimisation
- Purchasing-owned requisitions and records linking each supplier leg to its contract (if any) and negotiation
- WhatsApp-like supplier-facing request/response interface
- Supplier negotiation rounds, response validation and multi-supplier split coordination
- Combined proposal, Purchasing-side approval handling, failure/abort behaviour and audit records
- LLM explanation with strict validation and deterministic fallback
- Standalone API, database and automated tests, using test inputs where other agents are not yet integrated

## Connect during multi-agent integration
- Actual A2A requests/responses with Inventory and Planning
- Shared Publish–Subscribe events and the Message Broker
- Shared Negotiation Engine/protocol adapters, where appropriate
- Scenario Manager event delivery and automatic Planning re-evaluation
- Cross-agent approval/commit and scheduled-receipt updates

Keep integration points behind clear interfaces so Purchasing can be developed and tested now without implementing or pretending that the other agents are already connected.

# 11. Testing and Definition of Done
- Test contract lookup for active, inactive, valid, expired and missing contracts.
- Test feasibility, total-cost calculation, MOQ surplus, delivery constraints and deterministic tie-breaking.
- Test when a split is necessary and when the 10% cost-saving rule permits a split.
- Test combination selection across multiple suppliers, including availability/MOQ constraints, surplus and missing-price fallbacks.
- Test supplier request/response through the WhatsApp-like interface, including acceptance, counter-offer, rejection and the three-round limit.
- Test that all supplier legs must succeed before a combined proposal is created; a failed split aborts accepted legs without committing them or counting scheduled receipts.
- Test that the LLM cannot change supplier selection, quantity allocation or price data, and that unsupported price claims trigger deterministic fallback.
- Test Purchasing APIs and persistence with a test database. Use test doubles for other agents until integration is ready.
- Test supplier-change handling independently.