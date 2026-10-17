# Core Idea:
Initial agreement → disruption → agents communicate → negotiate → revised agreement → another disruption → negotiate again → final feasible plan.

# Base Scenario — Initial Plan
Let's use one simple product: Office Chair

Customer Orders:
Order	Qty	Due
O001	100	Oct 5
O002	60	Oct 7

Total = 160 chairs

BOM
1 Chair
├── 1 Frame
├── 1 Seat
└── 5 Wheels

## Initial plan:
```text
Customer Orders
       ↓
Production Planning Agent
       ↓
MRP
       ↓
Check Inventory
       ↓
Inventory Agent
       ↓
Check Procurement
       ↓
Purchasing Agent
       ↓
Negotiation
       ↓
     AGREEMENT
       ↓
Production Plan
``` 
- Now the Simulation module can inject different events.

# Variant 1 — Supplier Delay
Initial situation
- Inventory → 60 Frames
- Purchasing → 100 Frames from Supplier A

Everything is feasible.

## Disruption

### Simulation:
Supplier A is delayed by 3 days.

Flow
```text
Simulation
   ↓
SUPPLIER_DELAY
   ↓
Purchasing Agent
   ↓
"Supplier A will arrive late."
   ↓
Production Planning Agent
   ↓
"Current plan may miss deadline."
   ↓
Inventory Agent
   ↓
"Can I provide additional frames?"
   ↓
Purchasing Agent
   ↓
"Can another supplier deliver faster?"
   ↓
Negotiation
   ↓
REVISED PLAN
```

### Possible outcome:
Inventory → +20
Supplier B → remaining 80


# Variant 2 — Sudden Demand Increase
Initial situation
- Demand = 160 chairs
- Available resources = sufficient

## Disruption

### Simulation:
New customer order of 40 chairs arrives.

Now:
160 → 200 chairs

Flow
```text
Simulation
   ↓
NEW_ORDER
   ↓
Production Planning Agent
   ↓
Recalculate MRP
   ↓
New requirements
   ↓
Inventory Agent
   ↓
"Can I support the additional requirement?"
   ↓
Purchasing Agent
   ↓
"Additional procurement required."
   ↓
Negotiation
   ↓
REVISED PRODUCTION PLAN
```
- This demonstrates dynamic demand adaptation.


# Variant 3 — Supplier Price Increase
Initial situation
- Supplier A
- 100 frames
- ₹100/frame

## Disruption

### Simulation:
- Supplier A increases price to ₹130/frame.
- The material is still available.
- But Purchasing Agent's constraint might be:
- Maximum acceptable price = ₹115

Flow
```text
Simulation
   ↓
PRICE_CHANGE
   ↓
Purchasing Agent
   ↓
"₹130 exceeds my acceptable limit."
   ↓
Search alternative suppliers
   ↓
Supplier B
₹110/frame
   ↓
Purchasing Agent negotiates
   ↓
Agreement
   ↓
Production Planning informed
   ↓
PLAN CONTINUES
```

- This demonstrates that negotiation isn't only about quantity.

### It can involve:
Cost
Quantity
Delivery date


# Variant 4 — Inventory Reservation Changes
Initial situation
- Inventory Agent has:
Frames = 100
- Production Planning expects to use:
80

Everything is feasible.

## Disruption

### Simulation:
- Another high-priority order reserves 30 frames.
Now:
- Available = 100 - 30
         = 70  
- But Production Planning needs 80.

Flow
```text
Simulation
   ↓
INVENTORY_RESERVATION
   ↓
Inventory Agent
   ↓
"Only 70 frames are available."
   ↓
Production Planning Agent
   ↓
"Need 80."
   ↓
Negotiation
   ↓
Inventory offers 70
   ↓
Purchasing Agent procures 10
   ↓
Agreement
   ↓
Revised Plan
```

- This demonstrates resource allocation under changing constraints.


# Variant 5 — Customer Due-Date Change
Initial situation
- Order: 100 chairs
- Due: Oct 8
- There is enough time to procure materials.

## Disruption

### Simulation:
- Customer changes delivery date from Oct 8 → Oct 5.
- Now the agents have to reconsider the schedule.

Flow
```text 
Simulation
   ↓
DUE_DATE_CHANGE
   ↓
Production Planning Agent
   ↓
"New deadline is earlier."
   ↓
Inventory Agent
   ↓
"Can I allocate material immediately?"
   ↓
Purchasing Agent
   ↓
"Can supplier deliver earlier?"
   ↓
Negotiation
   ↓
New procurement terms
   ↓
Revised production schedule
```

- This demonstrates deadline-driven negotiation.


# Variant 6 — Supplier Quantity Reduction
Initial situation
- Required = 100 frames
- Supplier A can provide = 100

## Disruption

### Simulation:
- Supplier A's available quantity drops from 100 → 60.

Flow
```text
Simulation
   ↓
SUPPLIER_CAPACITY_REDUCTION
   ↓
Purchasing Agent
   ↓
"Supplier A can only provide 60."
   ↓
Production Planning Agent
   ↓
"Need remaining 40."
   ↓
Purchasing searches alternatives
   ↓
Supplier B
   ↓
Negotiation
   ↓
Combined procurement
   ↓
REVISED PLAN
```


# Variant 7 — Multiple Disruptions Together
- Start with:
160 chairs
↓
Initial plan created
↓
Agreement reached

- Then Simulation triggers:

## Disruption 1
- Supplier A delayed by 3 days.
- Agents renegotiate.

Then:

## Disruption 2
- New order of 40 chairs arrives.
- Agents renegotiate again.

Final flow:
```text
                 INITIAL ORDERS
                       ↓
             Production Planning
                       ↓
                    MRP
                       ↓
                Inventory Check
                       ↓
                 Negotiation
                       ↓
                Purchasing
                       ↓
                INITIAL PLAN
                       │
             ┌─────────▼─────────┐
             │    SIMULATION     │
             │  Scenario Manager │
             └─────────┬─────────┘
                       │
                 Supplier Delay
                       ↓
               RE-NEGOTIATION
                       ↓
                REVISED PLAN
                       │
                       ↓
                 New Customer
                    Order
                       ↓
               Recalculate MRP
                       ↓
               RE-NEGOTIATION
                       ↓
                FINAL PLAN
```