# How Real Manufacturing Software Works — Research for the Six-Agent MRPII Prototype

**Status:** Research report for developer review (2026-10-17). It changes no decision, doc or code. Every
recommendation here is a **proposal**; the developer decides one at a time.

## How to read this report

Every important statement carries a label that says where it comes from:

| Label | Meaning |
| --- | --- |
| **[D]** | Official product documentation, read in full for this report (link in §15) |
| **[D-s]** | Official product documentation, seen only as a search-result excerpt (page not read in full) — weaker evidence |
| **[L]** | Peer-reviewed research or pattern literature (bibliographic details checked; full text not read unless stated) |
| **[B]** | Standard textbook knowledge, cited at book level, **not re-checked online** for this report |
| **[R]** | Our recommendation for this project (not industry fact) |
| **[P]** | An existing project decision or the current code |

Citations look like `[S8]` and point to the numbered source list in §15.

Important limits: SAP's main help portal pages for S/4HANA MRP were mostly not reachable through search, so SAP
statements rely on SAP's official Learning site and one older SAP Help page. Oracle's reservation page could only be
seen as an excerpt. No ERP is claimed to work exactly like another; differences are listed in §8.

---

## 1. Key findings (summary)

1. **Real MRP systems propose; they do not commit.** The planning run creates *planned orders* and *purchase
   requisitions*, which are suggestions that can be changed or deleted; people or execution functions convert them
   into binding production orders and purchase orders [D] [S1] [S8] [S25]. → In our design, Planning proposes and
   the resource owners commit. This matches industry practice.
2. **Planning works item by item, top of the BOM first** (low-level code), and each level's planned orders create
   the next level's demand [D] [S8]. Our current code has only a **single-level BOM** [P].
3. **The core calculation is the same everywhere:** a time-phased record per item where demand (gross requirements)
   is compared with on-hand stock plus scheduled receipts. When projected stock falls below safety stock, a net
   requirement appears; lot-sizing rules round it; the lead time moves it earlier into a release date [D] [S1] [S10]
   [S20] [B].
4. **Classic MRP assumes infinite capacity.** Capacity is checked afterwards (capacity requirements planning,
   leveling) or by a separate finite scheduler [D] [S6] [S8] [S16] [B]. Machines and workers are modeled as
   **resources with calendars (hours per day), efficiency and capabilities (skills)** [D] [S16].
5. **Reservations are owned by inventory/execution, not by planning.** Oracle's planning does not create
   reservations [D-s] [S23]. Dynamics 365 reserves physical stock and also *ordered* (incoming) stock [D] [S14].
   Odoo lets each operation reserve at confirmation, manually, or a few days before the scheduled date [D-s] [S21].
6. **Order promising is a separate function from MRP.** Available-to-Promise (ATP) checks a new order against the
   current plan; SAP notes that ATP is first-come-first-served and needs *backorder processing* to redistribute
   later [D-s] [S3]. Oracle adds *capable-to-promise* (CTP), which also plans the supply needed to fill an order
   [D-s] [S24].
7. **Replanning is driven by "action/exception messages"**: new, change quantity, reschedule in/out, cancel
   [D] [S9] [S5]. Supply that has already started (receipt posted, consumption posted) is *not* replanned
   [D] [S9]. A frozen zone / time fence protects the near future [D] [S8] [D-s] [S5].
8. **Safety stock is normally a soft limit:** by default in Dynamics 365, real demand may consume safety stock and
   planning immediately proposes its replenishment; strict protection is an option [D] [S10] [S11]. Business
   Central does the same and flags an "exception" warning [D] [S9]. Our approved rule (QA-2, only Inventory may
   release part of it) is **stricter than the ERP default** — this is our choice, not industry practice.
9. **Warehouse capacity is mainly an execution check** (location stocking limits, volume/weight at put-away; open
   receiving work counts against capacity) [D-s] [S18]. Using storage space as a *planning* constraint, as we plan
   to, is a simplification we choose for the simulation.
10. **Decentralized, negotiating agents are a research approach, not standard ERP.** Agent and holonic manufacturing
    research (contract-net protocol, PROSA) is well established [L] [S26] [S27], but industrial adoption has been
    slow [L] [S28]. Our six-agent architecture is a valid research contribution; it should not be presented as
    "how ERPs work".
11. **Our messaging choices match known patterns:** the outbox pattern (EV-2, NG-1) and saga-style compensation
    instead of cross-agent rollback (negotiation.md §8) are documented microservice patterns [L] [S30] [S31].

The biggest gaps in our project are listed in §11. In short: multi-level BOM, routings and work centers, component
lead-time offsetting and lot sizing, planned vs firm orders with a time fence, explicit pegging (which order uses
which supply), and an owner for production orders.

---

## 2. Glossary (plain language)

