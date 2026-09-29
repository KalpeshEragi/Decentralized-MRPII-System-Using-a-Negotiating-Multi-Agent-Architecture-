## Overview

The system uses a single PostgreSQL (Neon Severless) database organized into logical schemas.
The database acts as the shared system of record, while autonomous agents make
decisions using domain services/tools.

### Logical Schemas

- `core` — Products, items, and BOM
- `sales` — Customers, customer orders, and customer ordered items
- `inventory` — Warehouses, stock, and reservations
- `planning` — MPS and MRP requirements
- `purchasing` — Suppliers, supplier items and procurement
- `production` — Machines, production orders, and schedules
- `agent` — Agent definitions and internal agent state
- `negotiation` — Multi-agent negotiation sessions, participants (agents), offers, agreements and messages
- `simulation` — What-if scenarios and simulated disruptions (events)
- `audit` — Agent decision history

---

# 1. Core Schema

## `core.items`

Stores all products and materials used by the MRPII system.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique item ID |
| `sku` | VARCHAR | UNIQUE, NOT NULL | Stock keeping unit |
| `name` | VARCHAR | NOT NULL | Item name |
| `item_type` | ENUM | NOT NULL | Finished product / raw material / component |
| `unit` | VARCHAR | NOT NULL | Unit of measurement |
| `description` | TEXT | | Item description |
| `is_active` | BOOLEAN | DEFAULT TRUE | Whether item is active |
| `created_at` | TIMESTAMP | | Creation time |
| `updated_at` | TIMESTAMP | | Last update time |

---

## `core.bom`

Stores Bill of Materials (BOM) definitions for products.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | BOM ID |
| `parent_item_id` | UUID | FK → `core.items.id` | Finished/parent item |
| `version` | INTEGER | NOT NULL | BOM version |
| `is_active` | BOOLEAN | DEFAULT TRUE | Active BOM version |
| `created_at` | TIMESTAMP | | Creation time |

---

## `core.bom_items`

Stores the components required by a BOM.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | UUID | PK | BOM item ID |
| `bom_id` | UUID | FK → `core.bom.id` | Parent BOM |
| `component_item_id` | UUID | FK → `core.items.id` | Required component |
| `quantity_required` | DECIMAL | NOT NULL | Quantity required per parent item |

---

# 2. Sales Schema

## `sales.customers`

Stores customer information.

| Column         | Type      | Constraint | Description         |
| -------------- | --------- | ---------- | ------------------- |
| `id`           | UUID      | PK         | Customer ID         |
| `name`         | VARCHAR   | NOT NULL   | Customer name       |
| `location`     | VARCHAR   | NOT NULL   | Customer location   |
| `contact_info` | JSONB     | NOT NULL   | Contact information |
| `created_at`   | TIMESTAMP |            | Creation time       |

---

## `sales.customer_orders`

Stores customer orders.

| Column         | Type      | Constraint                | Description            |
| -------------- | --------- | ------------------------- | ---------------------- |
| `id`           | UUID      | PK                        | Order ID               |
| `customer_id`  | UUID      | FK → `sales.customers.id` | Customer               |
| `order_number` | VARCHAR   | UNIQUE, NOT NULL          | Order number           |
| `order_date`   | DATE      | NOT NULL                  | Order date             |
| `due_date`     | DATE      | NOT NULL                  | Required delivery date |
| `priority`     | INTEGER   | NOT NULL                  | Order priority         |
| `status`       | VARCHAR   |                           | Order status           |
| `created_at`   | TIMESTAMP |                           | Creation time          |

---

## `sales.customer_order_items`

Stores products and quantities within customer orders.

| Column     | Type    | Constraint                      | Description      |
| ---------- | ------- | ------------------------------- | ---------------- |
| `id`       | UUID    | PK                              | Order item ID    |
| `order_id` | UUID    | FK → `sales.customer_orders.id` | Customer order   |
| `item_id`  | UUID    | FK → `core.items.id`            | Ordered item     |
| `quantity` | DECIMAL | NOT NULL                        | Ordered quantity |

```text
sales.customers
       │
       └──< sales.customer_orders
                    │
                    └──< sales.customer_order_items >── core.items
```

---

# 3. Inventory Schema

## `inventory.warehouses`

Stores warehouse information.

