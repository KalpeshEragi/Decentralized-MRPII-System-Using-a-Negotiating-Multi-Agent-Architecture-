# Warehouse Agent: High-Level Architecture (System Boundary)

**Status:** APPROVED by the developer (2026-10-17). Nothing here is implemented; there is no Warehouse code
(the old stub was removed, P0-01).
**Scope:** the Warehouse Agent only. Other agents appear as contact points.
**Related:** `../architecture/quantity_accounting.md` §7 (capacity rule), `../architecture/negotiation.md`,
`../architecture/pubsub_event_channel.md`, `../inventory_agent/` (IN-1: quantity vs space), `../DECISIONS.md`.
Later notes: `2_warehouse_agent_functions.md`, `3_warehouse_agent_backend.md`, `4_warehouse_agent_database.md`.

## 1. Purpose

Warehouse owns the physical side of the factory: how much can be **received** each day, how much **space** is free in
each zone, and the physical moves — receiving supplier deliveries, issuing material to production, storing finished
goods and shipping them. It promises space and receiving capacity only once, and reports physical facts so Inventory
can update quantities.

Research note: real ERPs mostly check space at put-away time; treating space as a planning constraint is our
simplification for the simulation (`../research/real_manufacturing_mrpii_research.md` §1 point 9).

## 2. Inside the Warehouse boundary (Warehouse owns this)

1. Receiving capacity per day (units, a configured number, WH-3).
2. Storage space per zone and day: two zones, MATERIALS and FINISHED_GOODS, in space units (WH-2).
3. Holds and commitments of receiving slots and space (owner role in negotiations).
4. Receiving: posting supplier deliveries that arrive (actual quantity) → `MaterialReceived`.
5. Issuing material to production → `MaterialIssuedToProduction`.
6. Storing finished goods after production → `FinishedGoodsStored` (IN-2).
7. Shipping to the customer on the committed date → `ShipmentDispatched` (WH-4).
8. The space ledger and balance (QA-1).
9. Capacity changes (e.g. a zone partly unusable) → `StorageCapacityChanged`, and finding which commitments no longer
   fit.

## 3. Outside the boundary

| Item | Owner |
| --- | --- |
| Item quantities (on-hand, reserved, incoming) | Inventory (IN-1) |
| Supplier choice and delivery dates | Purchasing |
| Production plan, production orders, finished-goods dates | Planning |
| Worker hours | HR (not used by Warehouse, WH-3) |
| Customer communication | Sales |

## 4. Contact points

| Contact point | Direction | Kind |
| --- | --- | --- |
| Receiving slot + material space for a delivery | Purchasing → Warehouse, **before** Purchasing commits a supplier date (WH-1) | Private negotiation (A2A); Warehouse is the owner |
| Finished-goods space from completion to shipment | Planning → Warehouse | Private negotiation; Warehouse is the owner |
| Delivery date change when space or receiving no longer fits | Warehouse → Purchasing | Private negotiation; Warehouse is the starter (problem-holder, HA-5) |
| `free_receiving`, `free_space` | Others → Warehouse | Read module (IB-2) |
| Arriving deliveries (actual quantity) | Simulated supplier deliveries → Warehouse input (WH-O2) | Input door |
| Subscribed / published events | §6 | Event channel |
| AI model | Warehouse ↔ shared model | Negotiation wording only |
| Storage | Warehouse ↔ `warehouse` schema | Warehouse-owned data only |

## 5. How space and receiving are promised

- **Receiving:** a delivery uses receiving capacity on its arrival day: `free = capacity − committed − held ≥ quantity`.
- **Space:** a delivery or finished-goods batch occupies `quantity × space_per_unit` in its zone **every day from
  arrival until the planned issue or shipment date**; every day in that interval must fit.
- **Answer:** fits → OFFER; else COUNTER_OFFER with the facts (another arrival day, or the quantity that fits) — same
  rule shape as Inventory (IF-1); else REJECT.
- **Hold → commit:** hold on agreement (24 h); `COMMIT` → re-check → commitment → `ReceivingSlotCommitted` (receiving
  and material space) or a space commitment for finished goods.
- **Capacity cut:** commitments that no longer fit are flagged; for supplier deliveries Warehouse negotiates a date
  change with Purchasing; for finished goods it reports to Planning (`StorageCapacityChanged`).