| Term | Simple meaning |
| --- | --- |
| **MRPII** | Manufacturing Resource Planning: material planning (MRP) plus capacity, scheduling and execution in one loop |
| **Independent demand** | Demand that comes from outside: customer orders, forecasts |
| **Dependent demand** | Demand calculated from another item's plan: 450 phones need 450 batteries |
| **MPS** (master production schedule) | The plan of how many finished products to make, and when |
| **BOM** (bill of materials) | The recipe: which parts, and how many of each, make one unit of a product. Can have several levels |
| **Low-level code** | The deepest BOM level at which an item appears; items are planned from level 0 downwards |
| **BOM explosion** | Multiplying the planned quantity by the BOM to get component requirements |
| **Gross requirement** | Total quantity needed of an item in a period, before looking at stock |
| **On-hand** | Physically in stock |
| **Allocated / reserved** | On-hand (or incoming) quantity already promised to a specific order |
| **Scheduled receipt** | Supply already ordered and expected: an open purchase order or production order |
| **Projected available balance (PAB)** | Expected stock at the end of each period if the plan is followed |
| **Net requirement** | What is still missing after stock and scheduled receipts (and keeping safety stock) |
| **Safety stock** | Extra stock kept to protect against surprises |
| **Lot sizing** | Rule for the order quantity: lot-for-lot (exactly the need), fixed quantity, minimum, multiples, min/max |
| **Lead time** | How long it takes from ordering/starting to having the item available |
| **Lead-time offset** | Moving the order date earlier by the lead time: release date = need date − lead time |
| **Planned order** | A suggestion created by planning. Can be changed or deleted by the next planning run |
| **Firm planned order** | A planned order a planner has locked so planning no longer changes it |
| **Production order / work order** | A released, binding instruction to make a quantity |
| **Purchase requisition / purchase order (PO)** | Internal request to buy / binding order to a supplier |
| **Routing** | The steps (operations) to make an item, each on a work center with setup and run time |
| **Work center / resource** | A machine, line, worker or group that has capacity in hours per day |
| **Calendar / shift** | When a resource works, giving its available hours |
| **CRP** (capacity requirements planning) | Adds up the hours that planned and released orders need per work center per period |
| **Capacity leveling** | Moving work to periods where the resource is free |
| **Finite / infinite capacity** | Whether scheduling respects the hour limit (finite) or allows overload (infinite) |
| **Pegging / order tracking** | The link showing which supply covers which demand |
| **ATP** (available-to-promise) | How much can still be promised to new customer orders, by date |
| **CTP** (capable-to-promise) | ATP plus planning new supply (production/purchase) to fill an order |
| **Backorder processing (BOP)** | Re-checking existing orders and redistributing available quantities |
| **Action / exception message** | Planning's suggestion to fix an imbalance: new, increase, decrease, reschedule in/out, cancel |
| **Time fence / frozen zone** | A near-term period in which planning must not change orders automatically |
| **Goods receipt / goods issue** | Posting material into stock / out of stock (to production or shipment) |
| **Put-away** | Moving received goods to a storage location |
| **Outbox pattern** | Saving a message in the same database transaction as the business change, then sending it |
| **Saga / compensation** | A multi-step process where a failed step is undone by "reverse" steps, not one big rollback |

---

## 3. The real manufacturing workflow

### 3.1 Sequence and dependencies

```
Customer demand ─┬─> Order promising (ATP / CTP check) ──> Confirmed sales order
Forecasts ───────┘                │
                                  v
                    MPS (finished products, by period)            [needs: demand, FG stock, capacity check]
                                  v
                    Rough-cut capacity check (optional)
                                  v
             MRP per item, level by level (low-level code):
               gross reqs → netting with on-hand + scheduled receipts − safety stock
               → net reqs → lot sizing → lead-time offset → planned orders
                                  v
                    CRP / capacity leveling per work center   ──(overload → reschedule, overtime, replan)
                                  v
        ┌──────────── release (planner / buyer converts proposals) ───────────┐
        v                                                                      v
 Purchase orders → supplier confirmation → goods receipt → put-away    Production orders → material reservation
        └──────────────────────────────> stock <───── goods issue to production ──┘
                                                         v
                                   Operations on work centers (workers + machines)
                                                         v
                                   Finished goods receipt → picking → shipment → delivery
```

Sources: the MRP sequence (net requirements → lot size → scheduling of proposals) [D] [S1]; planning by low-level
code [D] [S8]; planned orders released into work orders / purchase requisitions / transfers [D-s] [S25]; capacity
leveling of infinitely scheduled operations [D-s] [S6]; ATP and backorder processing [D-s] [S3]; textbook loop [B].

### 3.2 What must wait and what can run in parallel

| Must wait for | Because |
| --- | --- |
| MRP for a component waits for the planned orders of its parent | The parent's planned orders create the component's dependent demand [D] [S8] |
| Release date of a purchase waits for the component's need date | Release = need date − lead time [D] [S1] [B] |
| A production order's start waits for its components to be available | Material must be issued before operations start [B] |
| Shipment waits for finished-goods receipt | — |

| Can run in parallel | Why it is safe |
| --- | --- |
| Planning of different items at the same BOM level | No dependency between them (ERPs still run them in one batch) |
| Purchasing different components from different suppliers | Independent supply chains |
| Capacity checks of different work centers | Independent resources |
| Receiving, production and shipping of *different* orders | Only shared resources (stock, space, hours) must be protected |

[R] For our agents: Inventory, Purchasing, Warehouse and HR checks for one order can run in parallel once Planning
has exploded the BOM and computed dates; they meet again when Planning combines the results.

---

## 4. Planning calculations

### 4.1 Inputs and outputs

