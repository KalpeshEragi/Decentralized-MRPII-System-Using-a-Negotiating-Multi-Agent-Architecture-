# C9 — Simulation Event Types and Parameters

## Status

**Status:** DRAFT (2026-09-30) — proposal for developer review. Nothing here is implemented.

**Owner:** Project developer

**Depends on:** `dev_docs/implementation_25%/scenarios.md` (source of truth, not modified), `docs/smartphone_x1_fixture.md`
§7 (scenario data), C8 (what re-evaluation does to plan attempts), C2 (`simulation.*` tables).

## Purpose

Defines the What-If events the Scenario Manager can inject for scenarios 2, 3, 4, 6 and 7, their parameters, which
owning service applies each one, and how agents are told to re-evaluate. Scenario 1 is the baseline (no event).
Scenario 5 (price) is out of scope.

## Scope

- Event types and their JSON parameters.
- The owning service that applies each change.
- The Scenario Manager's steps and the event status lifecycle.
- Storage in `simulation.simulation_scenarios` / `simulation.simulation_events`.

## Does Not Define

- How agents respond: the agents decide (CLAUDE.md, Simulation).
- Approval and attempt handling after re-evaluation: C8.

## Specification

### 1. Principle

The Scenario Manager **injects** a change through the service that owns the data, then asks the Production Planning
Agent to re-evaluate the affected order. It never changes plans, sessions or agent state and never decides a response.
No timers: an event is applied immediately when the tester triggers it (`event_time` = the request time).

### 2. Event types (proposed)

| Event type | Scenario | Parameters | Owning service (change) |
| --- | --- | --- | --- |
| `SUPPLIER_LEAD_TIME_CHANGED` | S2 | `supplier`, `item_id`, `lead_time_days` | `supplier_service` (supplier_items.lead_time_days) |
| `ORDER_QUANTITY_CHANGED` | S3 | `order_id`, `item_id`, `quantity` | `order_service` (order line quantity) |
| `SUPPLIER_AVAILABLE_QTY_CHANGED` | S4 | `supplier`, `item_id`, `available_qty` | `supplier_service` (supplier_items.available_qty) |
| `INVENTORY_RESERVATION_CHANGED` | S6 | `item_id`, `reserved` | `inventory_service` (reserved quantity, see O2) |
| `ORDER_DUE_DATE_CHANGED` | S7 | `order_id`, `due_date` | `order_service` (due_date; `due_date >= order_date`) |

No cost/price event. Parameters are validated deterministically before anything changes (unknown supplier/item/order
→ `NOT_FOUND`; negative quantity, lead time or a due date before the order date → `VALIDATION_ERROR`).

X1 values (fixture §7): S2 `{"supplier": "Volt Power", "lead_time_days": 27}` for Battery; S3 `quantity` 1300;
S4 `{"supplier": "Alpha Displays", "available_qty": 300}` for Display; S6 Speaker `reserved` 500; S7 `due_date` 2026-10-21.

```json
{
  "event_type": "SUPPLIER_LEAD_TIME_CHANGED",
  "parameters": { "supplier": "Volt Power", "item_id": "6f1c0e2a-0000-4000-8000-000000000003", "lead_time_days": 27 }
}
```

```json
{
  "event_type": "ORDER_DUE_DATE_CHANGED",
  "parameters": { "order_id": "6f1c0e2a-0000-4000-8000-000000000100", "due_date": "2026-10-21" }
}
```

### 3. Scenario Manager steps

```text
1. validate the event parameters                         (refused -> event not stored, nothing changes)
2. store simulation_events row, status PENDING
3. apply the change through the owning service           (one transaction with step 4)
4. status APPLIED  (or FAILED with the error, nothing changed)
5. PlanningAgent.re_evaluate(order_id, cause = event id)  -> C8: the open attempt becomes SUPERSEDED, a new attempt
   runs (plan -> Inventory -> Purchasing negotiations for the new or changed shortages)
6. return the event and the new attempt's summary
```

Event status: `PENDING` → `APPLIED` | `FAILED`. Supplier and inventory events affect every open order that uses the
item; in the 25% demo that is SO-0001.

### 4. Storage

`simulation.simulation_scenarios.configuration`:

```json
{ "scenario_number": 2, "fixture": "X1-v2", "order_id": "6f1c0e2a-0000-4000-8000-000000000100",
  "events": ["SUPPLIER_LEAD_TIME_CHANGED"] }
```

`simulation.simulation_events`: `event_type`, `event_time`, `parameters` (§2 JSON), `status`.
Each scenario run starts from the X1 baseline (`reset_and_seed`, D10), so scenarios stay independent (fixture §7).

### 5. API (proposed)

```text
POST /simulation/scenarios              { scenario_number }            -> reset to baseline, create scenario
POST /simulation/scenarios/{id}/events  { event_type, parameters }     -> apply, re-evaluate, return summary
GET  /simulation/scenarios/{id}                                        -> events and resulting attempts
```

## Open Items

- **O1 — Baseline plan before the event.** Scenarios say "a plan already exists". Options: the event applies to the
  current state only (the tester runs scenario 1 first), or `POST /simulation/scenarios` also runs the baseline to an
  approved plan automatically (needs scripted supplier answers). Recommended: tester-driven, no scripted answers.
- **O2 — S6 reservation.** Set the balance `reserved` directly (as the fixture does) or create an
  `inventory_reservations` row for "another requirement". Recommended: a reservation row with no order
  (`order_id` NULL), so reserve/release stays consistent; needs a nullable check in C2.
- **O3 — Existing agreements.** In S2/S4 the plan may already hold an agreement with the changed supplier. Does the
  event change that agreement (e.g. a committed delivery moves), or only supplier master data for re-evaluation?
  Fixture §7 evaluates each scenario from the untouched baseline, so recommended: master data only; Purchasing
  re-evaluates on the new negotiation.
- **O4 — Split procurement** (S3 Display 800, S4 Display 500 with Alpha at 300): needs a decision (P3-01) or those
  scenarios end with a clearly identified constrained quantity (scenarios.md allows this for S3).
- **O5 — Combined events** (S7 + S2 "cannot meet" case in the fixture): allow several events in one scenario? Recommended yes, applied in order.
