# Quantity Accounting

**Status:** APPROVED by the developer (2026-10-17; updated the same day with RD-1, RD-2, RD-5, RD-6 and
the lead-time / lot-size rules from the research report). Nothing new here is implemented.
**Related:** `negotiation.md` (holds, commitments), `pubsub_event_channel.md` (events that change numbers),
`high_level_architecture.md` (who owns which number), `../research/real_manufacturing_mrpii_research.md` (sources,
full worked example).

## 1. Purpose

Every number in the simulated factory (stock, reservations, incoming supply, storage space, receiving capacity,
worker hours, machine capacity) must change **exactly**, for a known reason, by its owner only, and must never be
promised twice. This doc gives the rules and worked examples so the code and the tests can be checked against them.

## 2. Decisions (2026-10-17)

| ID | Decision |
| --- | --- |
| QA-1 | Every change is an append-only **ledger** row plus an update of the **balance** row, in one transaction. |
| QA-2 | Normal promises never use safety stock. Inventory alone may release part of it for an urgent order, with a recorded reason, and publishes `SafetyStockBreached`. Physical stock never goes below 0. |
| QA-3 | An order change is handled as a **delta**: the existing reservation stays; only the difference is negotiated or released. |
| QA-4 | Incoming supply can be promised **by date** (Available-to-Promise): a promise due on day D may use committed receipts arriving by D. |
| QA-5 | Units (2026-10-17): pieces are whole numbers; machine- and worker-hours are rounded **up** to steps of 0.25 h per step and day (e.g. 9.1 h → 9.25 h); space units are rounded **up** to whole numbers per commitment. Values are stored as exact decimals; rounding happens only in code at these points. |

Related decisions from the research (`../DECISIONS.md`): RD-1 multi-level BOM (§6), RD-2 machine + worker hours
(§7), RD-5 pegging (§5.3), RD-6 configurable safety-stock limits and automatic refill (§5.2).

## 3. Research basis

The rules follow standard MRPII definitions, not invented ones:

| Concept used here | Standard source |
| --- | --- |
| On-hand, allocated (reserved), available, safety stock, scheduled receipts | APICS/ASCM Dictionary |
| Time-phased netting: gross → net requirements, lead-time offset, lot sizing | Ptak & Smith, *Orlicky's Material Requirements Planning* (3rd ed.) |
| Available-to-Promise (ATP) with look-ahead, MPS, capacity checks | Vollmann, Berry, Whybark, Jacobs, *Manufacturing Planning and Control for Supply Chain Management* |
| Perpetual inventory: every movement recorded as a transaction; balance must equal the sum of transactions | Standard inventory-control practice (same books) |

(Cited from the standard texts at book level.) The research report checks these rules against official ERP
documentation (SAP, Microsoft Dynamics 365 / Business Central, Odoo, Oracle) with direct links.

## 4. Stock: the numbers per item (owner: Inventory)

| Number | Meaning | Changed by |
| --- | --- | --- |
| `on_hand` | Physically in the factory | Receipt (+), issue to production or shipment (−), count adjustment (±) |
| `reserved` | Committed to orders, not yet issued | Commit (+), release / cancellation (−), issue (−) |
| `held` | Tentative holds from negotiations, expiring | Agreement (+), commit (− held, + reserved), expiry / abort (−) |
| `safety_stock` | Protective floor set by Inventory | Inventory policy only |
| `incoming` | Committed supplier receipts, each with a date | `ProcurementCommitted` (+), receipt (−), delay (date moves), quantity reduced (−) |

Each reservation and hold also has a **due date** (when production needs it).

### 4.1 Available now (simple case, matches the existing code)

```
available_now = max(0, on_hand − reserved − held − safety_stock)
```

### 4.2 Available to promise by date D (QA-4)

For each date t:
- `S(t)` = on_hand + incoming arriving on or before t (cumulative supply)
- `C(t)` = reserved + held that are due on or before t (cumulative promises)

```
ATP(D) = max(0, min over all t ≥ D of ( S(t) − C(t) ) − safety_stock)
```

A new promise of q due on D is allowed only if `q ≤ ATP(D)`. The "min over later dates" stops a new promise from
taking stock that a later promise needs. With no incoming receipts, `ATP(today)` equals `available_now` above, so the
two rules agree.

## 5. Worked examples (stock)

### 5.1 The developer's example: 5000 on hand, three orders, one grows