| Step | Inputs | Output | Key formula |
| --- | --- | --- | --- |
| Order promising | Order qty/date, current plan, stock | Confirmed qty/date | `ATP(D) = min over t ≥ D of (cumulative supply(t) − cumulative promised(t))` [B] |
| MPS | Customer orders (and forecast), finished-goods stock, safety stock | Planned production per period | `net = max(0, demand − available FG)` [P] [B]; Odoo's MPS: `replenishment = safety target − starting stock + demand` [D] [S20] |
| BOM explosion | Planned parent orders, BOM quantities | Component gross requirements by date | `gross(child) = parent planned qty × qty per` |
| MRP netting | Gross reqs, on-hand, reserved, scheduled receipts, safety stock | Net requirement by date | `PAB(t) = PAB(t−1) + SR(t) + planned receipts(t) − gross(t)`; net when `PAB < safety stock` [B] [S10] |
| Lot sizing | Net requirement, rules | Planned order quantity | L4L; fixed; min/max (e.g. min 10, max 15, on-hand 4 → order 11 [D] [S10]); modify: down to max, up to min, up to multiple [D] [S9] |
| Lead-time offset | Need date, lead time | Release date | `release = need date − lead time`; SAP schedules purchasing processing, planned delivery and goods-receipt time [D] [S1] |
| CRP | Planned/released orders, routings, work-center calendars | Load vs capacity per period | `hours = setup + qty × run time`; D365: `scheduling time = time × 100 ÷ efficiency %` [D] [S16] |
| Leveling | Load, capacity | Moved operations | Move to free slots; overtime; other resource [D-s] [S6] |

### 4.2 Complete numerical example (sample data)

**Factory (working days 1, 2, 3, …; today = day 1).**

BOM (three levels):

```
Phone P (level 0, made in-house, lead time 2 days, work center ASM)
 ├─ 1 × Main board MB (level 1, made in-house, nominal lead time 1 day, work center SMT)
 │    ├─ 1 × PCB  (level 2, bought, supplier lead time 4 days, lot-for-lot)
 │    └─ 2 × CHIP (level 2, bought, lead time 7 days, order multiple 250)
 ├─ 1 × Battery BAT (level 1, bought, lead time 5 days, order multiple 100)
 └─ 1 × Case CASE  (level 1, bought, lead time 3 days, lot-for-lot)
```

Stock on day 1:

| Item | On-hand | Reserved | Safety stock | Scheduled receipts |
| --- | --- | --- | --- | --- |
| P | 50 | 0 | 0 | — |
| MB | 20 | 0 | 0 | — |
| BAT | 300 | 100 (order SO-0, issue day 4) | 50 | 200 on day 6 |
| CASE | 1000 | 0 | 100 | — |
| PCB | 100 | 0 | 0 | — |
| CHIP | 300 | 0 | 100 | — |

Work centers (routing data):

| Work center | Capacity | Run time | Setup |
| --- | --- | --- | --- |
| SMT (makes MB) | 8 h/day (1 machine, 1 shift) | 0.02 h per MB | 0.5 h per order |
| ASM (makes P) | 16 h/day (2 assembly workers × 8 h) | 0.05 h per P | 1 h per order |

Warehouse: receiving capacity 1500 units/day.

**Demand:** customer order SO-1: 500 phones, due day 15.

**Step 1 — Finished-goods netting / MPS.** Available P = 50 → reserve 50 for SO-1. Net = 500 − 50 = **450**.
P lead time 2 days → produce on days 13–14, start (release) day 13, ready for shipment day 15.

**Step 2 — Level 1 explosion** (needed when P starts, day 13): MB 450, BAT 450, CASE 450.

**Step 3 — MB (level 1, made).** Available 20 → net **430**. Nominal lead time 1 day → would run on day 12.
Capacity check on SMT: `0.5 + 430 × 0.02 = 9.1 h` > 8 h → **overload of 1.1 h**. Leveling: spread the order over
days 11–12 (9.1 h of 16 h). MB start moves to **day 11**. This changes the need date of MB's components.

**Step 4 — Level 2 explosion** (needed day 11): PCB 430, CHIP 860.

**Step 5 — MRP records for bought items.**

BAT (safety stock 50, multiple 100, lead time 5):

| Day | 1 | 4 | 6 | 13 |
| --- | --- | --- | --- | --- |
| Gross requirement | | 100 (SO-0) | | 450 |
| Scheduled receipt | | | 200 | |
| PAB before planned order | 300 | 200 | 400 | −50 |
| Net requirement (to keep 50) | | | | 100 |
| Planned receipt (multiple 100) | | | | 100 |
| PAB after | 300 | 200 | 400 | **50** |
| **Planned release** (13 − 5) | | | | day **8** |

CASE: `1000 − 450 = 550 ≥ 100` → no order.

PCB (lead time 4, lot-for-lot): `100 − 430 = −330` → planned receipt **330** day 11, release day **7**.

CHIP (safety stock 100, multiple 250, lead time 7): `300 − 860 = −560`; to keep 100 → net **660** → rounded up to
**750**; release day **4**; PAB after = `300 + 750 − 860 = 190`.

**Step 6 — Capacity (CRP).** SMT days 11–12: 9.1 h of 16 h. ASM days 13–14: `1 + 450 × 0.05 = 23.5 h` of 32 h
(two workers × 8 h × 2 days) → feasible. Workers: 23.5 assembly-skill hours on days 13–14.

**Step 7 — Warehouse.** Receipts on day 11: PCB 330 + CHIP 750 = 1080 ≤ 1500 → feasible.

**Step 8 — Execution timeline.**

| Day | Event | Effect |
| --- | --- | --- |
| 4 | PO CHIP 750 released; SO-0 issue BAT 100 | BAT on-hand 200 |
| 6 | BAT 200 received (old PO) | BAT on-hand 400 |
| 7 | PO PCB 330 released | — |
| 8 | PO BAT 100 released | — |
| 11 | PCB 330 + CHIP 750 received; MB order released; issue PCB 430, CHIP 860 | PCB 0, CHIP 190 |
| 12 (end) | 430 MB completed | MB on-hand 450 |
| 13 | BAT 100 received; P order released; issue MB 450, BAT 450, CASE 450 | BAT 50 (= safety stock), CASE 550 |
| 14 (end) | 450 P completed | P on-hand 500 (reserved for SO-1) |
| 15 | Ship 500 to customer | P on-hand 0 |

