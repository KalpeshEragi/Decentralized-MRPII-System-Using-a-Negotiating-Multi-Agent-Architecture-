# Planning Agent: High-Level Architecture (System Boundary)

**Status:** APPROVED by the developer (2026-10-17). Nothing new here is implemented.
**Scope:** the Planning Agent only. Other agents appear as contact points.
**Related:** `../architecture/high_level_architecture.md`, `../architecture/negotiation.md`,
`../architecture/pubsub_event_channel.md`, `../architecture/quantity_accounting.md`, `../DECISIONS.md` (HA-*, NG-*,
RD-*), `../sales_agent/` (the Sales side of the contact points), `../research/real_manufacturing_mrpii_research.md`.
Later notes: `2_planning_agent_functions.md`, `3_planning_agent_backend.md`, `4_planning_agent_database.md`.

## 1. Purpose

Planning turns customer demand into a feasible production plan and keeps it feasible when facts change. It
calculates (MPS, multi-level MRP, machine capacity, schedule), decides what is needed from others, asks the owners of
those resources, and tells Sales what can honestly be offered. It proposes and coordinates; owners commit their own
resources.

## 2. Inside the Planning boundary (Planning owns this)

1. Answering Sales' feasibility requests with options (capable-to-promise).
2. MPS: finished-goods netting and planned production per order.
3. Multi-level BOM explosion and MRP netting with lot sizing and lead-time offset (RD-1, `quantity_accounting.md` §6).
4. Machine capacity: work centers, calendars, machine-hours per day (RD-2).
5. Schedule: which production step runs on which day.
6. Production orders and their states: PLANNED → FIRM → RELEASED → STARTED → COMPLETED / CANCELLED (RD-3, RD-4).
7. Procurement requests: Planning starts procurement with Purchasing (HA-3), including safety-stock refills (RD-6).
8. Pegging: which supply covers which demand, rebuilt per item when replanned (RD-5).
9. Replanning: net change on affected items, with time fence (RD-4) and dampener (RD-8).
10. The commit decision for a customer order (execution policy, NG-4) and the plan events.

## 3. Outside the boundary (not Planning's job)

| Item | Owner |
| --- | --- |
| Customer conversation, options shown, the customer's "yes" | Sales |
| Stock, reservations, holds on stock, safety-stock release | Inventory |
| Supplier choice, supplier terms, purchase commitments | Purchasing |
| Receiving capacity, storage space, material issue, finished-goods storage, shipment | Warehouse |
| Worker hours, skills, shifts, overtime limits | HR |
| BOM, items, routings (shared reference data) | Read-only for all; set through the simulator's configuration |

Planning never writes another agent's records. It reads them through their read functions and asks for changes by
negotiation.

## 4. Contact points

| Contact point | Direction | Kind |
| --- | --- | --- |
| Feasibility request | Sales → Planning | Door (Sales decision 1.1) |
| Planning result (options / nothing feasible / working / needs staff) | Planning → Sales | Door (Sales door 3) |
| Customer confirmed option X | Sales → Planning | Event `OrderConfirmed` (the Sales "confirmation notice") |
| Order change / cancel | Sales → Planning | Events `OrderChangeRequested`, `OrderCancelled` |
| Resource negotiations | Planning ↔ Inventory, Purchasing, Warehouse, HR | Private negotiation (A2A, NG-1); Planning is usually the starter |
| Read functions of other agents | Planning → owners | ATP by date (Inventory), supplier options and lead times (Purchasing), free space / receiving (Warehouse), free worker-hours per skill (HR) |
| Facts from others | Owners → Planning | Subscribed events (§7) |
| Plan facts | Planning → others | Published events (§7) |
| Shop-floor adapter | Simulator → Planning | Input: started, quantity completed, machine down (RD-3) |
| AI model | Planning ↔ shared model | Ranks valid alternatives and writes rationale only (PL-4) |
| Storage | Planning ↔ `planning` schema | Planning-owned data only |

## 5. Options Planning returns to Sales

Planning computes them; Sales never does. Kinds follow the Sales contract.

| Kind | Meaning |
| --- | --- |
| REQUESTED | Full quantity by the requested date |
| LATER_DATE | Full quantity, earliest feasible date |
| LESS_QUANTITY | The quantity feasible by the requested date |
| PART_NOW_REST_LATER | Placeholder, later (Sales decision) |
| Status NOTHING_FEASIBLE | No option; Sales says so honestly |
| Status WORKING / NEEDS_STAFF | Still negotiating / a person must look |

**Holds (PL-1):** only the **best option** gets resources held for its validity (24 h, NG-2). "Best" = the first
feasible in the order REQUESTED → LATER_DATE → LESS_QUANTITY. Other options are computed from read functions only and
are **subject to re-check** when chosen.

## 6. How a request becomes a committed plan

1. **Request arrives.** Planning plans this request alone against the current committed and held state
   (capable-to-promise, PL-2): MPS → MRP level by level → capacity per day → candidate options.
