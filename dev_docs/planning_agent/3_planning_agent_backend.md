# Planning Agent: Backend Design

**Status:** APPROVED by the developer (2026-10-17). Nothing new here is implemented.
**Stack:** FastAPI backend, PostgreSQL on Neon (as decided).
**Related:** `1_planning_agent_high_level_architecture.md`, `2_planning_agent_functions.md`,
`../architecture/pubsub_event_channel.md`, `../architecture/negotiation.md` §10, `../sales_agent/3_sales_agent_backend.md`.

## A. Layers

| # | Layer | Job |
| --- | --- | --- |
| 1 | API doors | Receive Sales requests, shop-floor reports and A2A negotiation messages; answer "received" fast |
| 2 | Planning manager | Work queue; one worker per customer order; runs every step of a work item |
| 3 | Planning AI | `ai_rank_alternatives` only. Saves nothing, sends nothing, uses no tools (PL-5) |
| 4 | Rules | `check_ai_ranking`, fixed ranking (PL-6), execution policy (NG-4), time fence, dampener, Sales-result checks |
| 5 | Calculation library | `backend/app/mrpii/` (pure, no database): netting, multi-level MRP, loads per day, schedule, options, alternatives |
| 6 | Data access | The only code that reads and writes the `planning` schema |
| 7 | Connectors | Sales connector, negotiation client (A2A), other agents' read functions, AI model, event publisher — every outgoing write through an outbox |
| Side | Audit, settings, errors | |

Rule: the AI talks only to the manager. Only the data-access layer touches the `planning` schema. Planning never
reads other agents' tables; it uses their read functions.

**Folder (PB-1):** `backend/app/planning_agent/`, same layout as `sales_agent/` (`manager.py`, `rules.py`, `agent.py`,
`prompts.py`, `data_access.py`, `connectors.py`, `api.py`, `models.py`, `views.py`). The pure calculations stay in
`backend/app/mrpii/`, extended for RD-1/RD-2. The old `agents/planning/` is reviewed in Phase 2 and retired, not edited.

## B. API doors

| # | Door | Who | Takes | Returns |
| --- | --- | --- | --- | --- |
| 1 | `POST /planning/requests` | Sales (shared key) | Sales request (§E) | `202` received / duplicate (by `request_ref`) |
| 2 | `POST /planning/shop-floor/reports` | Simulated shop-floor adapter | Report (§E) | `202` received / duplicate (by `report_id`) |
| 3 | `/a2a/planning` | Other agents (A2A, NG-1) | Negotiation envelope | Acknowledgement (store and acknowledge) |
| 4 | `GET /planning/orders/{order_ref}` | Team, demo, read function | — | Plan status, dates, quantities, options, held flags |
| 5 | `GET /planning/production-orders?status=` | Team, demo | — | Production orders and states |
| 6 | `GET /planning/orders/{order_ref}/pegging` | Team, demo | — | Pegs across BOM levels |
| 7 | `POST /planning/maintenance/regenerate-check` | Us | — | Full regeneration **compared** with the stored plan; reports differences, changes nothing (PL-2) |

Events arrive through the event dispatcher, not through doors. Errors use the backend's existing error format;
duplicates are answered "already received", not as errors (same rule as Sales).

## C. Functions (plumbing)

**Manager:** `accept_request` (dedupe, save, enqueue, answer fast); `enqueue_work`; `process_work` (claim the next
item for an order that no other worker holds); `plan_request`; `handle_event` (one handler per subscribed type; quick
and deterministic, only records work items, `pubsub_event_channel.md` §6.3); `handle_negotiation_message`;
`commit_order`; `release_due_orders` (on `SimulatedDayStarted`); `record_shop_floor_report`; `replan_affected`;
`escalate`.

**Rules:** `check_ai_ranking`; `rank_alternatives` (PL-6); `execution_policy_ok`; `inside_time_fence`;
`is_dampened`; `check_result_for_sales` (every option has a valid kind, quantity > 0, date not before the order date,
held flag set correctly).

**Connectors:** `sales_connector` (outbox → Sales door 3); `negotiation_client` (outbox → A2A); read clients
(`atp_by_date`, `supplier_options`, `free_space`, `free_receiving`, `free_worker_hours`); `ai_connector` (shared
Ollama model, timeout, one retry); `publish` (event outbox).

## D. Flows

### Flow 1: new request from Sales
Door 1 → `accept_request` → work item (order scope) → `plan_request`: MPS → MRP level by level → loads per day →
options → alternatives for the best option → AI ranks (or fixed ranking) → negotiations opened in parallel → answer
`WORKING` to Sales if it takes long → when the best option's sessions agree (holds placed) → result `READY` with held
and unheld options → Sales door 3. If a negotiation fails: next best option (at most 2 re-picks), else
`NOTHING_FEASIBLE` / `NEEDS_STAFF`.

### Flow 2: negotiation message arrives
Door 3 stores and acknowledges → the inbox dispatcher runs `handle_negotiation_message` → the order's worker updates
the case (agreement, counter-offer, rejection, expiry) and decides the next step with code-computed terms.

### Flow 3: customer confirms
Event `OrderConfirmed` → work item → held option: `execution_policy_ok` → `COMMIT` to every linked session → all
owners committed → production orders FIRM → `PlanCommitted`. Unheld option: negotiate now, then commit. Any failure →
`PlanCommitFailed` (with reason) and compensation (release what was committed, negotiation.md §8).