## 6. Events

| Subscribes to | Reaction |
| --- | --- |
| `ProcurementCommitted` | Link the delivery to its receiving commitment |
| `SupplierDeliveryDelayed`, `SupplierQuantityReduced` | Move or shrink the receiving and space commitments; flag if the new day does not fit |
| `ProductionOrderReleased` | Prepare the material issue for the start day |
| `ProductionCompleted` | Store the finished goods (space was committed with Planning) → `FinishedGoodsStored` |
| `PlanRevised`, `PlanCommitFailed`, `OrderCancelled` | Release space no longer needed (through the negotiation starter's ABORT, or as reported) |
| `SimulatedDayStarted` | Receive due deliveries; issue material for orders starting today; ship orders due today; expire holds |

| Publishes | When |
| --- | --- |
| `ReceivingSlotCommitted` | A receiving slot + material space is committed |
| `MaterialReceived` | A delivery is posted (actual quantity) |
| `MaterialIssuedToProduction` | Material is issued for a production order |
| `FinishedGoodsStored` | Finished goods are put away |
| `ShipmentDispatched` | An order is shipped |
| `StorageCapacityChanged` | A zone's or the receiving capacity changes |

`WorkforceCommitted` and `WorkforceCapacityChanged` are **removed** from Warehouse's subscriptions (WH-3, WH-O1).

## 7. Shipping (WH-4)

On `SimulatedDayStarted`, Warehouse ships every order whose committed delivery date is today and whose finished goods
are stored and reserved for it (read from Inventory's and Planning's read modules), within the daily shipping capacity
(configured). Missing goods → no shipment; Planning already reports `PlanAtRisk`. Early shipment is not done
automatically.

## 8. Rules (write these on the diagram)

1. Warehouse owns space and physical moves; it never changes item quantities (Inventory does, from its events).
2. Never promise the same receiving capacity or space twice; every day of an interval must fit.
3. A supplier date is committed only after its receiving slot is held (WH-1).
4. Physical facts are posted as they happen (actual quantities), never as planned.
5. The AI writes wording only; all checks are code.
6. No price or cost.

## 9. Decisions recorded

| ID | Decision |
| --- | --- |
| WH-1 | Purchasing negotiates a receiving slot + material space with Warehouse before committing a supplier date (detail in the Purchasing doc). |
| WH-2 | Two storage zones by item type: MATERIALS (raw materials, sub-assemblies) and FINISHED_GOODS; space per piece from `core.items.space_per_unit`. |
| WH-3 | Receiving and shipping capacity per day are configured numbers; Warehouse does not use HR workers. |
| WH-4 | Warehouse ships on the committed delivery date when the order's finished goods are stored and reserved; publishes `ShipmentDispatched`. |
| WH-5 | All Warehouse decisions are deterministic; the AI writes negotiation wording only (same as IN-4). |

## 10. Open (for the next notes)

| ID | Question |
| --- | --- |
| WH-O1 | Done 2026-10-17: Warehouse removed from the workforce events' subscribers and from HR needs in `high_level_architecture.md` §2. |
| WH-O2 | How actual deliveries arrive: a simulated delivery input to Warehouse (driven by the supplier simulation; may deliver short). Settle with the Purchasing doc and `demo.md`. |
| WH-O3 | Settled by WF-1 (complete kits only) in note 2. |
| WH-O4 | Resolved 2026-10-17: Factory A defaults in `demo.md` §4.1. |

## 11. Diagram checklist

- One box "Warehouse Agent" with the 9 inside items (§2) and two zones drawn inside.
- Purchasing → Warehouse: receiving-slot negotiation (before supplier commitment); Warehouse → Purchasing: date change.
- Planning → Warehouse: finished-goods space negotiation.
- Simulated deliveries → Warehouse input.
- Warehouse → Inventory: `MaterialReceived`, `MaterialIssuedToProduction`, `FinishedGoodsStored`, `ShipmentDispatched`.
- Simulator clock → Warehouse: `SimulatedDayStarted` (receive, issue, ship, expire holds).
- Read modules: `free_receiving`, `free_space`.
- AI model: "wording only". `warehouse` schema with ledger + balance.
- Rules note (§8).