| Column     | Type    | Constraint | Description        |
| ---------- | ------- | ---------- | ------------------ |
| `id`       | UUID    | PK         | Warehouse ID       |
| `name`     | VARCHAR | NOT NULL   | Warehouse name     |
| `location` | VARCHAR | NOT NULL   | Warehouse location |

---

## `inventory.inventory_balance`

Stores current inventory quantities.

| Column         | Type      | Constraint                     | Description          |
| -------------- | --------- | ------------------------------ | -------------------- |
| `id`           | UUID      | PK                             | Inventory record ID  |
| `item_id`      | UUID      | FK → `core.items.id`           | Item                 |
| `warehouse_id` | UUID      | FK → `inventory.warehouses.id` | Warehouse            |
| `on_hand`      | DECIMAL   | NOT NULL                       | Physical stock       |
| `reserved`     | DECIMAL   | DEFAULT 0                      | Reserved stock       |
| `safety_stock` | DECIMAL   | DEFAULT 0                      | Minimum safety stock |
| `updated_at`   | TIMESTAMP |                                | Last update          |

### Available Quantity

```text
available_quantity =
    on_hand - reserved - safety_stock
```

---

## `inventory.inventory_reservations`

Stores inventory reservations.

| Column         | Type      | Constraint                      | Description        |
| -------------- | --------- | ------------------------------- | ------------------ |
| `id`           | UUID      | PK                              | Reservation ID     |
| `item_id`      | UUID      | FK → `core.items.id`            | Reserved item      |
| `warehouse_id` | UUID      | FK → `inventory.warehouses.id`  | Warehouse          |
| `order_id`     | UUID      | FK → `sales.customer_orders.id` | Related order      |
| `quantity`     | DECIMAL   | NOT NULL                        | Reserved quantity  |
| `status`       | VARCHAR   |                                 | Reservation status |
| `created_at`   | TIMESTAMP |                                 | Creation time      |

---

# 4. Planning Schema

## `planning.mps_plans`

Stores Master Production Schedule (MPS) plans.

| Column             | Type      | Constraint                      | Description                 |
| ------------------ | --------- | ------------------------------- | --------------------------- |
| `id`               | UUID      | PK                              | MPS plan ID                 |
| `order_id`         | UUID      | FK → `sales.customer_orders.id` | Related customer order      |
| `item_id`          | UUID      | FK → `core.items.id`            | Product                     |
| `planned_quantity` | DECIMAL   | NOT NULL                        | Planned production quantity |
| `planned_start`    | TIMESTAMP | NOT NULL                        | Planned start               |
| `planned_end`      | TIMESTAMP | NOT NULL                        | Planned completion          |
| `status`           | VARCHAR   |  NOT NULL                       | Plan status                 |
| `created_at`       | TIMESTAMP |                                 | Creation time               |

---

## `planning.mrp_requirements`

Stores material requirements calculated from MRP.

| Column                | Type      | Constraint                   | Description                  |
| --------------------- | --------- | ---------------------------- | ---------------------------- |
| `id`                  | UUID      | PK                           | MRP requirement ID           |
| `mps_plan_id`         | UUID      | FK → `planning.mps_plans.id` | MPS plan                     |
| `item_id`             | UUID      | FK → `core.items.id`         | Required material            |
| `gross_requirement`   | DECIMAL   | NOT NULL                     | Total material required      |
| `available_inventory` | DECIMAL   | NOT NULL                     | Available inventory          |
| `net_requirement`     | DECIMAL   | NOT NULL                     | Additional quantity required |
| `required_by`         | TIMESTAMP | NOT NULL                     | Required date                |
| `status`              | VARCHAR   | NOT NULL                     | Requirement status           |

---

# 5. Purchasing Schema

## `purchasing.suppliers`

Stores supplier information.

| Column         | Type    | Constraint   | Description                  |
| -------------- | ------- | ------------ | ---------------------------- |
| `id`           | UUID    | PK           | Supplier ID                  |
| `name`         | VARCHAR | NOT NULL     | Supplier name                |
| `contact_info` | JSONB   |              | Supplier contact information |
| `rating_data`  | JSONB   |              | Supplier evaluation data     |
| `is_active`    | BOOLEAN | DEFAULT TRUE | Whether supplier is active   |

---

## `purchasing.supplier_items`

Stores supplier-specific item information.

