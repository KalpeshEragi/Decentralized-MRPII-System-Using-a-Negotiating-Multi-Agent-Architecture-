# One order end to end: a real production simulation, decentralised feasibility, agents that think

**Status: approved 2026-10-27 (SIM-1..5, DC-1, AB-1..2, `DECISIONS.md`); step 1 built.** Developer's request: "first, one order — how does our system perform".
Builds on `quotes_and_agent_decisions.md` (approved QD-1..11) and does not repeat it. Open decisions in §7.

## 1. What happens today (inspected 2026-10-27)

| Point | Today | Effect seen (80 TABLET-T, `not_feasible`) |
| --- | --- | --- |
| Feasibility | `planning_agent/plan.py` computes the whole plan from a snapshot of every owner's data (stock, hours, dock, lead times), then asks owners to confirm | Inventory answered "insufficient" for MB, BAT, CHIP, PCB; the option failed; round 2 failed the same way |
| Shortage | A counter-offer fails the option (with AI off D7 falls back to "next option"); Planning does not turn the missing part into "make it" or "buy it" | "only from stock or reject" |
| Shop floor | `simulation/shop_floor.py`: an order starts on its start day; its whole quantity appears at the end of its end day | No hours, no batches, no component → assembly flow |
| Agent brain | Think loop: one prompt, at most one fact lookup, then one action | The agent cannot look around, compare paths, then act |

## 2. The one-order story we want to see (scenario ONE)

Factory A, one customer asks for **80 tablets in 9 days**. Stock covers part of it; the rest must be made and bought.

```
Day 1 08:00  Sales: request → Planning (MPS: 80 TABLET-T due day 9)
             Planning asks owners for QUOTES (not reads): Inventory, HR, Warehouse, Purchasing
             Inventory: "20 tablets now; MB 20 now; BAT 140 now, rest only if bought"
             Purchasing: "160 CHIP + 60 PCB from Silicon Parts / Board Works, arrive day 5 (lead 4–7 d)"
             HR: "SMT 2 workers 08–16, ASSEMBLY 3 workers 08–16"
             Planning (thinks): plan = 20 from stock + make 60: MB first, then assembly — options to Sales
Day 1 08:40  Customer confirms → commit with every owner → PlanCommitted
Day 5 09:00  Truck: CHIP and PCB received (dock slot booked by Warehouse)
Day 6 08:00  MB production order released; kits issued (PCB, CHIP)
     08:30   SMT setup done; batch 1 of 25 MB … 09:00 … 09:30 … every 30 min a batch is reported
     11:00   60 MB done → stored → available for assembly
Day 7 08:00  ASSEMBLY: 60 tablets in batches of 20 (setup 1 h, 0.08 h/pc × crew) … done 14:30
     15:00   finished goods stored; Day 9 08:00 shipment dispatched → order COMPLETED
```

Every line is a real state change by its owner, visible in the timeline, the 3D town and the agent drawers.

## 3. Production simulation in hours and batches

| ID | Rule |
| --- | --- |
| SIM-1 | The clock gets hours. A simulated day has working hours (setting `shift_start` 08:00, `shift_hours` 8; two shifts later). **Next hour** and **Next day** buttons; Play advances one simulated hour per tick (setting `seconds_per_sim_hour`, default 2). Day-level routines (holds, releases, receiving) run at `shift_start`. |
| SIM-2 | The shop floor executes each production order's **operations** from its routing (setup hours + run hours per unit per work center) in **batches** (setting per item `batch_size`, default 25). A batch is done when its hours have passed on the work center with its crew present (HR's assignment). |
| SIM-3 | Every finished batch is reported to Planning (`QUANTITY_COMPLETED` with the batch quantity, as the shop-floor door already allows); Planning publishes `ProductionBatchCompleted`; Warehouse stores the batch, so components are available to the next operation (sub-assembly → assembly) as soon as they exist. |
| SIM-4 | A missing input stops the operation (no kit, no worker, machine busy): the shop floor reports `BLOCKED` with the reason; Planning decides (think loop) — wait, re-sequence, or ask the owner. |
| SIM-5 | After the customer's confirmation nothing needs a click: commit → release → kits → batches → storage → shipment run by themselves as the clock moves. |

