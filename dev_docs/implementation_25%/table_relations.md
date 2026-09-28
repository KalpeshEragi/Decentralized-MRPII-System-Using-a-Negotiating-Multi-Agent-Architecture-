# 1. Core Schema
```text
                    ┌──────────────┐
                    │ core.items   │
                    └──────┬───────┘
                           │
                  parent   │ 1:N
                           ▼
                    ┌──────────────┐
                    │  core.bom    │
                    └──────┬───────┘
                           │ 1:N
                           ▼
                    ┌──────────────┐
                    │ bom_items    │
                    └──────┬───────┘
                           │ N:1
                           ▼
                    ┌──────────────┐
                    │ core.items   │
                    └──────────────┘
```

# 2. Sales Schema
```text
                    ┌──────────────┐
                    │ core.items   │
                    └──────┬───────┘
                           │
                  parent   │ 1:N
                           ▼
                    ┌──────────────┐
                    │  core.bom    │
                    └──────┬───────┘
                           │ 1:N
                           ▼
                    ┌──────────────┐
                    │ bom_items    │
                    └──────┬───────┘
                           │ N:1
                           ▼
                    ┌──────────────┐
                    │ core.items   │
                    └──────────────┘
```
# 3. Inventory Schema
```text
                 core.items
                 /        \
                /          \
             1:N            1:N
              ↓              ↓
     inventory_balance   reservations
              ↑              ↑
             1:N            1:N
              │              │
        warehouses      customer_orders
```
# 4. Planning Schema
```text
         customer_orders
               │
               │ 1:N
               ▼
           mps_plans
               │
               │ 1:N
               ▼
        mrp_requirements
               ▲
               │ N:1
               │
   core.items
```
# 5. Purchasing Schema
```text
suppliers ──1:N──> supplier_items <──N:1── core.items
                                             │
                                             │ 1:N
                                             ▼
                                    purchase_requisitions
                                             ▲
                                             │ N:1
                                             │
                                        agent.agents
```
# 6. Production Schema
```text
          sales.customer_orders
                    │
                    │ 1 : N
                    ▼
        production.production_orders
                    │
                    │ N : 1 
                    ▼
        production.machines
                    │
                    │
                    └──── production.production_schedule
                                 │
                                 │ N : 1
                                 ▼
                      production.production_orders
```
# 7. Agent Schema
```text
       agent.agents
             │
             │ 1 : 1
             ▼
     agent.agent_state
```
# 8. Negotiation Schema
```text
agent.agents ──1:N──> negotiation_participants <──N:1── negotiation_sessions
                                                        │
                                                        ├──1:N──> negotiation_messages
                                                        │                │
                                                        │                └──1:N──> negotiation_offers
                                                        │
                                                        └──1:N──> negotiation_agreements
                                         ## NOTE: Agent ↔ Negotiation Session: M:N, through negotiation_participants.              
```
# 9. Simulation Schema
```text
         simulation_scenarios
                  │
                  │ 1 : N
                  ▼
          simulation_events
```
# 10. Audit Schema
```text
         agent.agents
               │
               │ 1 : N
               ▼
        audit.decision_audit
```