| Column           | Type    | Constraint                     | Description            |
| ---------------- | ------- | ------------------------------ | ---------------------- |
| `id`             | UUID    | PK                             | Supplier item ID       |
| `supplier_id`    | UUID    | FK → `purchasing.suppliers.id` | Supplier               |
| `item_id`        | UUID    | FK → `core.items.id`           | Supplied item          |
| `lead_time_days` | INTEGER | NOT NULL                       | Expected lead time     |
| `min_order_qty`  | DECIMAL | NOT NULL                       | Minimum order quantity |
| `available_qty`  | DECIMAL | NOT NULL                       | Available quantity     |

---

## `purchasing.purchase_requisitions`

Stores procurement requirements generated by the planning process.

| Column              | Type      | Constraint             | Description                |
| ------------------- | --------- | ---------------------- | -------------------------- |
| `id`                | UUID      | PK                     | Requisition ID             |
| `item_id`           | UUID      | FK → `core.items.id`   | Required item              |
| `quantity_required` | DECIMAL   | NOT NULL               | Required quantity          |
| `required_by`       | TIMESTAMP | NOT NULL               | Required date              |
| `priority`          | INTEGER   | NOT NULL               | Procurement priority       |
| `status`            | VARCHAR   |                        | Requisition status         |
| `created_by_agent`  | UUID      | FK → `agent.agents.id` | Agent creating requisition |
| `created_at`        | TIMESTAMP |                    | Creation time              |

---

# 6. Production Schema

## `production.machines`

Stores manufacturing machines/resources.

| Column             | Type    | Constraint | Description    |
| ------------------ | ------- | ---------- | -------------- |
| `id`               | UUID    | PK         | Machine ID     |
| `machine_code`     | VARCHAR | UNIQUE     | Machine code   |
| `name`             | VARCHAR | NOT NULL   | Machine name   |
| `capacity_per_day` | DECIMAL |            | Daily capacity |
| `status`           | VARCHAR |            | Machine status |

---

## `production.production_orders`

Stores production orders.

| Column     | Type    | Constraint                      | Description         |
| ---------- | ------- | ------------------------------- | ------------------- |
| `id`       | UUID    | PK                              | Production order ID |
| `order_id` | UUID    | FK → `sales.customer_orders.id` | Customer order      |
| `item_id`  | UUID    | FK → `core.items.id`            | Product             |
| `quantity` | DECIMAL | NOT NULL                        | Production quantity |
| `priority` | INTEGER | NOT NULL                        | Production priority |
| `status`   | VARCHAR |                                 | Production status   |

---

## `production.production_schedule`

Stores machine-level production schedules.

| Column                | Type      | Constraint                             | Description      |
| --------------------- | --------- | -------------------------------------- | ---------------- |
| `id`                  | UUID      | PK                                     | Schedule ID      |
| `production_order_id` | UUID      | FK → `production.production_orders.id` | Production order |
| `machine_id`          | UUID      | FK → `production.machines.id`          | Machine          |
| `start_time`          | TIMESTAMP | NOT NULL                               | Start time       |
| `end_time`            | TIMESTAMP | NOT NULL                               | End time         |
| `status`              | VARCHAR   |                                        | Schedule status  |

---

# 7. Agent Schema

## `agent.agents`

Stores autonomous agents participating in the MRPII system.

| Column       | Type      | Constraint | Description      |
| ------------ | --------- | ---------- | ---------------- |
| `id`         | UUID      | PK         | Agent ID         |
| `agent_code` | VARCHAR   | UNIQUE     | Agent identifier |
| `agent_type` | VARCHAR   | NOT NULL   | Agent type       |
| `name`       | VARCHAR   | NOT NULL   | Agent name       |
| `status`     | VARCHAR   |            | Agent status     |
| `created_at` | TIMESTAMP |            | Creation time    |

### 25% Agents

```text
PRODUCTION_PLANNING_AGENT
INVENTORY_AGENT
PURCHASING_AGENT
```

---

## `agent.agent_state`

Stores the agent's internal operational and negotiation state.