### 4.3 The same example under disruptions (what real systems do)

**A. Demand increase (day 6: SO-1 becomes 600).** P net 550 → MB 530 (SMT 11.1 h over days 11–12, still fits).
BAT: net 200; its planned order is not released yet → **change quantity** 100 → 200 [D] [S9]. PCB planned 330 → 430
(not released yet). CHIP: PO 750 is already released; projected `300 + 750 − 1060 = −10` (and safety stock 100) →
a new 250 would arrive day 13, two days late. Real systems produce an exception message and the planner/buyer
chooses [D] [S9] [D-s] [S5]: ask the supplier to increase the existing PO, use safety stock (still 10 short), or
deliver partially (1050 chips → 525 MB + 20 = 545 MB → 595 phones on day 15, 5 later).

**B. Supplier late (CHIP arrives day 13, not day 11).** MB can start only day 13 → P days 15–16 → shipment day 17
(2 days late). Recovery found by leveling and extra capacity: SMT overtime 1.1 h on day 13 (MB ready end of day 13),
plus a third assembly worker on day 14 (24 h ≥ 23.5 h) → shipment still day 15. This needs HR (extra worker,
overtime) and Planning (schedule) to agree — exactly the kind of decision an ERP leaves to people [D] [S8].

**C. Fewer materials (PCB supplier delivers 300 instead of 330).** MB possible: `100 + 300 = 400` + 20 in stock =
420 → P = 420 + 50 = 470 by day 15. Missing 30: new PCB order (4 days) → MB day 15 → P days 16–17 → 30 shipped
day 18. Options for the customer: 470 on day 15 + 30 on day 18, or 500 on day 18.

**D. Customer cancels (day 9).** Release the 50 reserved phones. Planned orders not yet released (MB, P) are
cancelled by planning [D] [S9]. Released POs (CHIP day 4, PCB day 7, BAT day 8) become **cancel suggestions**; whether
they can be cancelled depends on the supplier, so a person/buyer decides; otherwise the goods arrive as extra stock.
(Real systems never assume a released PO can be cancelled automatically — consistent with the project brief.)

**E. Warehouse receiving capacity drops (day 11: 1500 → 800).** Inbound 1080 > 800. Options: PCB 330 one day earlier
(if supplier and storage allow) or CHIP split 470 + 280 (MB starts with 470 chips). This is a supplier-date change
requested by Warehouse — our negotiation model, not an ERP feature (ERPs check location capacity mostly at put-away
[D-s] [S18]).

**F. Worker unavailable.** One assembly worker absent on day 13: ASM capacity days 13–14 = 8 + 16 = 24 h ≥ 23.5 h →
still feasible, but with no slack. Absent both days: 16 h < 23.5 h → late unless overtime or another worker with the
assembly skill (capability-based assignment [D] [S16] [D-s] [S17]).

---

## 5. Resource ownership in real systems

| Resource | How real systems represent it | Who commits it |
| --- | --- | --- |
| Stock on hand | Inventory ledger / on-hand per site, warehouse, location [D] [S8] [S15] | Inventory postings (receipts, issues) |
| Reservations | Physical (on-hand) or ordered (incoming) reservation per order; reserved quantity can't be taken by other orders unless cancelled [D] [S14] | Inventory / order processing — **not planning** [D-s] [S23] [D] [S8] ("the planning system doesn't include reserved quantities") |
| Incoming material | Scheduled receipts: open POs, production orders; planned orders are only proposals [D] [S1] | Purchasing (PO), production control (production order) |
| Supplier commitments | PO + supplier confirmation; SAP scheduling-agreement delivery lines are "fixed elements with a binding character" [D] [S1] | Purchasing |
| Warehouse capacity | Location stocking limits or volume/weight profiles; open receiving work reduces remaining capacity [D-s] [S18] | Warehouse execution at put-away |
| Machines | Resources with calendars, capacity per hour, efficiency, finite/infinite flag, bottleneck flag [D] [S16] | Scheduling (capacity reservation) |
| Workers | Human-resource resources linked to workers; capabilities/competencies with validity dates [D] [S16] | Scheduling, using HR data |

**How shortages are found.** SAP: a shortage is when cumulative requirements up to a point in time exceed cumulative
receipts [D] [S2]. Business Central: projected available inventory below safety stock gives an "exception" warning;
negative projected inventory gives an "emergency" [D] [S8]. This is the same as our ATP rule (`S(t) − C(t) < 0`).

**How double-booking is prevented.** Reservation quantities are excluded from what other demands can use [D] [S8]
[S14]; finite-capacity resources treat existing capacity reservations as unavailable [D] [S16]; order promising
consumes ATP, and its first-come-first-served effect is corrected by backorder processing [D-s] [S3]. Technically,
ERPs post each change as a transaction against the ledger [B]. (Our design: owner-only atomic check-and-update, a
ledger and a balance — QA-1 [P].)

---

## 6. Planning and replanning in real systems

