# Scenario 1 — Normal Production Planning

## Scenario:
Produce 1,000 SmartPhone X1 units for a customer order.

## Initial conditions:
Inventory contains some required components, while the remaining quantities must be procured.

## Trigger:
New customer order for 1,000 units with a defined due date.

## Affected agents:
Planning Agent, Inventory Agent, Purchasing Agent.

## Expected negotiations:
Planning requests material allocation from Inventory. For shortages, Purchasing obtains supplier options and negotiates procurement terms. Agents coordinate toward a feasible production plan.

## Constraints:
- Available inventory cannot be over-allocated.
- Safety-stock requirements must be respected.
- Supplier lead times must be respected.
- Required quantities must be available before production.

## Expected final outcome:
A validated procurement and production plan for 1,000 smartphones.

## What the scenario proves:
The complete baseline MRPII workflow and autonomous coordination of the three agents.



# Scenario 2 — Supplier Delivery Delay

## Scenario:
A supplier cannot deliver a required component on the originally promised date.

## Initial conditions:
A production plan already exists and depends on the supplier delivery.

## Trigger:
Supplier delivery date is delayed.

## Affected agents:
Planning Agent, Purchasing Agent, Inventory Agent.

## Expected negotiations:
Purchasing evaluates revised supplier availability/terms. Planning evaluates the impact on production. Inventory reports current availability. Agents negotiate a feasible alternative.

## Constraints:
- Delayed material cannot be used before its new availability date.
- Existing inventory constraints remain valid.
- Customer due date should be respected where feasible.

## Expected final outcome:
A revised procurement/production plan that remains feasible.

## What the scenario proves:
Agents can react to an external disruption and re-plan instead of relying on a fixed plan.



# Scenario 3 — Demand Increase

## Scenario:
The customer increases the order from 1,000 → 1,300 SmartPhone X1 units.

## Initial conditions:
The original 1,000-unit plan has already been generated.

## Trigger:
Customer demand increases by 300 units.

## Affected agents:
Planning Agent, Inventory Agent, Purchasing Agent.

## Expected negotiations:
Planning recalculates material requirements. Inventory checks additional availability. Purchasing handles newly identified shortages and negotiates additional procurement.

## Constraints:
- Existing allocations must be respected.
- Additional materials require valid supplier lead times.
- Capacity and production constraints must be respected.

## Expected final outcome:
A revised plan capable of handling the increased demand, or a clearly identified constrained quantity/date.

## What the scenario proves:
The system can recalculate requirements and coordinate additional resources when demand changes.



# Scenario 4 — Supplier Quantity Reduction

## Scenario:
A supplier originally committed to 500 Display Assemblies but can now supply only 300.

## Initial conditions:
The production plan depends on the original supplier quantity.

## Trigger:
Supplier reduces committed quantity.

## Affected agents:
Purchasing Agent, Planning Agent, Inventory Agent.

## Expected negotiations:
Purchasing searches/evaluates alternative procurement possibilities. Planning determines the production impact. Inventory reports available displays and other constraints.

## Constraints:
- Supplier cannot provide more than the revised quantity.
- Inventory cannot exceed available quantity.
- Production cannot require unavailable displays.
- Alternative supply must respect lead time/cost constraints.

## Expected final outcome:
Alternative procurement or a revised feasible production plan.

## What the scenario proves:
Agents can respond to resource shortages and negotiate alternatives.



# Scenario 5 — Supplier Price Increase

## Scenario:
A supplier increases the price of a required component.

## Initial conditions:
A supplier was previously considered acceptable under the existing procurement plan.

## Trigger:
Supplier increases the component price.

## Affected agents:
Purchasing Agent, Planning Agent, Inventory Agent.

## Expected negotiations:
Purchasing compares available supplier options and evaluates the trade-off between cost, quantity, lead time, and availability. Planning evaluates the effect on the production plan.

## Constraints:
- Production requirements must still be satisfied.
- Supplier lead times must be respected.
- Procurement must remain within defined business constraints.
- Cheapest option is not automatically the only criterion.

## Expected final outcome:
A procurement decision and feasible plan based on multiple negotiation factors.

## What the scenario proves:
Negotiation is multi-factor rather than price-only and agents can reason about trade-offs.



# Scenario 6 — Inventory Reservation Change

## Scenario:
Some inventory previously considered available becomes reserved for another requirement.

## Initial conditions:
The planning process has already considered that inventory available.

## Trigger:
An inventory reservation changes, reducing allocatable stock.

## Affected agents:
Inventory Agent, Planning Agent, Purchasing Agent.

## Expected negotiations:
Inventory reports the new allocatable quantity. Planning evaluates the resulting shortage. Purchasing handles procurement if additional material is required.

## Constraints:
- Reserved inventory cannot be double allocated.
- Safety-stock constraints must remain valid.
- Production cannot consume unavailable inventory.

## Expected final outcome:
- A revised allocation/procurement/production plan.

## What the scenario proves:
The system responds to internal resource-state changes, not just external supplier events.



# Scenario 7 — Customer Due-Date Change

## Scenario:
The customer changes the due date from 30 days → 20 days.

## Initial conditions:
A feasible 30-day production plan already exists.

## Trigger:
Customer requests an earlier delivery.

## Affected agents:
Planning Agent, Inventory Agent, Purchasing Agent.

## Expected negotiations:
Planning evaluates the compressed schedule. Inventory checks immediate availability. Purchasing evaluates whether suppliers can meet earlier requirements and negotiates delivery/quantity terms.

## Constraints:
- Supplier lead times cannot be ignored.
- Inventory cannot be over-allocated.
- Production capacity must be respected.
- The new deadline cannot be treated as automatically achievable.

## Expected final outcome:
A revised plan meeting the new deadline when feasible, or a validated alternative when constraints prevent it.

## What the scenario proves:
Agents can re-plan based on changing priorities and deadlines while respecting real constraints.