Item X: on_hand 5000, safety_stock 0, nothing incoming. Three orders arrive at the same time, each 500, all due on
the same day. Inventory handles them one at a time on the item's locked row (order picked by NG-3; with enough stock
the order does not change the result).

| Step | Ledger row | on_hand | held | reserved | available |
| --- | --- | --- | --- | --- | --- |
| Start | — | 5000 | 0 | 0 | 5000 |
| O-1 agreed | HOLD +500 (O-1) | 5000 | 500 | 0 | 4500 |
| O-2 agreed | HOLD +500 (O-2) | 5000 | 1000 | 0 | 4000 |
| O-3 agreed | HOLD +500 (O-3) | 5000 | 1500 | 0 | 3500 |
| All three customers confirm, Planning commits | HOLD −500 / RESERVE +500 (×3) | 5000 | 0 | 1500 | 3500 |
| O-2 changes 500 → 1000: delta +500 checked (500 ≤ 3500) and committed | RESERVE +500 (O-2, change) | 5000 | 0 | 2000 | **3000** |
| O-2 then reduces 1000 → 600: release 400 | RELEASE −400 (O-2, change) | 5000 | 0 | 1600 | 3400 |
| O-3 cancelled | RELEASE −500 (O-3, cancel) | 5000 | 0 | 1100 | 3900 |
| O-1 production starts, 500 issued | ISSUE −500 on_hand, −500 reserved | 4500 | 0 | 600 | 3900 |

Note that issuing does not change `available`: the stock was already promised.

### 5.2 Not enough stock (scarce case)

on_hand 1200, safety_stock 200 → available 1000. Three requests of 500 each, slack: O-3 = 2 days, O-1 = 5, O-2 = 9.

| Order (queue rule NG-3) | Result | available after |
| --- | --- | --- |
| O-3 (smallest slack) | Hold 500 | 500 |
| O-1 | Hold 500 | 0 |
| O-2 | Counter-offer: 0 now; Inventory reports the shortage; Planning decides (procurement, later date) | 0 |

If O-2's slack were within the urgent limit, Inventory **may** offer part of its safety stock (QA-2, RD-6). Both
limits are **configurable factory settings**, enforced by Inventory with whatever values are set:

| Setting | Default | Meaning |
| --- | --- | --- |
| `safety_stock_release_share` | 50 % | At most this share of an item's safety stock may be released |
| `safety_stock_max_slack_days` | 2 days | Only for requests whose deadline slack is at most this |

With the defaults: O-2 has slack 9 days → no release. If O-2's slack were 2 days, Inventory could offer up to
`50 % × 200 = 100`. It records `SAFETY_STOCK_USE` and publishes `SafetyStockBreached`; **Planning then plans a refill
at once** (it starts procurement, HA-3).

### 5.3 Promising incoming stock by date (QA-4)

on_hand 1000, reserved 800 (due day 5), incoming 2000 arriving day 10, safety_stock 0.

| t | S(t) | C(t) | S − C |
| --- | --- | --- | --- |
| day 1–9 | 1000 | 800 (from day 5) | 200 |
| day 10+ | 3000 | 800 | 2200 |

- New promise due day 3: ATP = min(200, 2200) = **200**.
- New promise due day 12: ATP = **2200**.

**Supplier delay** to day 15 (`SupplierDeliveryDelayed`): S(10..14) drops to 1000. If a promise of 1500 was due on
day 12, S(12) − C(12) = 1000 − 2300 = −1300 < 0, so that promise is now uncovered. Inventory publishes
`StockAvailabilityChanged`. Inventory finds the uncovered promises **for this item** by walking them in due-date
order (then commit time).

Planning then finds the **affected customer orders** by following its pegs (RD-5) up the BOM levels: for example
delayed chips → main-board production order → phone production order → customer order SO-1. Only the orders on that
path are replanned (PlanAtRisk / negotiations).

### 5.4 Receipts

| Event | on_hand | incoming | Note |
| --- | --- | --- | --- |
| `MaterialReceived` 2000 of a 2000 receipt | +2000 | −2000 | ATP after the receipt date does not change |
| `MaterialReceived` 1800 of 2000 | +1800 | −1800 | The 200 stays incoming only if Purchasing keeps it; otherwise `SupplierQuantityReduced` removes it |
| Received 2 days early | +q earlier | −q | ATP for early dates rises |

## 6. Planning numbers: MRP netting (owner: Planning)

### 6.1 Rules (multi-level, RD-1)