| Change | Typical system reaction | Sources |
| --- | --- | --- |
| Demand up | Re-net; increase quantity of unreleased supply; new supply; reschedule in | [D] [S9] |
| Demand down / cancel | Decrease, reschedule out, or cancel supply; released orders flagged for human decision | [D] [S9] [S8] |
| Supplier late | Receipt date moves; projected stock goes negative earlier; exception/reschedule messages; ATP re-check / backorder processing | [D] [S9] [D-s] [S3] [D-s] [S5] |
| Supplier delivers less | Receipt posted for actual qty; remaining need re-netted | [D] [S9] |
| Capacity drop (machine/worker) | Finite-capacity resources treat existing reservations as unavailable, so new work moves to later free time; capability matching can pick another qualified resource | [D] [S16] [D-s] [S17] |
| Warehouse capacity drop | Put-away rules use remaining capacity; replenishment/put-away blocked or redirected | [D-s] [S18] |

Protections used by real systems:
- **Frozen zone / planning start date:** nothing before it is replanned [D] [S8] [S9].
- **Planning flexibility = None** for supply that is partly handled or in process (receipt, consumption or output
  already posted) [D] [S9].
- **Firm planned orders** are not changed by the planning run [D] [S9] (status list); SAP firming and planning time
  fence [D-s] [S5].
- **Rescheduling window / dampener:** small changes are ignored to avoid "nervousness" [D] [S8] [S9].
- **Net-change planning:** only items whose supply/demand pattern changed are replanned [D] [S8].

---

## 7. Order promising

- SAP: the traditional check is a simple availability check in one plant; advanced ATP adds rules for alternative
  plants/products [D-s] [S4]. Because the check is first-come-first-served in entry order, backorder processing
  re-checks and redistributes confirmed quantities; only confirmed schedule lines can be delivered [D-s] [S3].
- Oracle: Global Order Promising uses CTP to plan transfers, work orders and purchases when existing supply is not
  enough, and pegs that supply to the sales order [D-s] [S24].
- Business Central: real-time ATP warnings at order entry; full planning in batch [D] [S8].

[R] Our Sales → Planning feasibility request is a CTP check (it may trigger supply planning and negotiation). The
24 h hold (NG-2) is our own design; the nearest ERP equivalent is a confirmed sales-order line that consumes ATP.

---

## 8. Differences between ERP products (do not assume one workflow)

| Topic | SAP S/4HANA | Dynamics 365 SCM / Business Central | Odoo | Oracle Fusion |
| --- | --- | --- | --- | --- |
| Planning output | Planned orders (make), purchase requisitions or schedule lines (buy) [D] [S1] | Planned orders / planning-worksheet action lines [D] [S8] | MPS suggests; user orders; reordering rules or MTO create orders [D] [S20] | Make/buy/transfer planned orders released to execution [D-s] [S25] |
| Safety stock | Field per material/plant [D] [S1] | Demand may consume it; strict pegging optional [D] [S10] [S11] | "Safety stock target" in MPS [D] [S20] | Not researched |
| Reservations | Not researched in depth | Physical + ordered; automatic/manual/explosion [D] [S14] | At confirmation / manual / before scheduled date [D-s] [S21] | Created by inventory, only displayed by planning [D-s] [S23] |
| Capacity | Leveling of infinitely scheduled operations [D-s] [S6] | Finite/infinite per resource, capabilities [D] [S16] | Work-center capacity = parallel units; working hours [D-s] [S22] | Not researched |
| Promising | ATP, aATP, backorder processing [D-s] [S3] [D-s] [S4] | Real-time ATP warnings (BC) [D] [S8] | Not researched | GOP with CTP and pegging [D-s] [S24] |
| Notable rule | Rescheduling check before new proposals [D-s] [S5] | MPS and reordering rules must not be mixed (Odoo) — n/a | Don't combine MPS with reordering rules [D] [S20] | Planning doesn't create reservations [D-s] [S23] |

"Not researched" means no evidence was gathered for this report; no claim is made.

---

## 9. Our decentralized six-agent approach

### 9.1 Practice vs our choice

| Element | Established practice? | Notes |
| --- | --- | --- |
| Planning proposes, owners commit | **Yes** [D] [S1] [S8] [S23] | Matches HA-3, NG-4 |
| Deterministic MRP/ATP math | **Yes** [B] | Matches CLAUDE.md |
| Reservations owned by Inventory | **Yes** [D-s] [S23] [D] [S14] | |
| Workers as calendar + skills | **Yes** [D] [S16] | HR agent owning this is our mapping |
| Event-driven pub-sub between functions | Partly — ERP modules share one database; events are our architecture [R] | Outbox pattern is documented [L] [S30] |
| Negotiation between functions | **Our choice / research** [L] [S26] [S27] [S28] | ERPs leave exceptions to planners and buyers [D] [S8] |
| Holds on agreement with expiry | Our choice | Closest: confirmed ATP, soft/ordered reservations |
| Storage space as a planning constraint | Our simplification | ERPs check it at put-away [D-s] [S18] |
| Compensation instead of global rollback | Documented pattern (saga) [L] [S31] | |

### 9.2 Responsibility matrix

| Resource / decision | Owner (commits) | Reads it | Asks owner to change it (negotiation) | Fact events |
| --- | --- | --- | --- | --- |
| Customer order, promised date | Sales | Planning | Planning (via Sales doors) | OrderConfirmed, OrderChangeRequested, OrderCancelled |
| MPS, planned orders, schedule, production orders | Planning | Sales, Warehouse, HR | — | PlanCommitted, PlanRevised, PlanAtRisk, ProductionStarted/Completed |
| Machine capacity (work centers) | Planning | — | — | (internal) |
| Stock, reservations, safety stock | Inventory | Planning | Planning | ReservationCommitted/Released, StockAvailabilityChanged, SafetyStockBreached |
| Purchase orders, supplier dates/quantities | Purchasing | Planning, Inventory, Warehouse | Planning, Warehouse | ProcurementCommitted, SupplierDeliveryDelayed, SupplierQuantityReduced |
| Receiving capacity, storage space, put-away, issue, shipment | Warehouse | Planning, Purchasing | Purchasing, Planning | ReceivingSlotCommitted, MaterialReceived, MaterialIssuedToProduction, StorageCapacityChanged, ShipmentDispatched |
| Worker hours, skills, shifts, overtime limits | HR | Planning, Warehouse | Planning, Warehouse | WorkforceCommitted, WorkforceCapacityChanged |

