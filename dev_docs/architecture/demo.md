# Simulation Controls and How the Demo Is Run

**Status:** APPROVED by the developer (2026-10-17). Nothing new here is implemented.
**Related:** `system_design.md` (clock, settings, runner), `backend_api.md` (doors, observer API),
`pubsub_event_channel.md` §9 (triggers travel the normal path), the agent folders,
`../research/real_manufacturing_mrpii_research.md` §10 (minimum factory data).

## 1. Purpose

The simulator is the outside world and the stage: it sets up a factory, moves simulated time, plays customers,
suppliers, the shop floor and workers' absences, and lets a demo operator trigger changes and see what the agents
did and why. It is **infrastructure, not an agent**: it changes conditions; agents decide responses.

## 2. Decisions (2026-10-17)

| ID | Decision |
| --- | --- |
| DM-1 | Time moves by "Next day" or by "Play", which advances only when the factory is **quiet** (§6). |
| DM-2 | Starting states are **database snapshots**: build once, "Save state", "Restore" exactly (§5). |
| DM-3 | A **scripted customer driver** plays customers through the normal Sales door with a fixed, seedable rule; the operator can still chat live (§9). |
| DM-4 | On reset, a **run report** is saved, then all run data is cleared or restored (§12). |
| DM-5 | Every simulated day is a working day unless HR's calendar says otherwise for a worker (resolves HR-O2 / HB-O2). |
| DM-6 | Randomness is optional, only for outside-world facts, and always seeded per run (§10). |
| DM-7 | The customer driver has two modes, chosen by a setting (decided 2026-10-20): **structured** (default; product, quantity and date reach Sales as data through a simulated-customer door, so only the language-reading step is skipped and everything after is Sales' normal code; for large runs such as 100 orders, no Ollama needed) and **chat** (simulated customers type messages that Sales reads with the model; for showing one or two orders live). Refines DM-3. |

## 3. Parts of the simulator

| Part | Job | Talks to |
| --- | --- | --- |
| Configuration | Validated setup of the factory before a run (§4) | Owners' setup doors, `core`, factory settings |
| State store | Save / restore named starting states (§5) | All run tables |
| Clock | Simulated date; `SimulatedDayStarted` (PB-3) | Event channel |
| Trigger catalogue | Known changes the operator can fire now or schedule for a day (§7) | Owners' inputs only |
| Outside-world adapters | Customer driver (→ Sales), supplier simulation (→ Purchasing; details in the Purchasing doc), deliveries (→ Warehouse), shop floor (→ Planning), absences (→ HR) | Owners' input doors |
| Scenario runner | Plays a scenario: starting state + scheduled triggers + customer rules + seed (§8) | All of the above |
| Run manager | Start, pause, finish, report, reset (§12) | All of the above |

The simulator never writes agents' tables directly except through **restore** (§5), which loads an exact copy of a
state that the agents themselves produced.

## 4. Configuring the environment

Only while the run is CONFIGURING (no work running). Each owner validates its own part through a setup door
(`X-Door-Key`); the simulator checks references across owners.

| What | Owner / where | Door |
| --- | --- | --- |
| Items, BOM, routings, make/buy, space per unit | `core` (shared reference) | `POST /simulation/reference` |
| Stock on hand, safety stock | Inventory | `POST /inventory/setup` |
| Work centers, calendars | Planning | `POST /planning/setup` |
| Zones, receiving and shipping capacity | Warehouse | `POST /warehouse/setup` |
| Workers, skills, calendars | HR | `POST /hr/setup` (HB-O1) |
| Suppliers | Purchasing | Later (Purchasing doc) |
| Factory settings (SD-2) | `simulation.settings` | `POST /simulation/settings` |
| Existing open orders | Built through the **normal flow** with the customer driver, then saved in the state | — |

Cross checks: every BOM and routing item exists; every routing's work center exists in Planning and its skill in HR;
every bought item has a supplier (once Purchasing exists); all numbers ≥ 0. Errors use RFC 9457 (API-1).

### 4.1 Default demo factory ("Factory A", starting values)

Built from the research report's example (§4.2) plus a second product that shares the main board, so orders compete:

| Item | Make/buy | BOM | Stock / safety | Routing / supply |
| --- | --- | --- | --- | --- |
| Phone P | Make | 1 MB, 1 BAT, 1 CASE | 50 / 0 | ASM: setup 1 h, 0.05 h/pc, crew 1, skill ASSEMBLY |
| Tablet T | Make | 1 MB, 2 BAT, 1 CASE-T | 20 / 0 | ASM: setup 1 h, 0.08 h/pc, crew 1, skill ASSEMBLY |
| Main board MB | Make | 1 PCB, 2 CHIP | 20 / 0 | SMT: setup 0.5 h, 0.02 h/pc, crew 1, skill SMT |
| Battery BAT | Buy | — | 300 / 50 | lead time 5 d, multiple 100 |
| Case CASE, CASE-T | Buy | — | 1000 / 100, 300 / 50 | lead time 3 d |
| PCB | Buy | — | 100 / 0 | lead time 4 d |
| CHIP | Buy | — | 300 / 100 | lead time 7 d, multiple 250 |

Work centers: SMT 8 h/day, ASM 16 h/day. Workers: 2 SMT, 3 ASSEMBLY (one also SMT), 8 h shifts. Warehouse:
MATERIALS 2 000 space units, FINISHED_GOODS 1 000, receiving 1 500 units/day, shipping 1 000 units/day.
Settings: defaults from the agent docs. All values are starting values to tune after the first runs.

## 5. Starting states (DM-2)

- **Build:** configure (§4), then optionally run a few days with the customer driver to create existing orders,
  commitments and production in progress.
- **Save state:** when the factory is quiet, copy every run table (all agent schemas, `core`, `events`,
  `negotiation`, `simulation` clock and settings) into `simulation.snapshots` (name, description, created_at, one
  JSON document per table). Queues must be empty or only hold FAILED items, which are not saved.
- **Restore:** in one transaction, empty the run tables and load the snapshot exactly; then every owner's reconcile
  check runs and must report no difference.
- Same snapshot + same scenario + same seed + same AI behaviour → the same run. (With the real model the AI wording
  may differ, but decisions do not, because every decision is code or validated against code.)

## 6. Clock (DM-1)

| Control | Effect |
| --- | --- |
| Next day | Advance one simulated day now: publish `SimulatedDayStarted(date)` |
| Play | Advance automatically, but only when the factory is quiet; pauses by itself when nothing is left to do |
| Pause | Stop advancing; work already queued finishes |

**Quiet** = no PENDING or RUNNING item in any queue (FAILED items do not count), no outbox waiting, and no
negotiation waiting on an agent. A day that does not become quiet within a limit (setting, default 5 minutes real
time) pauses the run and shows what is still waiting.

**Nothing left to do** = no open customer demand (all completed, cancelled, expired or failed), no scheduled trigger,
and no simulated customers placing orders (`customer_orders_per_day` = 0). Play then pauses by itself with that
reason (shown on the panel) instead of moving the clock through empty days. Next day still works by hand.

Real-time limits (negotiation response timeouts, NG-O2; leases; retries) only protect against stuck work. Because
Play waits for quiet, no business step is ever cut off by a day change; business deadlines (holds, offers) are counted
in simulated days.

## 7. Triggers

A trigger changes a fact through the owner's input; the owner publishes the event (pub-sub §9). Each can be fired now
or scheduled for a simulated day.

| Trigger | Input | Resulting event |
| --- | --- | --- |
| New customer order / demand increase | Customer driver → Sales door 1 | (Sales flow) → `OrderConfirmed` |
| Order change / cancellation | Customer driver → Sales | `OrderChangeRequested`, `OrderCancelled` |
| Supplier delivery late | Supplier simulation → Purchasing | `SupplierDeliveryDelayed` |
| Supplier quantity reduced | Supplier simulation → Purchasing | `SupplierQuantityReduced` |
| Delivery arrives short / over | Delivery input → Warehouse | `MaterialReceived` (received / refused) |
| Storage or receiving capacity cut | `POST /warehouse/capacity-changes` | `StorageCapacityChanged` |
| Worker absent | `POST /hr/absences` | `WorkforceCapacityChanged` |
| Machine down | Shop-floor adapter → Planning | `PlanRevised` / `PlanAtRisk` (after replanning) |
| Production finishes short | Shop-floor adapter → Planning | `ProductionCompleted` (partial) |

Every trigger the operator fires is logged (`simulation.trigger_log`) and appears in the timeline.

## 8. Scenarios

A scenario = a starting state + a list of (simulated day, trigger) + customer-driver rules + a seed. Stored in
`simulation.scenarios` (JSON). Known scenarios follow the roadmap's test progression:

| # | Scenario | What it shows |
| --- | --- | --- |
| S1 | One normal order | Full flow: request → options → confirmation → commitment → production → shipment |
| S2 | Supplier delay | Negotiation, AT_RISK, recovery with overtime / later date |
| S3 | Material shortage | Procurement started by Planning, holds, options |
| S4 | Storage limit | Warehouse counter-offer, date change with Purchasing (step 8: needs the receiving slot, WH-1) |
| S5 | Worker absence | HR cover (reassign, move, overtime) or AT_RISK |
| S6 | Cancellation | Releases, compensation, PO cancel request |
| S7 | Order change | Delta handling (QA-3) |
| S8 | Competing orders | Priority rule (NG-3), no double booking |
| S9 | Load | 10, 20, then 100 orders; measurements (Phase 6) |

## 9. Customer driver (DM-3)

- Simulated customers (fictional phone numbers) send requests through Sales door 1 — the same path as a real chat.
- Two modes (DM-7): **structured** (default, for large runs: the request reaches Sales as data) and **chat**
  (messages read by the model, for showing one or two orders live).
- Rules (configurable, seeded): orders per simulated day, product mix, quantities, requested dates.
- Answering options: it reads the inquiry's options from Sales' view door (structured data, not the chat text) and
  replies with a short fixed message by a rule (default: accept REQUESTED; else LATER_DATE if ≤ 10 days later; else
  decline), then confirms with "yes".
- It never calls agents' internals and never changes agents' data.
- The operator can still chat live in the Sales test page during a demo.

## 10. Randomness (DM-6)

Off by default. When on, only outside-world facts vary: supplier delay days, delivery shortfalls, absence chance,
shop-floor yield, customer order arrivals. Each adapter has its own generator derived from the run seed, so adding one
random draw does not shift the others. The seed is stored in the run and in its report.

## 11. Control panel (frontend screens)

| Screen | Uses |
| --- | --- |
| Factory state (per day) | `/observer/factory-state` |
| Configure | Setup doors (§4) |
| States | Save / restore / list snapshots |
| Scenarios | Pick, start, see scheduled triggers |
| Clock | Next day, Play, Pause, current day, "waiting for" list |
| Triggers | Fire now / schedule |
| Timeline | `/observer/timeline` (polling) |
| Order story | `/observer/orders/{ref}` |
| Compare | Checkpoint before a trigger vs after the factory is quiet: promise dates, quantities, commitments, KPIs |
| Runs | Reports of past runs, side by side |
| Failed work | `/work/failed`, retry |

## 12. Run lifecycle and reset (DM-4)

```
CONFIGURING → READY (state saved or restored) → RUNNING ⇄ PAUSED → FINISHED → report saved → reset (restore a state)
```

- **Run report** (`simulation.run_reports`): run id, scenario, seed, settings version, start and end day, metrics
  (system design §10), final factory state, checkpoints, and the full timeline as JSON.
- **Reset:** restore a starting state (§5). Events, negotiations, queues, ledgers, audit logs and `llm_calls` of the
  finished run are cleared with it — they live on only in the report (resolves PD-O1, ID-O1, WD-O2, HD-O2, EV-O3).

## 13. Simulation doors (resolves API-O2)

`POST /simulation/reference` (K) · `POST /simulation/settings` (K) · `GET /simulation/settings` ·
`POST /simulation/states` (save) · `GET /simulation/states` · `POST /simulation/states/{name}/restore` (K) ·
`POST /simulation/clock/next-day` · `POST /simulation/clock/play` · `POST /simulation/clock/pause` ·
`GET /simulation/clock` (day, status, waiting-for) · `POST /simulation/triggers` (now or scheduled) ·
`GET /simulation/scenarios` · `POST /simulation/scenarios/{id}/start` · `POST /simulation/checkpoints` ·
`GET /simulation/runs` · `GET /simulation/runs/{id}/report` · `POST /simulation/runs/{id}/finish`.

New owner doors this doc needs (added to `backend_api.md` on 2026-10-17): `POST /inventory/setup`,
`POST /planning/setup`, `POST /warehouse/setup`, `POST /warehouse/capacity-changes` (all K).

## 14. `simulation` schema

`runs` · `settings` (versioned) · `snapshots` · `scenarios` · `clock` (one row per run) · `trigger_log` ·
`checkpoints` · `run_reports`. Queue tables follow `system_design.md` §4.2.

## 15. Open

| ID | Question |
| --- | --- |
| DM-O1 | Supplier simulation behaviour (capacity, lead-time variation, how it answers Purchasing) — Purchasing doc. |
| DM-O2 | The 100-order load test with the real model: Sales makes AI calls per conversation turn; measure first, and decide in Phase 6 whether load tests use the fake model for Sales. |
| DM-O3 | Default Factory A numbers (§4.1) are starting values; tune after S1–S8 run. |
