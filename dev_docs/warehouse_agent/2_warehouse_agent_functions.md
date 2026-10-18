# Warehouse Agent: Agent Design (Role, Rules, Methods, Functions)

**Status:** APPROVED by the developer (2026-10-17). Nothing here is implemented.
**Related:** `1_warehouse_agent_high_level_architecture.md` (boundary, WH-1 to WH-5),
`../architecture/quantity_accounting.md` §7 (capacity rule), `../inventory_agent/2_inventory_agent_functions.md`
(same answer shape).

## 1. Role

The factory's warehouse keeper. It promises receiving capacity and storage space only once, receives what actually
arrives, issues complete kits to production, stores finished goods and ships them on the promised day — and reports
each physical fact so Inventory can update quantities.

## 2. Instructions (rules it must follow)

- Every check uses the capacity rule: `free = capacity − committed − held ≥ request`, for **every day** the request
  covers.
- Never promise the same receiving capacity or space twice.
- Post physical facts with actual quantities, never planned ones.
- Never change item quantities (Inventory does, from Warehouse's events).
- Issue only complete kits (WF-1); receive at most the committed quantity (WF-2).
- Start a negotiation only when its own commitment breaks and the fix needs another owner (date change with
  Purchasing).
- No price or cost.

## 3. Methods (all deterministic, WH-5)

| # | Method |
| --- | --- |
| 1 | Answer a receiving-slot / space request: OFFER, COUNTER_OFFER or REJECT |
| 2 | Place, commit, release and expire holds |
| 3 | Receive due deliveries (actual quantity, WF-2) |
| 4 | Issue complete kits for production orders starting today (WF-1) |
| 5 | Store finished goods after production |
| 6 | Ship orders due today within the shipping capacity |
| 7 | Apply capacity changes and find commitments that no longer fit |
| 8 | Ask Purchasing for a new delivery date when a supplier commitment no longer fits |
| 9 | Reconcile space balances with the ledger |

The AI only turns code-computed terms and reason codes into short negotiation wording.

## 4. Functions

### 4.1 Calculation (pure)

| Function | Input | Output |
| --- | --- | --- |
| `space_needed` | Item, quantity | `quantity × space_per_unit` in the item's zone |
| `fits` | Request (zone, space, receiving units, arrival day, until day), balances | Yes/no per day |
| `counter_terms` | Request, balances, horizon | Full quantity on the earliest day that fits (receiving day + whole space interval) within the shared horizon (60 days, PL-7); else the most that fits on the requested day |
| `complete_kits` | Production order quantity, BOM quantities per unit, quantity available per component for this order | Number of complete units that can be issued |
| `shipping_list` | Orders due today, stored and reserved finished goods, shipping capacity | Orders (and quantities) to ship today |
| `no_longer_fitting` | Commitments, new capacity | Commitments to flag, in date order (then commit time) |

### 4.2 Read module (IB-2)

| Function | Returns |
| --- | --- |
| `free_receiving(from, to)` | Free receiving units per day |
| `free_space(zone, from, to)` | Free space units per day |
| `commitments_for(ref)` | Receiving / space commitments of a delivery or an order |

### 4.3 Reads it uses

Inventory: `reservations_for_order`, `stock_position` (for kits and shipping). Planning: `get_order_plan`,
`get_production_orders` (dates). `core.items`, `core.bom_items` (space per unit, quantities per unit).

### 4.4 Actions (one transaction each: ledger + balance + outbox event)

| Action | Effect |
| --- | --- |
| `answer_request` | OFFER / COUNTER_OFFER / REJECT |
| `place_hold` / `commit_hold` / `release` / `expire_holds` | Space and receiving balances; `ReceivingSlotCommitted` on commit of a delivery slot |
| `receive_delivery` | Receiving used; material space occupied from today; `MaterialReceived` (actual quantity) |
| `issue_kits` | Material space freed; `MaterialIssuedToProduction` (issued and missing per component) |
| `store_finished_goods` | Finished-goods space occupied; `FinishedGoodsStored` |
| `ship` | Finished-goods space freed; shipping used; `ShipmentDispatched` |
| `apply_capacity_change` | Capacity rows changed; `StorageCapacityChanged`; flags; date-change negotiation with Purchasing |
| `reconcile` | Compare balances with ledger sums; report only |

## 5. Decision rules

### 5.1 Answering a request

1. Fits on the requested day and every day of the space interval → OFFER.
2. Else the earliest day (within the horizon) where the full quantity fits → COUNTER_OFFER with that day.
3. Else the largest quantity that fits on the requested day → COUNTER_OFFER with that quantity.
4. Else → REJECT, reason `NO_SPACE` or `NO_RECEIVING_CAPACITY`.

### 5.2 Complete kits (WF-1)

For a production order starting today, for each component: `available_c` = what is reserved for this order and
physically on hand (Inventory read). Kits = `min over components of floor(available_c ÷ quantity_per_c)`, at most the
order quantity. Issue exactly kits × quantity_per of each component. `MaterialIssuedToProduction` reports, per
component, the issued and the missing quantity. Planning decides whether to start the smaller quantity or wait.

Example: 450 main boards need 450 PCBs and 900 chips. On hand for the order: 450 PCBs, 800 chips → kits =
`min(450, 400) = 400` → issue 400 PCBs and 800 chips. Reported: 50 kits missing, because 100 chips are missing; the
other 50 PCBs stay in stock, still reserved for this order.

### 5.3 Receiving (WF-2)

- Actual ≤ committed → receive the actual quantity; free the unused receiving units and space.
- Actual > committed → receive the committed quantity only; refuse the excess and report it in `MaterialReceived`
  (`refused_quantity`) so Purchasing can act.
- Nothing arrives on the committed day → nothing is posted; the receiving slot stays until Purchasing reports a delay
  (`SupplierDeliveryDelayed`) or the day ends (then it is released and reported).

### 5.4 Shipping (WH-4)

Orders due today whose finished goods are stored and reserved, in order of committed delivery date, then commit time,
up to the daily shipping capacity. Orders that do not fit move to the next day and are reported (Planning publishes
`PlanAtRisk` if the customer date is missed).

### 5.5 Capacity change

Commitments that no longer fit are walked in date order (then commit time). Supplier deliveries: Warehouse starts a
date-change negotiation with Purchasing (Warehouse is the problem-holder, HA-5). Finished goods: reported to Planning
through `StorageCapacityChanged`.

## 6. The AI step (wording only)

Same as Inventory: input = message type, code-computed terms, reason code; output = one or two short sentences;
every number and date must match the terms, else retry once, then a fixed template.

## 7. Statuses

| Record | Statuses |
| --- | --- |
| Hold (receiving / space) | ACTIVE → COMMITTED; side: EXPIRED, ABORTED |
| Commitment | ACTIVE → IN_USE (goods arrived / stored) → FREED (issued / shipped); side: RELEASED, FLAGGED (no longer fits) |

## 8. Settings (configurable, defaults with the simulator configuration, WH-O4)

| Setting | Meaning |
| --- | --- |
| `receiving_units_per_day` | Receiving capacity |
| `shipping_units_per_day` | Shipping capacity |
| `zone_size_materials`, `zone_size_finished_goods` | Space units per zone |
| Hold validity | 24 h (NG-2) |
| Counter-offer horizon | 60 days (PL-7) |

## 9. Boundaries (must not do)

- Change item quantities, reservations or holds on stock.
- Choose suppliers or change delivery dates by itself.
- Issue partial kits or receive more than committed.
- Let the AI decide or change any number.

## 10. Decisions recorded

| ID | Decision |
| --- | --- |
| WF-1 | Issue complete kits only: kits = min over components of floor(available ÷ quantity per unit); report issued and missing quantities; Planning decides how to continue. |
| WF-2 | Receive at most the committed quantity: short deliveries posted as they are, excess refused and reported to Purchasing. |

## 11. Safeguards and tests

- Space interval: a delivery that fits on its arrival day but not three days later is countered.
- Two requests for the last receiving units: the second is countered.
- Kit example from §5.2 as an exact test.
- Short and over delivery: posted and refused quantities exact; balances freed correctly.
- Shipping capacity smaller than due orders: the earliest committed are shipped first; the rest are reported.
- Capacity cut: the right commitments are flagged and the date-change negotiation starts.
- Repeated event or message changes nothing (unique `source_id`); reconcile after every test.