[R] Open question raised by the research: in ERPs, **production orders** belong to production control, not to
planning. Since we have no Production agent, Planning should own production orders explicitly (and the doc should
say so), or the developer decides otherwise.

### 9.3 Event catalogue — research view

The approved catalogue (`pubsub_event_channel.md` §8) maps well onto ERP documents: sales order confirmation,
PO/confirmation, goods receipt, goods issue, production order completion, shipment. Proposed additions [R] for
discussion only:
- `ProductionOrderReleased` (Planning) — ERPs separate planned → released → started → completed; release is when
  material reservations are made [D] [S14] (production reservation point).
- `PlanningExceptionRaised` is **not** proposed: exceptions stay private to the owner/starter and reach others only
  as outcomes, consistent with the approved design.

### 9.4 Negotiation model — research view

- The starter/owner model resembles the **contract-net protocol** (manager announces, contractors bid, award)
  [L] [S26]; we use direct owner lookup instead of open bidding because each resource has exactly one owner.
- Conflicting negotiations at one owner correspond to **first-come-first-served ATP problems**; SAP fixes them with
  backorder processing [D-s] [S3]. Our NG-3 priority queue (slack → aging → FIFO) is a per-request version of the same
  idea [R].
- ERPs use **dampeners and rescheduling windows** to avoid nervous replanning [D] [S9]; [R] we should add a small
  dampener (ignore changes smaller than X days / Y units) to avoid negotiation storms in the 100-order test.

---

## 10. Realistic simulation: minimum data and rules

### 10.1 Minimum data [R]

| Data | Minimum | Why |
| --- | --- | --- |
| Products and items | 2 finished products sharing some components | Shared components create real conflicts |
| BOM | 3 levels (FG → sub-assembly → bought parts) | Dependent demand and low-level codes [D] [S8] |
| Routings | 1–2 operations per made item: work center, setup h, run h/unit | CRP and leveling [D] [S16] |
| Work centers | 2–3, each with hours/day calendar, efficiency, finite flag | Capacity limits |
| Workers | 4–8 workers, skills, shifts (8 h), absences | HR constraints [D] [S16] |
| Stock | On-hand, reserved, safety stock per item | Netting |
| Suppliers | 1–2 per bought item: lead time, order multiple/minimum, capacity per period, reliability | Procurement choices |
| Open orders | 3–10 existing customer orders, POs, production orders at different stages | Competing demand; frozen supply |
| Warehouse | Receiving capacity/day, 2 zones with space units, item space per unit | Storage constraint |
| Calendar | Working days, today's date (simulated clock) | Time-phased planning |

### 10.2 Rules that make outcomes depend on state (not scripts) [R]

- All outcomes come from the same deterministic calculations applied to the current state; scenarios only change
  facts (a date, a quantity, a capacity) through the owner's input.
- Variety comes from **state variety**: different starting snapshots (stock levels, open orders, absences) give
  different results for the same event.
- Optional seeded randomness only for outside-world facts (supplier delay of 0–3 days with a fixed seed), never for
  agent decisions.
- Store each run's seed and starting snapshot so any run can be replayed exactly.

---

## 11. Gap analysis (repository and `dev_docs/`, inspected 2026-10-17)

### 11.1 Current code (`backend/app/`)

| Area | What exists [P] | Verdict vs research |
| --- | --- | --- |
| `mrpii/mps.py` | FG netting `max(0, order − available FG)`; one MPS entry per order line; backward schedule by production lead time | **Correct** for per-order MTO; **incomplete**: no period buckets, no aggregation across orders |
| `mrpii/mrp.py` | Single-level explosion; netting per order with scheduled receipts consumed in date order | **Correct netting idea**; **incomplete**: single level only, no low-level codes, all components needed at `planned_start` with no purchase lead-time offset, no lot sizing (multiples/minimum), safety stock only via `available_quantity` |
| `mrpii/capacity.py` | `ceil(qty / capacity_per_day) ≤ production lead time` per product | **Too simple** for HR/machine realism: no work centers, routings, setup/run times, calendars, or sharing of capacity between orders |
| `mrpii/scheduling.py` | Backward schedule: start = due − lead time | Correct basic rule; no finite scheduling |
| `mrpii/suppliers.py` | Supplier feasibility from fixture | Reusable as supplier data rules |
| `services/inventory_service.py` | `available = on_hand − reserved − safety_stock`, row lock on reserve | **Correct and reusable**; missing holds, ledger, ordered (incoming) reservations |
| `models/` | Reservations, supplier items with lead time, requisitions; no POs, no production orders, no work centers | **Incomplete** for the full workflow |
| `negotiation/`, A2A | Generic protocol pieces, fixed routes | Reusable as reviewed in `negotiation.md` §10 |
| `simulation/` | Empty files | **Missing** |
| `sales_agent/` | Complete conversational agent with guarded confirmation | **Correct** for its scope; separate acceptance and commitment matches research |
| Old approval workflow (C8) | Human approves each plan | Conflicts with the approved autonomy direction (NG-4) |

### 11.2 Approved design docs

