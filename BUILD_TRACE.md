# Build trace: steps 1 to 6, file by file, in the order they were made

How to use: go top to bottom. For each file: read *why it was made at that moment*, open the file, read the doc named
in brackets, then write your own notes. Paths are from the repository root; `be/` = `backend/`.
A file that only changed later is listed again where it changed, with what changed.

---

## Step 1 — Foundation (commit `9b2de01`, together with step 3)

The old prototype had no shared infrastructure for six agents. Before any agent could exist we needed: a place for
new tables, a way to run background work safely, an event channel, a common error format, a simulated clock and
factory settings. Everything in step 1 is "infrastructure that never decides business outcomes".

| # | File | Why it was made at that moment | Doc |
| --- | --- | --- | --- |
| 1 | `be/app/core/config.py` (changed) | New settings first, because everything after reads them: `background_workers`, `worker_poll_seconds`, `event_dispatcher_workers`, `simulation_door_key`. | system_design §4 |
| 2 | `.env.example` (changed) | So a developer knows the two new variables (`BACKGROUND_WORKERS`, `SIMULATION_DOOR_KEY`). | — |
| 3 | `be/app/core/platform_base.py` | A separate ORM base for all new tables, so the old demo reset (which truncated `Base` tables) could never wipe events or the clock. | system_design §5 |
| 4 | `be/app/models/core.py` (changed) | Planning needs routings (work center, skill, hours) and Warehouse needs space per unit; `Item` got `sourcing` + `space_per_unit`, and a new `Routing` model (RD-2). | planning_agent/4, RD-2 |
| 5 | `be/alembic/versions/004_platform_foundation.py` | The database side of 3–4 plus the new schemas: `events` (events, deliveries), `simulation` (clock, settings), `observability` (LLM calls). | system_design §5 |
| 6 | `be/app/core/work_runner.py` | The heart of the platform: one shared queue shape (`QueueMixin`) and a runner that claims rows with `FOR UPDATE SKIP LOCKED`, one item per `scope_key` in `seq` order, short and long (lease) modes, retries 1/5/30/120 s then FAILED. Every later queue (events, negotiation, Planning work) reuses it. | system_design §4 (SD-1) |
| 7 | `be/app/events/models.py` | Tables of the event channel: `Event` (the common envelope) and `EventDelivery` (one row per subscriber = a runner queue). | pubsub_event_channel §3–5 |
| 8 | `be/app/events/channel.py` | Publish–subscribe: the static `CATALOGUE` (who publishes / who subscribes), `publish` (event + deliveries in the caller's transaction = outbox), `deliver`, `is_newer` (ignore stale versions), and the dispatcher registration. | pubsub_event_channel §6–8 |
| 9 | `be/app/core/doors.py` | Machine-to-machine doors need a key check (`X-Door-Key`); the simulator doors were the first users. | backend_api §3 |
| 10 | `be/app/core/errors.py` (changed) | API-1: switch to RFC 9457 Problem Details with our codes, plus `X-Correlation-Id` on every response. | backend_api §4 |
| 11 | `be/app/simulation/models.py` | `Clock` (the simulated day) and `Setting` (factory settings stored in the DB, SD-2). | demo §6 |
| 12 | `be/app/simulation/settings.py` | `DEFAULTS` and `setting()`: one place for every configurable factory value (hold validity, release lead, dampener ...). | demo §6, planning_agent/2 §8 |
| 13 | `be/app/simulation/clock.py` | `today()` and `next_day()`; `next_day` publishes `SimulatedDayStarted` (PB-3), which later drives hold expiry, release, kits and shipping. | demo §6 |
| 14 | `be/app/simulation/api.py` | Simulator doors for the clock and settings, protected by `require_door_key`. | backend_api §5 |
| 15 | `be/app/observability/models.py` | `LlmCall` table: CLAUDE.md asks to log AI wait/response time and failures before any resource allocator. | system_design §8 |
| 16 | `be/app/core/workers.py` | Which queues the runner serves (`register_all`) and `start_workers` / `stop_workers`. In step 1 only the event dispatcher. | system_design §4 |
| 17 | `be/app/main.py` (changed) | Start/stop the workers in the FastAPI lifespan; install correlation id; mount the simulation router. | backend_api §2 |
| 18 | `frontend/lib/api.ts` (changed) | The frontend had to read the new error body (`code`, `detail`, `errors`). | backend_api §4 |
| 19 | `be/tests/conftest.py` | Switch the background runner off in all tests, so tests run queued work themselves. | tests README |
| 20 | `be/tests/platform/conftest.py` | Test database setup (migrate, empty tables before each test) for the new platform tests. | tests README |
| 21 | `be/tests/platform/test_work_runner.py` | Proves claim, lease takeover, retry and idempotency of the runner. | ROADMAP step 1 |
| 22 | `be/tests/platform/test_event_channel.py` | Proves duplicates are ignored, stale versions dropped, per-entity order kept. | ROADMAP step 1 |

## Step 2 — Pure calculations (commit `10fa0d7`)

Planning needs exact numbers before it can negotiate. These files are pure Python (no database), so they could be
built and tested fast and alone. Planning's `plan.py` (step 5) calls them.

| # | File | Why | Doc |
| --- | --- | --- | --- |
| 23 | `be/app/mrpii/hours.py` | Capacity is in hours per day (RD-2, QA-5): rounding rules, machine-hours per step, and `schedule_backward` (latest start that fits both free machine-hours and free worker-hours). | quantity_accounting, planning_agent/2 §4.1 |
| 24 | `be/app/mrpii/atp.py` | Available-to-promise by date (QA-4): stock − promises over time, safety stock kept out. Used by Inventory to answer and by Planning to plan. | quantity_accounting §ATP |
| 25 | `be/app/mrpii/multilevel.py` | Multi-level MRP (RD-1): low-level codes, netting each level against its own stock, lot rules, parent→child demand. | research §4.2, RD-1 |
| 26 | `be/app/mrpii/ranking.py` | PL-6 fixed ranking of alternatives, and a check that an AI choice is allowed. | planning_agent/2 §6 |
| 27 | `be/tests/mrpii/test_planning_calculations.py` | The research phone example must come out exactly; ATP with a supplier delay; ranking filters and ties. | ROADMAP step 2 |

## Step 3 — Negotiation v2 (commit `9b2de01`)

Agents must make private deals (request → offer → hold → commit) without a central decider, over A2A, without
losing messages after a restart.

| # | File | Why | Doc |
| --- | --- | --- | --- |
| 28 | `be/app/negotiation/envelope.py` | First the message shape everyone agrees on: `Terms` (no price/priority), `Hold`, `Envelope`, message types, resource types, reason codes (NG-6). | negotiation §3–5 |
| 29 | `be/app/negotiation/state.py` | The state machine (`apply`): which message is allowed when, max 3 rounds, who has the turn. Pure, so it is easy to test. | negotiation §4 |
| 30 | `be/app/negotiation/models.py` | `Session` (one negotiation), `Message` (the receiver's inbox = runner queue), `Outbox` (sending = runner queue). | negotiation §7 |
| 31 | `be/alembic/versions/005_negotiation_v2.py` | Tables of 30, plus the NG-5 unique index (one open negotiation per need). | negotiation §7 |
| 32 | `be/app/negotiation/layer.py` | The layer agents use: `send` (to outbox), `receive` (validate, store, acknowledge), `reply_to`, inbox registration per agent, outbox sender. Routes and stores, never decides. | negotiation §6–7 (NG-1) |
| 33 | `be/app/negotiation/transport.py` | The HTTP call (JSON-RPC `SendMessage`) used by the outbox sender. | negotiation §7 |
| 34 | `be/app/negotiation/a2a_endpoints.py` | The A2A endpoints `/a2a/<agent>` with agent cards: store and acknowledge only. | negotiation §7, backend_api §6 |
| 35 | `be/tests/platform/test_negotiation.py` | Request → offer → hold → commit end to end; duplicate; stale. | ROADMAP step 3 |
| 36 | `be/tests/api/test_errors_and_a2a.py` (changed) | Error format and A2A refusals without a database. | backend_api §4 |

## Step 4 — Retire the old prototype, then the owner agents (commits `88f23c0` … `910b93e`)

The old three-agent code used the same paths (`/a2a/inventory`) and old tables; keeping it would clash with the new
agents. So the retirement came first, then the shared helpers the owners need, then each owner with its test.

| # | File | Why | Doc |
| --- | --- | --- | --- |
| 37 | `be/tests/sales_agent/db/test_manager.py` (changed, `88f23c0`) | A Sales test read rows in no fixed order and failed at random; fixed before building on top. | — |
| 38 | Deleted: `be/app/agents`, `app/api`, `app/services`, `app/data`, `app/schemas`, `be/scripts`, old `mrpii` and `negotiation` modules, old models and tests (`8ef0404`) | IMP-1: Phase 2 retirement folded into step 4. Changed with it: `app/models/__init__.py`, `base.py`, `core.py`, `llm/reasoning.py`, two tests. | ROADMAP step 5 row, IMP-1 |
| 39 | `be/alembic/versions/006_retire_old_tables.py` | Drops the old tables and schemas (not reversible). | — |
| 40 | `be/app/core/owner_tables.py` | Every owner keeps a ledger + balance in one transaction (QA-1) and an audit log: `LedgerMixin`, `AuditMixin`, `LedgerWriter` (idempotent by source id). Written once, used by all four owners. | quantity_accounting §2 |
| 41 | `be/app/core/http_doors.py` | Agents call each other's doors over HTTP (Planning → Sales door 3, Sales → Planning door 1). | backend_api §5 |
| 42 | `be/app/inventory_agent/models.py` | Inventory first, because every plan needs stock: balances, ledger, holds, reservations (for a demand or a production order, ID-2), incoming receipts. | inventory_agent/4 |
| 43 | `be/app/inventory_agent/manager.py` | Answers stock requests (IF-1, with RD-6 safety-stock release), places holds, commits reservations, reacts to issue / storage / shipment / plan revision. | inventory_agent/2–3 |
| 44 | `be/app/inventory_agent/reads.py` | The only thing other agents may import (IB-2): position, ATP by date, reservations of an order. | inventory_agent/3, IB-2 |
| 45 | `be/app/inventory_agent/api.py` | Setup door (simulator) and read views. | inventory_agent/3 |
| 46 | `be/tests/platform/test_inventory_agent.py` | Your 5000 → 3000 example with an exact ledger; no double booking. | quantity_accounting §example |
| 47 | `be/app/hr_agent/models.py` | Worker-hours per skill and day: workers, absences, pool days, moves, overtime, holds, commitments, named assignments, ledger. | hr_agent/4 |
| 48 | `be/app/hr_agent/manager.py` | Capacity, allocation (normal → move → overtime), answer (HF-1), holds/commits, named assignment at release (HF-2), absence cover (HR-5). | hr_agent/2–3 |
| 49 | `be/app/hr_agent/reads.py`, `api.py` | Read module (free hours, assignments, commitments) and doors (setup, absences). | hr_agent/3 |
| 50 | `be/tests/platform/test_hr_agent.py` | Absence covered by moving a worker, then overtime, then AT_RISK. | ROADMAP step 4 |
| 51 | `be/app/warehouse_agent/models.py` | Space by movement profile (WD-1): zones, capacities, holds, space commitments, planned movements, ledger. | warehouse_agent/4 |
| 52 | `be/app/warehouse_agent/manager.py` | Free space/receiving, answer, holds/commits, store finished goods, issue complete kits (WF-1), ship. (Daily routine added in step 5.) | warehouse_agent/2–3 |
| 53 | `be/app/warehouse_agent/reads.py`, `api.py` | Read module and doors. | warehouse_agent/3 |
| 54 | `be/alembic/versions/007_owner_agents.py` | Creates the three owners' tables from their models. | — |

## Step 5 — Planning + Sales → S1 end to end (commits `c336401` … `f34a659`)

With owners able to hold and commit, the starter could be built: Planning plans a request, negotiates with every
owner, commits on confirmation and runs production. Then the pieces were wired together and S1 proved the whole flow.

| # | File | Why | Doc |
| --- | --- | --- | --- |
| 55 | `be/app/negotiation/models.py`, `layer.py` (changed, `c336401`) | Building Planning showed one case may need the same chip for two production orders; NG-5 says "per need", so the need (`order_id`) joined the key. | negotiation §5 (NG-5) |
| 56 | `be/app/planning_agent/models.py` | Planning's own data: work centers and machine-hours, customer demands, options, cases (one per option being secured), production orders (pegged), work queue, Sales outbox, shop-floor reports. | planning_agent/4 |
| 57 | `be/app/planning_agent/plan.py` | Turns a request into a plan using step 2: MRP + backward scheduling against Inventory and HR read modules; then the options REQUESTED / LATER_DATE / LESS_QUANTITY. | planning_agent/2 §3–4 |
| 58 | `be/app/sales_agent/reads.py` | Planning must map a Sales product to a factory item; IB-2 says only through Sales' read module. | IB-2 |
| 59 | `be/app/planning_agent/manager.py` | The flow: door 1 → work item → options → secure the best (hold machine-hours + one negotiation per owner need) → READY to Sales → `OrderConfirmed` → COMMIT → `PlanCommitted` → release → shop floor → shipment. | planning_agent/1–3 |
| 60 | `be/app/planning_agent/reads.py` | Warehouse's daily routine needs "which orders start today" and "what ships today". | planning_agent/2 §4.4 |
| 61 | `be/app/planning_agent/api.py` | Door 1 (requests), door 2 (shop floor), setup, views. | backend_api §5 |
| 62 | `be/alembic/versions/008_planning_agent.py` | Planning tables + the NG-5 index change of 55. | — |
| 63 | `be/app/warehouse_agent/manager.py`, `inventory_agent/manager.py` (changed) | Warehouse `run_day` (expire → kits → ship); produced goods pegged: stored goods are reserved for what they were made for. | warehouse_agent/2 (WB-3), RD-5 |
| 64 | `be/app/sales_agent/planning.py`, `api.py`, `core/config.py`, `.env.example` (changed, `080d695`) | `RealPlanning` connector behind `PLANNING_CONNECTOR` (default fake), and Planning's door key. | PB-O1 |
| 65 | `be/app/main.py`, `core/workers.py`, `events/channel.py` (changed, `1a7765a`) | Wire all agents into the app and the runner; catalogue fixes found while wiring. | system_design §4 |
| 66 | `be/tests/platform/test_s1_order_flow.py` | S1: request → options → confirmation → commitment → production → shipment, exact stock at the end. | demo §5 (S1) |

Then the Purchasing branch was merged (`50de573`): their migrations became `009`/`010`; their code is in
`be/app/purchasing_agent/`, `supplier_service/`, `negotiation_engine/` (read their own READMEs).

## Step 6 — Replanning (in progress, not committed yet)

| # | File | Why | Doc |
| --- | --- | --- | --- |
| 67 | `be/tests/platform/conftest.py` (changed) | S1 took 30+ minutes on the remote database; the pump now asks all queues for work in one query and drains only busy ones, and fails if anything is left unfinished. S1: under 10 minutes. | tests README |
| 68 | `be/tests/platform/phone_factory.py` | S1 and the step-6 tests need the same small factory and the same "play Sales / play the shop floor" helpers. | — |
| 69 | `be/app/planning_agent/manager.py` (changed) | S6 cancellation: cancel orders not yet released, free machine-hours, publish one `PlanRevised` listing exactly what each owner releases. | planning_agent/2 §3 method 8, RD-4 |
| 70 | `be/app/hr_agent/manager.py`, `warehouse_agent/manager.py` (changed) | They must release exactly the listed commitments on `PlanRevised` (Inventory already did). | hr_agent/3, warehouse_agent/3 |
| 71 | `be/tests/platform/test_replanning.py` | Cancellation releases exactly; released work goes on and its output is free stock. | ROADMAP step 6 |

Still to come in step 6: S5 worker-absence repair, S7 order change, Purchasing stub with S2/S3.