| Column                   | Type      | Constraint                 | Description                  |
| ------------------------ | --------- | -------------------------- | ---------------------------- |
| `agent_id`               | UUID      | PK, FK → `agent.agents.id` | Agent                        |
| `current_goal`           | JSONB     |                            | Current objective            |
| `preferred_terms`        | JSONB     |                            | Preferred negotiation terms  |
| `reserved_limits`        | JSONB     |                            | Hard/acceptable limits       |
| `initial_proposal`       | JSONB     |                            | Initial proposal             |
| `own_offer_history`      | JSONB     |                            | Agent's previous offers      |
| `opponent_offer_history` | JSONB     |                            | Offers received              |
| `dialogue_history`       | JSONB     |                            | Negotiation dialogue/context |
| `negotiation_rules`      | JSONB     |                            | Rules/policies               |
| `current_task`           | JSONB     |                            | Current task                 |
| `updated_at`             | TIMESTAMP |                            | Last update                  |

> `preferred_terms`, `reserved_limits`, and `initial_proposal` are MRPII-specific adaptations of negotiation inputs such as preferred/reserved/initial values identified in the automated-negotiation literature. For MRPII, these can represent quantity, delivery date, priority, and other relevant terms.

### Important Design Rule

The agent state stores **decision-making and negotiation state**. It should NOT duplicate the complete inventory, supplier, production, or planning databases.

---

# 8. Negotiation Schema

## `negotiation.negotiation_sessions`

Stores negotiation sessions between agents.

| Column               | Type      | Constraint             | Description           |
| -------------------- | --------- | ---------------------- | --------------------- |
| `id`                 | UUID      | PK                     | Negotiation ID        |
| `negotiation_type`   | VARCHAR   |  NOT NULL              | Type of negotiation   |
| `initiator_agent_id` | UUID      | FK → `agent.agents.id` | Initiating agent      |
| `status`             | VARCHAR   | NOT NULL               | Negotiation status    |
| `objective`          | JSONB     | NOT NULL               | Negotiation objective |
| `started_at`         | TIMESTAMP | NOT NULL               | Start time            |
| `deadline`           | TIMESTAMP | NOT NULL               | Negotiation deadline  |
| `completed_at`       | TIMESTAMP | NOT NULL               | Completion time       |

---

## `negotiation.negotiation_participants`

Stores agents participating in a negotiation.

| Column           | Type      | Constraint                                 | Description         |
| ---------------- | --------- | ------------------------------------------ | ------------------- |
| `id`             | UUID      | PK                                         | Participant record  |
| `negotiation_id` | UUID      | FK → `negotiation.negotiation_sessions.id` | Negotiation         |
| `agent_id`       | UUID      | FK → `agent.agents.id`                     | Participating agent |
| `role`           | VARCHAR   | NOT NULL                                   | Negotiation role    |
| `joined_at`      | TIMESTAMP |   | Join time           |

---

## `negotiation.negotiation_messages`

Stores communication between agents.

| Column              | Type      | Constraint                                 | Description        |
| ------------------- | --------- | ------------------------------------------ | ------------------ |
| `id`                | UUID      | PK                                         | Message ID         |
| `negotiation_id`    | UUID      | FK → `negotiation.negotiation_sessions.id` | Negotiation        |
| `message_id`        | UUID      | UNIQUE                                     | Message identifier |
| `sender_agent_id`   | UUID      | FK → `agent.agents.id`                     | Sender             |
| `receiver_agent_id` | UUID      | FK → `agent.agents.id`                     | Receiver           |
| `message_type`      | VARCHAR   |                                            | Message type       |
| `sequence_number`   | INTEGER   |                                            | Message sequence   |
| `correlation_id`    | UUID      |                                            | Related message    |
| `payload`           | JSONB     |                                            | Message content    |
| `created_at`        | TIMESTAMP |                                            | Creation time      |

### Initial Message Types

```text
INITIATED
NEGOTIATING
REQUEST
OFFER
COUNTER_OFFER
ACCEPT
REJECT
AGREEMENT_PROPOSED
COMMIT
EXPIRED
ABORTED
```

---

## `negotiation.negotiation_offers`

Stores offers and counter-offers.

| Column           | Type      | Constraint                                 | Description              |
| ---------------- | --------- | ------------------------------------------ | ------------------------ |
| `id`             | UUID      | PK                                         | Offer ID                 |
| `negotiation_id` | UUID      | FK → `negotiation.negotiation_sessions.id` | Negotiation              |
| `message_id`     | UUID      | FK → `negotiation.negotiation_messages.id` | Related message          |
| `offer_number`   | INTEGER   | NOT NULL                                   | Offer sequence           |
| `offer_type`     | VARCHAR   | NOT NULL                                   | Offer/counter-offer      |
| `terms`          | JSONB     | NOT NULL                                      | Multi-factor offer terms |
| `valid_until`    | TIMESTAMP | NOT NULL                                           | Offer validity           |
| `status`         | VARCHAR   |  NOT NULL                                           | Offer status             |
| `created_at`     | TIMESTAMP |                                            | Creation time            |