| Doc | Correct vs research | Incomplete / potentially wrong | Unnecessary for prototype |
| --- | --- | --- | --- |
| `high_level_architecture.md` | Ownership map; Planning starts procurement (= MRP creates requisitions) | Production orders have no explicit owner; machine capacity listed under Planning without routings | — |
| `pubsub_event_channel.md` | Outbox, per-subscriber retries, versions | No `ProductionOrderReleased`; no dampener against event storms | — |
| `negotiation.md` | Starter/owner, holds, compensation | Holds for every inquiry may block stock in the 100-order test; ERPs promise against ATP without per-inquiry holds — measure before tuning | — |
| `quantity_accounting.md` (draft) | ATP with look-ahead; ledger + balance; delta changes; incoming promised by date (= ordered reservations) | Safety stock rule stricter than ERP default (our choice, keep or relax); no lot sizing or lead-time offset rules yet | — |

Items that real ERPs have but the prototype **does not need**: forecasting and forecast consumption, multi-plant
transfers, lot/serial tracking, costing, volumetric WMS, finite job-shop optimization, DDMRP.

---

## 12. Recommended end-to-end workflow [R]

**Normal flow**
1. Sales collects order details → feasibility request (CTP) to Planning.
2. Planning: FG netting → MPS → multi-level MRP (low-level codes) → lot sizing → lead-time offset → CRP per work
   center. Produces planned orders (proposals) with dates.
3. Planning negotiates in parallel with owners: Inventory (stock/holds), Purchasing (buy proposals → supplier
   dates), Warehouse (receipts/space on arrival dates), HR (worker hours per work center/day).
4. Planning returns options; Sales presents; customer confirms (`OrderConfirmed`).
5. Planning re-validates and commits: owners convert holds into reservations/commitments; Planning firms its planned
   orders inside the time fence and releases production orders on their start dates.
6. Execution through events: receipts, issues, production completion, shipment.

**Exceptions and replanning**
- A fact event marks affected items (net-change planning); Planning re-nets only those items.
- Released/started supply is not changed automatically; firm orders inside the time fence need negotiation.
- Small changes below a dampener are ignored.
- Conflicts at an owner are resolved by NG-3 ordering; failures escalate to a human with reason codes.

---

## 13. Prioritized roadmap for missing capabilities [R]

| Priority | Capability | Why | Alternatives / trade-off |
| --- | --- | --- | --- |
| 1 | Multi-level BOM with low-level codes | Without it dependent demand is unrealistic | Keep single level (simpler, less believable) |
| 2 | Lead-time offset and lot sizing per bought item | Correct release dates and quantities | Lot-for-lot only (simpler, no surplus effects) |
| 3 | Work centers, routings, calendars; CRP per day | HR and machine constraints need hours, not "units per product" | Keep per-product capacity (cannot model a worker absence) |
| 4 | Planned / firm / released / started order states and a time fence | Safe replanning | No states (every disruption replans everything) |
| 5 | Pegging records (which supply covers which order) | To know which orders a delay affects | Recompute by due-date walk each time (slower, harder to explain) |
| 6 | Explicit owner for production orders (Planning) | No gap in ownership | A seventh agent (rejected by scope) |
| 7 | Dampener for replanning | Avoid negotiation storms at 100 orders | None (risk of loops) |
| 8 | Simulation snapshot model (§10) | Repeatable, state-driven demos | Scripted scenarios (forbidden by the brief) |

Fits the roadmap as: items 1–8 decided in Phase 1 docs (Planning, Inventory, Warehouse, HR docs and `demo.md`),
reviewed against old code in Phase 2, implemented from Phase 3 on.

---

## 14. Decisions for the developer (one at a time)

1. Multi-level BOM (3 levels) — yes / no.
2. Work centers + routings + calendars replacing `capacity_per_day` — yes / no.
3. Planning explicitly owns production orders — yes / other.
4. Planned → firm → released → started states and a time fence — yes / no.
5. Explicit pegging records — yes / no.
6. Safety stock: keep QA-2 (strict, our choice) or follow the ERP default (demand may consume, replenish at once).
7. Add `ProductionOrderReleased` to the event catalogue — yes / no.
8. Replanning dampener — yes / no, and its starting values.
9. Whether to approve `quantity_accounting.md` as is or after these decisions (it is still a draft).

---

## 15. Sources