Items are planned **level by level from the top** (low-level code 0 = finished product, then 1, 2, ...). An item
used at several levels is planned at its deepest level, so all its demand is known first. For each item:

```
gross(t)            = customer demand (level 0) or Σ parent planned quantity × quantity_per, at the parent's start date
                      + existing reservations and holds at their due dates
PAB(t)              = PAB(t−1) + scheduled_receipts(t) + planned_receipts(t) − gross(t)      PAB(0) = on_hand
net(t)              = safety_stock − PAB_before_planned_receipt(t)      when that PAB is below safety stock, else 0
planned_receipt(t)  = lot size applied to net(t):
                        lot-for-lot  → net
                        multiple m   → ceil(net / m) × m
                        minimum q    → max(net, q)
release_date        = need_date − lead_time
                        bought item: the supplier's lead time
                        made item:   the production lead time after the capacity check (§7), which can be longer
```

The planned quantity **after** lot sizing creates the next level's gross requirement. Extra quantity from rounding
becomes free stock on receipt. Planned orders are proposals; owners commit them (NG-4, RD-4).

### 6.2 Example (from the research report §4.2)

Customer order: 500 phones due day 15; today is day 1. BOM: phone → main board (made) + battery + case; main board →
1 PCB + 2 chips.

| Level | Item | Gross (need day) | Stock and receipts | Safety stock | Net | Lot rule | Planned | Release |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Phone | 500 (day 15) | 50 finished | 0 | 450 | lot-for-lot | 450 | day 13 (lead time 2) |
| 1 | Main board | 450 (day 13) | 20 | 0 | 430 | lot-for-lot | 430 | day 11 (capacity: 2 days, §7.3) |
| 1 | Battery | 450 (day 13) + 100 reserved (day 4) | 300 + 200 arriving day 6 | 50 | 100 | multiple 100 | 100 | day 8 (lead time 5) |
| 1 | Case | 450 (day 13) | 1000 | 100 | 0 | — | — | — |
| 2 | PCB | 430 (day 11) | 100 | 0 | 330 | lot-for-lot | 330 | day 7 (lead time 4) |
| 2 | Chip | 860 (day 11) | 300 | 100 | 660 | multiple 250 | **750** | day 4 (lead time 7) |

Battery check: `300 − 100 + 200 − 450 = −50`; keeping 50 needs 100 → PAB after = 50. Chip: `300 − 860 = −560`; keeping
100 needs 660 → rounded to 750 → PAB after = 190 (90 above safety stock becomes free stock).

Finished goods are netted first (MPS): the 50 finished phones are reserved for this order, so only 450 are produced.

## 7. Capacity-type numbers (same pattern for every owner)

Every capacity-type resource uses one rule per period (a day, per skill / zone / work center):

```
free(period) = capacity(period) − committed(period) − held(period)
a request is allowed only if request(period) ≤ free(period) for EVERY period it covers
```

| Resource | Owner | Unit | capacity(period) | Notes |
| --- | --- | --- | --- | --- |
| Storage space | Warehouse | space units per zone | zone size | Space is occupied from arrival until the planned issue: check every day in that interval. Pieces → space units via the item's `space_per_unit`. |
| Receiving capacity | Warehouse | units (or slots) per day | daily receiving limit | One delivery uses its arrival day. |
| Workforce | HR | worker-hours per skill per day | Σ shift hours − absences | A routing step needs `(setup + qty × run time) × crew size` hours of its skill. A worker absence lowers capacity; commitments above the new capacity become uncovered. |
| Machine capacity | Planning | machine-hours per work center per day | calendar hours × efficiency | A routing step needs `setup + qty × run time` hours on its work center (RD-2). |
| Supplier capacity | Purchasing | units per period | supplier limit | Defined with the Purchasing doc. |

### 7.1 Example: storage space

Zone A: 1000 space units. Battery uses 0.5 space unit per piece. Already occupied 600, held 100.
A delivery of 800 batteries = 400 units, staying days 10–14. free = 1000 − 600 − 100 = 300 < 400 → Warehouse cannot
accept it as is. It counter-offers (e.g. 600 pieces = 300 units, or a later date when space frees up).

### 7.2 Example: worker absence

Assembly skill, day 8: 3 workers × 8 h = 24 h; committed 20 h. One worker absent → capacity 16 h; committed 20 h
> 16 h, so 4 h are uncovered. HR publishes `WorkforceCapacityChanged`. Commitments are walked in start-date order
(then commit time); the ones beyond 16 h are flagged; Planning replans them (shift, overtime limits from HR, other day).

