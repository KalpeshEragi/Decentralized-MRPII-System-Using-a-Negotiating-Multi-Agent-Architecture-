# 1. Production Planning Agent

## NOTE
The important point is that the Production Planning Agent is not a central controller. It has its own goal, preferences and constraints, and it negotiates with the other autonomous agents. 

## Owns
The Production Planning Agent owns the production plan and material requirements derived from customer demand.

## It is responsible for:
- MPS (Master Production Schedule)
- MRP (Material Requirements Planning)
- Production quantity and priority
- Required-by dates for materials
- Identifying material shortages
- Deciding what resource/material information it needs from other agents
- Initiating negotiations when the current plan cannot be fulfilled

## Can do
- Receive/interpret a production order
- Create or update an MPS
- Run MRP through the deterministic MRP service
- Calculate gross/net material requirements
- Detect shortages
- Ask Inventory Agent for material availability
- Request procurement when inventory is insufficient
- Propose required quantity and required delivery date
- Evaluate alternative plans
- Negotiate using multiple factors
- Accept/reject/counter an offer
- Trigger replanning after a disruption or failed negotiation

## Cannot do
- Directly change inventory quantities
- Directly reserve stock
- Select or modify supplier records
- Directly create/approve purchase orders
- Directly modify machine state
- Directly execute warehouse operations
- Override Inventory/Purchasing Agent decisions
- Directly manipulate database tables

## What the agent knows
Customer Order
├── Product
├── Quantity
├── Due Date
└── Priority

Production Planning Data
├── BOM
├── MPS
├── MRP requirements
└── Current production plan

Material requirements
├── Required quantity
├── Required-by date
└── Shortage quantity

Other-agent responses
├── Inventory availability
├── Procurement offers
└── Negotiation results

It doesn't need the entire inventory database or supplier database. It asks other agents through tools/interfaces.

## What stays INSIDE the agent
ProductionPlanningAgent
│
├── current_goal
├── current_task
├── planning_preferences
├── planning_constraints
├── priority_policy
│
├── negotiation_state
├── preferred_terms
├── reserved_limits
├── initial_proposal
│
├── own_offer_history
├── opponent_offer_history
├── dialogue_history
├── negotiation_rules
│
└── decision_context

## Example:

{
  "current_goal": "Fulfill order by due date",
  "preferred_terms": {
    "delivery_date": "2026-10-05",
    "quantity": 100
  },
  "reserved_limits": {
    "latest_delivery": "2026-10-08"
  },
  "priority_policy": "minimize production delay"
}

### NOTE: 
The MRP calculation itself should NOT live inside the LLM/agent reasoning. Put it in a deterministic mrp_service.

## 2. Inventory Agent

## Owns
The Inventory Agent owns material availability and allocation decisions.

## It is responsible for:
- Current stock availability
- Reserved stock
- Safety stock
- Material allocation
- Inventory constraints
- Proposing how much material can be allocated to Production Planning

## Can do
- Check inventory availability
- Calculate available quantity
- Consider reserved stock and safety stock
- Propose material allocation
- Negotiate requested quantities
- Counter-offer when requested quantity cannot be supplied
- Temporarily reserve material after an agreement
- Release reservations when required
- Inform Production Planning about shortages
- Provide expected availability information

## Cannot do
- Change production plans
- Run MRP
- Choose suppliers
- Negotiate supplier terms
- Create purchase orders
- Directly change production schedules
- Ignore safety-stock policies imposed by its own constraints
- Modify another agent's state

## What the agent knows
Inventory
├── On-hand quantity
├── Reserved quantity
├── Safety stock
├── Warehouse
└── Material availability

Allocation
├── Current reservations
├── Pending requests
└── Allocation constraints

Negotiation context
├── Requested quantity
├── Required-by date
├── Other agent's offers
└── Current negotiation status

For example:
On hand     = 180
Reserved    = 40
Safety stock= 40

Available  = 180 - 40 - 40
           = 100

# NOTE:
The calculation can be implemented in an inventory_service; the agent uses the result to make an allocation/negotiation decision.

## What stays INSIDE the agent
InventoryAgent
│
├── current_goal
├── allocation_policy
├── safety_stock_policy
├── minimum_reserve
│
├── preferences
├── constraints
├── acceptable_allocation_range
│
├── current_task
├── negotiation_state
├── preferred_terms
├── reserved_limits
├── initial_proposal
│
├── own_offer_history
├── opponent_offer_history
├── dialogue_history
└── negotiation_rules

## Example internal decision:

Requested = 150
Can allocate = 100
Preferred = 100
Minimum acceptable = 80

→ Offer 100
→ Counter-offer if requester demands >100

# 3. Purchasing Agent

## Owns
The Purchasing Agent owns procurement decisions and supplier negotiation.

## It is responsible for:
- Procurement requirements
- Supplier evaluation
- Supplier offer comparison
- Procurement quantity
- Expected delivery
- Quantity/delivery/lead-time trade-offs
- Negotiating with suppliers

### NOTE:
For your 25% demo, the "supplier" can initially be a simulated supplier service/database rather than another autonomous agent.

## Can do
- Receive procurement requirements
- Search available suppliers
- Compare supplier offers
- Evaluate quantity, delivery date and lead time
- Generate procurement proposals
- Negotiate quantity and delivery date
- Accept/reject/counter supplier offers
- Create a purchase requisition
- Recommend/create a purchase order after agreement
- Report procurement outcome to Production Planning

## Cannot do
- Change production quantities directly
- Modify inventory directly
- Run MRP
- Reserve warehouse stock
- Change another agent's negotiation state
- Guarantee a supplier commitment without an agreed procurement result
- Directly manipulate unrelated database tables

## What the agent knows
Procurement Requirement
├── Item
├── Quantity
├── Required-by date
└── Priority

Supplier information
├── Supplier
├── Lead time
├── Minimum order quantity
├── Available quantity
└── Reliability information

Negotiation
├── Supplier offers
├── Counter-offers
├── Current agreement
└── Deadline

## Example:

Requirement:
100 units by Oct 5

Supplier A:
Lead time = 3 days
Qty = 100

Supplier B:
Lead time = 7 days
Qty = 100

### NOTE:
The Purchasing Agent evaluates this according to its own objective/constraints.

## What stays INSIDE the agent
PurchasingAgent
│
├── current_goal
├── procurement_strategy
├── preferred_terms
├── reserved_limits
├── delivery_preferences
│
├── supplier_evaluation_policy
├── acceptable_quantity_range
├── latest_acceptable_delivery
│
├── current_task
├── negotiation_state
├── initial_proposal
│
├── own_offer_history
├── opponent_offer_history
├── dialogue_history
└── negotiation_rules

## Example:

{
  "preferred_terms": {
    "quantity": 100,
    "delivery_date": "2026-10-05"
  },
  "reserved_limits": {
    "latest_delivery": "2026-10-07"
  }
}