Official product documentation:
- [S1] SAP Learning — Running Materials Requirements Planning (S/4HANA): https://learning.sap.com/courses/business-processes-in-sap-s-4hana-sourcing-procurement/running-materials-requirements-planning **[D]**
- [S2] SAP Learning — Evaluating Planning Results: https://learning.sap.com/courses/exploring-business-processes-in-sap-s-4hana-production-planning/evaluating-planning-results **[D]**
- [S3] SAP Learning — Explaining the concept of backorder processing (BOP): https://learning.sap.com/courses/performing-the-availability-check/explaining-the-concept-of-backorder-processing-bop-_b6d7bcf7-5096-3595-9411-fce7f32209f7 **[D-s]**
- [S4] SAP Learning — Using Advanced Available-To-Promise (aATP): https://learning.sap.com/courses/functions-innovations-in-sap-s-4hana-sales/using-advanced-available-to-promise-aatp-in-sap-s-4hana_ef38afd2-4730-433f-854a-613b8e4afec5 **[D-s]**
- [S5] SAP Help (release 4.6C, old) — Rescheduling Check: https://help.sap.com/SAPHelp_46c/helpdata/EN/f4/7d2c9744af11d182b40000e829fbfe/content.htm **[D-s]**; time-fence/firming details came from SAP community answers and are not used as evidence beyond this page
- [S6] SAP Learning — Capacity Leveling Using the Capacity Scheduling Table: https://learning.sap.com/courses/exploring-the-capacity-planning-in-sap-s-4hana/capacity-leveling-using-the-capacity-scheduling-table **[D-s]**
- [S8] Microsoft Learn — Business Central, Design details: central concepts of the planning system: https://learn.microsoft.com/en-us/dynamics365/business-central/design-details-central-concepts-of-the-planning-system **[D]**
- [S9] Microsoft Learn — Business Central, Design details: balancing supply and demand: https://learn.microsoft.com/en-us/dynamics365/business-central/design-details-balancing-demand-and-supply **[D]**
- [S10] Microsoft Learn — D365 SCM, Safety stock fulfillment for items: https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/safety-stock-replenishment **[D]**
- [S11] Microsoft Learn — D365 SCM, Safety stock pegging options: https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/safety-stock-pegging **[D-s]**
- [S12] Microsoft Learn — D365 SCM, Coverage settings: https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/coverage-settings **[D-s]**
- [S13] Microsoft Learn — D365 SCM, Replenishment methods and quantity modification: https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/planning-optimization/replenishment-methods-quantity-modification **[D-s]**
- [S14] Microsoft Learn — D365 SCM, Reserve inventory quantities: https://learn.microsoft.com/en-us/dynamics365/supply-chain/inventory/reserve-inventory-quantities **[D]**
- [S15] Microsoft Learn — D365 SCM, Reservations in Warehouse management: https://learn.microsoft.com/en-us/dynamics365/supply-chain/warehousing/reservations-in-warehouse-management **[D-s]**
- [S16] Microsoft Learn — D365 SCM, Operations resources: https://learn.microsoft.com/en-us/dynamics365/supply-chain/production-control/operations-resources **[D]**
- [S17] Microsoft Learn — D365 SCM, Scheduling with resource selection based on capability: https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/planning-optimization/capability-based-scheduling **[D-s]**
- [S18] Microsoft Learn — D365 SCM, Location stocking limits: https://learn.microsoft.com/en-us/dynamics365/supply-chain/warehousing/location-stocking-limits **[D-s]**
- [S19] Microsoft Learn — D365 SCM, Coverage time fences: https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/planning-optimization/coverage-time-fence **[D-s]**
- [S20] Odoo documentation — Master production schedule: https://www.odoo.com/documentation/master/applications/inventory_and_mrp/manufacturing/workflows/use_mps.html **[D]**
- [S21] Odoo 18.0 documentation — Reservation methods: https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/shipping_receiving/reservation_methods.html **[D-s]**
- [S22] Odoo 19.0 documentation — Work centers: https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing/advanced_configuration/using_work_centers.html **[D-s]**
- [S23] Oracle Fusion Cloud SCM — Reservations in Supply Chain Planning: https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/23d/fausp/reservations-in-supply-chain-planning.html **[D-s]** (direct fetch returned only the guide's title page)
- [S24] Oracle — Global Order Promising solution brief: https://oracle.com/a/ocom/docs/applications/scm/global-order-promising-solution-brief.pdf **[D-s]**
- [S25] Oracle Fusion Cloud SCM — Release Project-Specific Supply Recommendations: https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26a/fausp/release-project-specific-supply-recommendations.html **[D-s]**

Research and pattern literature:
- [S26] R. G. Smith, "The Contract Net Protocol: High-Level Communication and Control in a Distributed Problem Solver," *IEEE Transactions on Computers*, C-29(12):1104–1113, 1980. DOI: https://doi.org/10.1109/TC.1980.1675516 **[L]**
- [S27] H. Van Brussel, J. Wyns, P. Valckenaers, L. Bongaerts, P. Peeters, "Reference architecture for holonic manufacturing systems: PROSA," *Computers in Industry*, 37(3):255–274, 1998. DOI: https://doi.org/10.1016/S0166-3615(98)00102-X **[L]**
- [S28] P. Leitão, "Agent-based distributed manufacturing control: A state-of-the-art survey," *Engineering Applications of Artificial Intelligence*, 22(7):979–991, 2009. Repository: https://bibliotecadigital.ipb.pt/handle/10198/1536 **[L]**
- [S29] W. Shen, Q. Hao, H. J. Yoon, D. H. Norrie, "Applications of agent-based systems in intelligent manufacturing: An updated review," *Advanced Engineering Informatics*, 20(4):415–431, 2006. **[L]**
- [S30] C. Richardson, Pattern: Transactional outbox: https://microservices.io/patterns/data/transactional-outbox.html **[L]**
- [S31] C. Richardson, Pattern: Saga: https://microservices.io/patterns/data/saga.html **[L]**

Textbooks (book-level, not re-checked online for this report) **[B]**:
- ASCM (APICS) Dictionary — standard definitions of MRP terms.
- C. Ptak, C. Smith, *Orlicky's Material Requirements Planning*, 3rd ed., McGraw-Hill, 2011.
- T. Vollmann, W. Berry, D. Whybark, F. R. Jacobs, *Manufacturing Planning and Control for Supply Chain Management*, McGraw-Hill.
- W. Hopp, M. Spearman, *Factory Physics* (on MRP's infinite-capacity and fixed-lead-time assumptions).

Gaps in evidence: SAP's own help pages for S/4HANA MRP Live, reservations and time fences were not read; Oracle
safety-stock and capacity handling, and Odoo ATP, were not researched; the full texts of the research papers were
not read.