## 4. Decentralised feasibility (no central calculation)

| Who | Owns and calculates (with the shared pure library `app/mrpii`) | Answers |
| --- | --- | --- |
| Planning | MPS (what finished goods by when), BOM explosion, its own machine-hours, the production schedule | the needs per component and day |
| Inventory | its stock, ATP, safety stock, what it can promise and when | QUOTE: now / partial / later / via purchase |
| Purchasing | supplier options, lead times, minimum quantities | QUOTE: supplier legs with dates |
| HR | workers, skills, shifts, overtime | QUOTE: hours per day / overtime / later |
| Warehouse | dock slots, space | QUOTE: slot / later |

`app/mrpii` stays a **calculator** (BOM explosion, ATP, hours, netting) that every agent may use on **its own** data; it
never decides. Planning stops reading the other owners' free capacity for feasibility (QD design §4, steps 3–4).
A shortage becomes a decision (make or buy the rest), not a rejection.

## 5. The agent's brain: look around, compare, choose the stable optimum

| ID | Rule |
| --- | --- |
| AB-1 | The think loop becomes a short tool loop: the agent may call up to 4 of its own read tools (one at a time, results back to it), then propose. Budget per decision: 6 model calls; still one agent per call (QD-11). |
| AB-2 | Every agent's goal states the same two objectives in its own terms: **optimal** (on time, full quantity, least cost/overtime) and **stable** (fewest changes to what is already committed, no promises it may have to break). The prompt gives the numbers to compare (e.g. days late, changes to commitments, overtime hours, stock left). |
| AB-3 | The agent proposes; code validates (hard limits, current facts); one revision; else the deterministic fallback (unchanged from QD-7). |
| AB-4 | Every decision card shows the tools it used, the paths it compared and why it picked one. |

## 6. Build order (one order first)

1. **[built]** **SIM-1/2/3/5**: hourly clock (Next hour, Play per hour), batch shop floor on Planning's scheduled hours,
   `ProductionBatchCompleted`, per-batch storage; scenario ONE; 3D line pin "running 25/60". First run (test data):
   40 MB on day 9 (25 at 12:00, last 15 at 16:00), 60 tablets on day 10 (25 at 11:00, 50 at 14:00, last 10 at
   16:00), shipped day 11 — no clicks after the confirmation. Next day works the whole shift, so earlier scenarios
   keep their results.
2. **QD steps 3–4 for this order**: QUOTE_REQUEST/QUOTE with Inventory, Purchasing, HR, Warehouse; Planning builds the plan
   from quotes; make-or-buy for the shortage.
3. **AB-1/2/4**: tool loop and the two objectives; Planning (D6/D7) and Inventory (D1/D2) first.
4. **SIM-4**: blocked operations and Planning's decision on them.

## 7. Open decisions (to approve)

| ID | Question | Recommendation |
| --- | --- | --- |
| SIM-1 | Hourly clock with working hours, Next hour / Next day, Play = one simulated hour per tick | Yes; 8 h shift first |
| SIM-2 | Batches per item (`batch_size` rule per item, default 25) on the routing's setup/run hours | Yes |
| SIM-3 | New event `ProductionBatchCompleted` (Planning → Warehouse, Inventory, Sales optional) | Yes, through the event manager |
| SIM-4 | Blocked operations reported and decided by Planning | After 1–3 |
| SIM-5 | Confirmed orders run to delivery without clicks | Yes (already true per day; now per hour) |
| DC-1 | Feasibility by owner quotes; `app/mrpii` a shared calculator, never a decider; no central engine outside Planning | Yes (it is QD-1; an engine outside Planning would still be central) |
| AB-1 | Tool loop: up to 4 tool calls, 6 model calls per decision | Yes; measure on qwen3.5:4b (~3 s per short call) |
| AB-2 | Two objectives (optimal, stable) in every agent's goal, with numbers to compare | Yes |