### Flow 4: a simulated day starts
Event `SimulatedDayStarted(date)` → `release_due_orders`: FIRM orders whose start − release lead ≤ date → RELEASED →
`ProductionOrderReleased`. Same event triggers re-checks of open cases that waited for a date.

### Flow 5: shop-floor report
Door 2 → `record_shop_floor_report`: STARTED → `ProductionStarted`; quantity completed → `ProductionCompleted`
(full or partial); machine down → capacity of that work center reduced for the given days → Flow 6.

### Flow 6: a fact changes (net change)
Subscribed event → `handle_event` records an item-scope work item → `replan_affected`: pegs → affected orders →
dampener → for each affected order an order-scope work item: PLANNED replanned freely; FIRM only via negotiation;
RELEASED/STARTED and time fence untouched → alternatives → ranking → negotiations → `PlanRevised` / `PlanAtRisk`.

### Flow 7: change or cancellation
`OrderChangeRequested` → delta handling (QA-3) as a new target through Flow 6. `OrderCancelled` → PLANNED/FIRM
production orders cancelled, procurement demand lines removed, owners release through `PlanRevised`; released orders
are reported, not undone automatically.

## E. Data shapes (bold = required)

- **Sales request** (existing Sales contract, `sales_agent/planning.py` `build_request`): **request ref**, **inquiry
  id**, **customer id**, **product**, **quantity** (> 0), **requested date**, **order date**; customer context
  (informational only — Planning never uses it for feasibility, capacity, supply or priority; Sales fairness rule).
- **Planning result** (existing Sales contract): **request ref**, **status** (READY, WORKING, NOTHING_FEASIBLE,
  NEEDS_STAFF), options, reason code, time. **Change needed (PL-O1):** each option gets **held** (yes/no).
- **Option:** **option id**, **kind**, **quantity**, **delivery date**, **valid until**, **held**, reason code.
- **Shop-floor report:** **report id**, **production order id**, **kind** (STARTED, QUANTITY_COMPLETED, MACHINE_DOWN),
  quantity, work center, days affected, **time**.
- **Work item:** id, **scope** (ORDER or ITEM), **ref** (order or item id), **kind**, payload, status (PENDING, DONE,
  FAILED), attempts, next attempt.
- **`SimulatedDayStarted`** (infrastructure event): **date**.

## F. Concurrency (PB-4)

- Work items are **ORDER**-scoped (an order's plan, production orders, negotiations) or **ITEM**-scoped (pegs and the
  grouped procurement request of one item, PL-3).
- One worker at a time per order and per item (a lock on the work-item ref); different orders and items run in
  parallel (starting value: 4 workers).
- An order work item never takes an item lock: it writes its own demand lines and enqueues an item work item, so no
  two locks are ever held together (no deadlocks).
- AI calls happen outside database transactions; the AI queue is the shared model's, not Planning's work queue.

## G. Errors and tests

| Situation | What we do | Test |
| --- | --- | --- |
| Same Sales request twice | "Already received", nothing repeated | Send twice, one result |
| Wrong key on door 1 | Not allowed | Missing / wrong key |
| AI down, slow or invalid choice | Fixed ranking (PL-6) | Fake AI fails / picks a filtered alternative |
| A wording number not in the chosen alternative | Retry once, then a template | Fake AI invents a date |
| Owner refuses the best option | Next option, up to 2 re-picks, then NOTHING_FEASIBLE | Fake owner rejects |
| Commit fails at one owner | `PlanCommitFailed`, compensation, Sales informed | One owner refuses COMMIT |
| Event about an old version | Ignored (stale) | Replay an older event |
| Supplier delay inside the time fence | No automatic change; `PlanAtRisk` / escalation | Delay for an order starting tomorrow |
| Harmless change | Dampened, nothing published | Delay that still meets the need date |
| Sending to Sales fails | Outbox retries | Sales door down, then up |
| Restart mid-work | Work item claimed again; outboxes resume | Kill and restart in a test |

Test set: the research report's phone example end to end with fake owners and a fake AI; the six disruptions;
two orders competing for one item; the fairness test (same request with different customer context → same result).

## H. Decisions recorded

| ID | Decision |
| --- | --- |
| PB-1 | New folder `backend/app/planning_agent/` with the Sales layout; calculations in `backend/app/mrpii/`; old `agents/planning/` retired after the Phase 2 review. |
| PB-2 | Sales ↔ Planning over HTTP doors (Planning door 1, Sales door 3), both sending through an outbox with retries. |
| PB-3 | The simulator's clock publishes the infrastructure event `SimulatedDayStarted(date)`; agents subscribe if they need time. A documented exception to "triggers never publish": time only, no business facts. |
| PB-4 | Work queue with one worker per order and per item (ORDER / ITEM scope), parallel across orders and items, no nested locks. |

## I. Open or later

| ID | Item |
| --- | --- |
| PB-O1 | Sales-side changes for integration: `held` on options, the confirmation notice published as `OrderConfirmed`, the real Planning connector (contract first). |
| PB-O2 | Resolved 2026-10-17: 30 s, configurable (`system_design.md` §7). |
| PB-O3 | Number of Planning workers (starting value 4; measure in Phase 6). |
| PB-O4 | Done 2026-10-17: `SimulatedDayStarted` added to `pubsub_event_channel.md` (envelope, catalogue, §9). |