### 7.3 Example: one routing step needs machine hours AND worker hours (RD-2)

A step fits a day only if **both** fit. A step may be spread over several days; every day is checked.

**Main board, 430 pieces** on work center SMT (8 machine-hours/day, setup 0.5 h, run 0.02 h/piece, crew 1, skill
SMT): need `0.5 + 430 × 0.02 = 9.1 h` of machine time and 9.1 worker-hours. One day has only 8 machine-hours → the
step is spread over days 11–12 (for example 4.55 h + 4.55 h). That is why the main board is released on day 11, not 12.

**Phone, 450 pieces** on work center ASM (2 stations × 8 h = 16 machine-hours/day, setup 1 h, run 0.05 h/piece,
crew 1, skill ASSEMBLY; HR has 2 assembly workers × 8 h = 16 worker-hours/day): need 23.5 h over days 13–14.

| Case | Machine-hours (days 13 + 14) | Worker-hours (days 13 + 14) | Fits 23.5 h? |
| --- | --- | --- | --- |
| Normal | 16 + 16 = 32 | 16 + 16 = 32 | yes |
| One worker absent on day 13 | 16 + 16 = 32 | 8 + 16 = 24 | yes, just (8 h + 15.5 h) |
| One worker absent both days | 32 | 8 + 8 = 16 | **no** → overtime or another assembly worker from HR, or a later date |

The usable hours per day are the **smaller** of the machine-hours and the worker-hours.

With QA-5 rounding the main-board step needs 9.25 h instead of 9.1 h; the result is the same (more than 8 h, spread over two days). 23.5 h is already a multiple of 0.25 h.

## 8. Ledger (QA-1)

Each owner keeps its own ledger in its own schema (for example `inventory.stock_ledger`, `warehouse.space_ledger`,
`hr.hours_ledger`, `planning.capacity_ledger`). Common columns:

| Column | Meaning |
| --- | --- |
| `resource_ref`, `period` | Item / zone / skill, and the day if time-phased |
| `bucket` | Which number changes: `ON_HAND`, `RESERVED`, `HELD`, `INCOMING`, `COMMITTED`, `CAPACITY` |
| `delta` | Signed change (+500, −400) |
| `reason` | `RECEIPT`, `ISSUE`, `HOLD`, `HOLD_EXPIRED`, `COMMIT`, `RELEASE`, `CANCEL`, `CHANGE`, `SAFETY_STOCK_USE`, `ADJUSTMENT`, `ABSENCE`, ... |
| `order_id`, `case_id` | What it was for |
| `source_id` | Event id or negotiation message id that caused it — **unique** with the line number, so a repeat is ignored |
| `sim_time`, `created_at` | Simulated and real time |

The balance row is updated in the same transaction. A reconcile check recomputes every balance from the ledger.

## 9. Concurrency rules

- An owner changes a resource only after locking its balance row (`FOR UPDATE`). Two requests for the same item are
  handled one after the other; requests for different items run in parallel.
- A request that touches several rows locks them in a fixed order (by id) to avoid deadlocks.
- The check (`q ≤ ATP` or `q ≤ free`) and the change happen in the same transaction as the ledger row and the event.
- Given the same starting state and the same order of arrival, the result is always the same (repeatable tests).

## 10. Invariants (checked by tests and the reconcile check)

1. `on_hand`, `reserved`, `held`, `incoming`, `committed` are never negative.
2. For every item and date t: `S(t) − C(t) ≥ 0` (nothing over-promised); and `≥ safety_stock` except for recorded
   `SAFETY_STOCK_USE` rows.
3. For every capacity resource and period: `committed + held ≤ capacity`, except after a capacity cut, where the
   excess is flagged at once.
4. Every balance equals the sum of its ledger rows.
5. A repeated event or message (same `source_id`) changes nothing.
6. An issue never exceeds what is reserved for that order; an order's reservations never exceed its requirement.
7. An expired hold is gone from `held` and its quantity is available again.

## 11. Open

| ID | Question |
| --- | --- |
| QA-O2 | Resolved 2026-10-17 (QA-5): pieces whole numbers; hours in steps of 0.25 h; space units whole numbers; rounded up where computed. |
| QA-O3 | Scrap, quality rejects and count corrections: out of scope unless a scenario needs them. |
| QA-O4 | Resolved 2026-10-17: finished-goods space is negotiated between Planning and Warehouse and held until shipment (WH-1 to WH-4, WF-2, WD-1). |