2. **Best option secured.** Planning negotiates in parallel with the owners it needs (stock, supply, space, worker
   hours). Agreements place holds. If a negotiation fails, the options are recomputed and the next one becomes best
   (bounded retries, PL-O4).
3. **Answer to Sales** with the options (held one marked), or NOTHING_FEASIBLE / NEEDS_STAFF.
4. **Customer confirms** (`OrderConfirmed`). Held option → execution policy check → `COMMIT` to every linked session →
   owners commit → `PlanCommitted`; production orders become FIRM. Unheld option → negotiate now, then commit.
   Failure → `PlanCommitFailed` (Sales informs honestly).
5. **No confirmation within 24 h** → owners' holds expire; Planning drops the proposal.
6. **Execution.** FIRM orders are RELEASED shortly before their start (`ProductionOrderReleased`, PL-O2); the
   shop-floor adapter reports start and completion (`ProductionStarted`, `ProductionCompleted`).
7. **Facts change.** Pegging finds affected orders; the dampener ignores harmless changes; PLANNED orders are
   replanned freely, FIRM ones only through negotiation, RELEASED/STARTED never automatically; inside the time fence
   nothing changes automatically. Result: `PlanRevised` or `PlanAtRisk`.

Customer acceptance, commitment and production start stay separate states (CLAUDE.md order lifecycle rule).

## 7. Events

| Subscribes to | Publishes |
| --- | --- |
| `OrderConfirmed`, `OrderChangeRequested`, `OrderCancelled` | `PlanCommitted`, `PlanCommitFailed` |
| `ReservationCommitted`, `ReservationReleased`, `StockAvailabilityChanged`, `SafetyStockBreached` | `PlanRevised`, `PlanAtRisk` |
| `ProcurementCommitted`, `SupplierDeliveryDelayed`, `SupplierQuantityReduced` | `ProductionOrderReleased` |
| `ReceivingSlotCommitted`, `MaterialReceived`, `MaterialIssuedToProduction`, `FinishedGoodsStored`, `StorageCapacityChanged`, `ShipmentDispatched` | `ProductionStarted`, `ProductionCompleted` |
| `WorkforceCommitted`, `WorkforceCapacityChanged` | |

## 8. How orders become proposals (PL-3)

- **Made items** (phone, main board): one production order per customer order line, lot-for-lot. Clear pegging and
  status per order.
- **Bought items**: Planning may combine the needs of several orders into one procurement request per item and
  release date, applying the supplier's multiple / minimum. The pegs show which orders share it.

## 9. Rules (write these on the diagram)

1. Planning proposes; owners commit. Planning never writes another agent's data.
2. All quantities, dates and capacity checks are deterministic code.
3. The LLM only ranks alternatives that code has already proven feasible and writes the rationale; code validates;
   if the model fails, a fixed preference order decides (PL-4).
4. Only validated options go to Sales; unheld options are marked "subject to re-check".
5. Released and started production orders are never changed automatically.
6. Hard constraints are never traded for priority.
7. No price or cost.

## 10. Decisions recorded

| ID | Decision |
| --- | --- |
| PL-1 | Only the best option (REQUESTED → LATER_DATE → LESS_QUANTITY, first feasible) gets 24 h holds; the others are read-function estimates marked "subject to re-check". |
| PL-2 | Per-request planning against the current committed and held state (capable-to-promise), plus net-change replanning of affected items via pegging. A full regeneration exists only as a manual check. |
| PL-3 | Made items: one production order per customer order line (lot-for-lot). Bought items: procurement requests may combine several orders per item and release date. |
| PL-4 | The LLM ranks deterministically generated feasible alternatives and writes rationale and negotiation wording; code validates; fixed preference order on failure. |
| Inherited | HA-3 (Planning starts procurement), NG-4 (starter commits after policy), RD-1 to RD-8. |

## 11. Open (for the next notes)

| ID | Question |
| --- | --- |
| PL-O1 | The Sales option contract needs a field saying whether an option is held (`held: true/false`). Contract change to the Sales side first. |
| PL-O2 | Resolved 2026-10-17: 1 day, configurable (PL-7). |
| PL-O3 | Resolved 2026-10-17: 60 days, configurable (PL-7). |
| PL-O4 | Resolved 2026-10-17: 2 re-picks, configurable (PL-7). |
| PL-O5 | Resolved 2026-10-17: fixed ranking PL-6 (`2_planning_agent_functions.md` §6). |

## 12. Diagram checklist

- One big box "Planning Agent" with the 10 inside items (§2).
- Sales with two doors (request in, result out) and the `OrderConfirmed` event arrow.
- Inventory, Purchasing, Warehouse, HR: dashed negotiation arrows (Planning = starter), plus read-function arrows.
- Event channel: subscribed and published events (§7).
- Shop-floor adapter (simulator) → Planning input.
- AI model with a two-way arrow labeled "ranks valid options, writes rationale".
- `planning` schema; shared reference data (BOM, items, routings) read-only.
- Rules note (§9).