### Example Multi-Factor Offer

```json
{
  "quantity": 80,
  "delivery_date": "2026-10-05",
  "unit_cost": 105,
  "priority": 1
}
```

---

## `negotiation.negotiation_agreements`

Stores finalized negotiation agreements.

| Column           | Type      | Constraint                                 | Description                    |
| ---------------- | --------- | ------------------------------------------ | ------------------------------ |
| `id`             | UUID      | PK                                         | Agreement ID                   |
| `negotiation_id` | UUID      | FK → `negotiation.negotiation_sessions.id` | Negotiation                    |
| `agreed_terms`   | JSONB     | NOT NULL                                   | Final agreed terms             |
| `validated`      | BOOLEAN   | DEFAULT FALSE                              | Agreement validation status    |
| `committed`      | BOOLEAN   | DEFAULT FALSE                              | Whether agreement is committed |
| `created_at`     | TIMESTAMP |                                            | Creation time                  |

---

# 9. Simulation Schema

The Simulation module provides the **What-If environment** for testing disruptions without directly representing a real-world event.

## `simulation.simulation_scenarios`

Stores What-If scenarios.

| Column          | Type      | Constraint | Description            |
| --------------- | --------- | ---------- | ---------------------- |
| `id`            | UUID      | PK         | Scenario ID            |
| `name`          | VARCHAR   | NOT NULL   | Scenario name          |
| `description`   | TEXT      | NOT NULL   | Scenario description   |
| `configuration` | JSONB     | NOT NULL   | Scenario configuration |
| `created_at`    | TIMESTAMP |            | Creation time          |

---

## `simulation.simulation_events`

Stores disruptions/events triggered inside a scenario.

| Column        | Type      | Constraint                                | Description          |
| ------------- | --------- | ----------------------------------------- | -------------------- |
| `id`          | UUID      | PK                                        | Event ID             |
| `scenario_id` | UUID      | FK → `simulation.simulation_scenarios.id` | Scenario             |
| `event_type`  | VARCHAR   | NOT NULL                                  | Event type           |
| `event_time`  | TIMESTAMP | NOT NULL                                  | Simulated event time |
| `parameters`  | JSONB     | NOT NULL                                  | Event parameters     |
| `status`      | VARCHAR   |                                           | Event status         |

### Example Events

```text
SUPPLIER_DELAY
SUDDEN_DEMAND_INCREASE
SUPPLIER_QUANTITY_REDUCTION
NEW_CUSTOMER_ORDER
CUSTOMER_DUE_DATE_CHANGE
INVENTORY_RESERVATION
MULTI_DISRUPTIONS
```

### Simulation Flow

```text
Simulation Scenario
        │
        ↓
Simulation Event
        │
        ↓
Change system condition
        │
        ↓
Agents detect/re-evaluate
        │
        ↓
Communication + Negotiation
        │
        ↓
Revised Plan
```

---

# 10. Audit Schema

## `audit.decision_audit`

Stores structured records of agent decisions for traceability.

| Column              | Type      | Constraint             | Description                |
| ------------------- | --------- | ---------------------- | -------------------------- |
| `id`                | UUID      | PK                     | Audit ID                   |
| `agent_id`          | UUID      | FK → `agent.agents.id` | Agent                      |
| `decision_type`     | VARCHAR   | NOT NULL               | Type of decision           |
| `context`           | JSONB     | NOT NULL               | Relevant decision context  |
| `decision`          | JSONB     | NOT NULL               | Final decision             |
| `reasoning_summary` | TEXT      | NOT NULL               | Concise decision rationale |
| `created_at`        | TIMESTAMP |                        | Decision time              |

> Store a concise structured rationale rather than hidden chain-of-thought.

---

**Design principle:** PostgreSQL remains the shared source of truth, but the **agents own their goals, constraints, preferences, negotiation state, and decisions**. The deterministic MRPII calculations and database operations remain outside the agents, accessed through domain services/tools.
