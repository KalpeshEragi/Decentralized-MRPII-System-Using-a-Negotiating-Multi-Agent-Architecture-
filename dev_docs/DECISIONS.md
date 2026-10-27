# Decisions

Confirmed and open decisions for the six-agent prototype. Started fresh on 2026-10-16; the earlier 25% decision
record was removed because it described a different design (three agents, A2A, no event bus, human approval of every plan).

Claude must not silently make or change a decision listed here. Record each new decision with its date.

## Confirmed

### Carried over (still valid)

| Topic | Decision |
| --- | --- |
| Stack | FastAPI backend, PostgreSQL on Neon (SQLAlchemy + Alembic), Next.js + React frontend. Connection via `DATABASE_URL`; tests use `TEST_DATABASE_URL`. |
| LLM | One shared model via Ollama, default `qwen3.5:4b`; model name and URL are configurable. |
| Deterministic truth | BOM, MPS, MRP, quantities, reservations, capacity and constraint checks are deterministic code. |
| LLM role | Reasoning, negotiation proposals, coordination, short rationale. Output is validated before it changes anything. LLM failure → the agent's own deterministic policy decides. |
| Negotiation | Multi-factor, cooperative; goal is a mutually feasible result, not a central winner. |
| Price/cost | Price is used **only in Purchasing supplier selection** (Purchasing Contract unit price, Total Purchasing Cost); never negotiated, never in offer terms or the supplier chat; Not Registered is never zero. Elsewhere still out of scope. See `adr/ADR-002-price-in-supplier-selection.md` (accepted 2026-10-17). |
| Suppliers | Simulated, not an agent. Built: Supplier Service (read-only data) + supplier-facing test chat. |
| Priority scale | Integer 1–5, 1 = highest. |
| Dates | Planning works in whole days. |
| Git | `master` is the integration branch; short-lived branches merged by PR; Claude never commits/pushes unless asked. |
| Sales Agent | All decisions recorded in `sales_agent/1`–`4` stay valid (two doors to Planning, Sales owns customer data and confirmation, no priority from Sales, guarded confirmation, fairness rules, `sales_agent` schema). |

### From the project brief (2026-10-16)

| Topic | Decision |
| --- | --- |
| Agents | Final roster: the six agents of `adr/ADR-001.md` §2: Sales, Planning (Production Planning), Inventory, Purchasing, Warehouse, HR. **No separate Production agent** (decided 2026-10-18, closes O-9); production orders and scheduling belong to Planning (RD-3). |
| Communication | Publish–subscribe for shared events + private negotiation among relevant agents. Only agreed outcomes are published. |
| Routing | Planning owns the MPS/plan but is not the mandatory messenger for all communication. |
| Data ownership | Each agent owns its data; others read authorized data only. |
| Commitments | Only the resource owner commits its resource, atomically. No double booking. Holds may expire. |
| Constraints vs priority | Hard constraints, dependencies and priority are separate; priority never overrides a hard constraint. |
| Order states | Customer acceptance, plan/resource commitment and production start are separate states/events. |
| Autonomy | Autonomous by default; humans handle explicit exceptions (from the Sales design, confirmed with the mentor). |
| Simulation | Configure state and trigger events are separate operations; triggers never dictate agent answers. |
| Infrastructure | No Kafka/RabbitMQ/Redis or similar without explanation and approval. |
| Docs | Old `dev_docs/implementation_25%/`, old decision files and `docs/` (contracts C1–C9) removed on 2026-10-16. |

### High-level architecture (2026-10-16/17, see `architecture/high_level_architecture.md`)

| ID | Decision |
| --- | --- |
| HA-1 | One backend program, six agent modules; agents talk only through shared infrastructure. |
| HA-2 | One database, one schema per agent, shared reference schema; cross-agent reads via read functions. |
| HA-3 | Planning starts procurement (replaces the old "Inventory starts" design). Today the standalone Purchasing Agent receives Procurement Requests through its own API from a test requester (`requested_by`); Planning becomes the requester at integration. |
| HA-4 | Negotiation partners are dynamic and rule-governed: an agent negotiates only when a fact change breaks its own commitment, it cannot fix it alone, and the fix needs a resource owned by another agent (ownership map). |
| HA-5 | The problem-holder starts, the owner responds; one two-party session per owner, linked by a case id. |
| HA-6 | Follow-up negotiation depth limit 3 (starting value), then human escalation. |

### Event channel (2026-10-17, see `architecture/pubsub_event_channel.md`)

| ID | Decision |
| --- | --- |
| EV-1 | Events stored in PostgreSQL; a dispatcher in the backend polls about every 0.5 s. No Kafka/RabbitMQ/Redis/LISTEN-NOTIFY for now. |
| EV-2 | Outbox: a business change and its event are saved in one transaction by the owner. |
| EV-3 | One delivery row per (event, subscriber); handler changes and "done" saved in one transaction. |
| EV-4 | Order kept per entity per subscriber; older versions never overwrite newer state. |
| EV-5 | Events carry the changed facts plus ids and version. |
| EV-6 | Static subscription list in code, documented in the catalogue. |

### Negotiation (2026-10-17, see `architecture/negotiation.md`)

| ID | Decision |
| --- | --- |
| NG-1 | Agent-to-agent (future integration): A2A over HTTP with a DB outbox/inbox and retries, separate from events. **Built today (Purchasing ↔ supplier only):** a DB-backed Negotiation Engine (`negotiation_engine` schema) holding sessions, participants, messages, rounds and response deadlines; no business decisions. |
| NG-2 | Offers are non-binding. Future integration: the owner places an expiring hold on agreement. **Built (Purchasing):** each Leg holds supplier quantity while PENDING/AGREED/COMMITTED (counted in effective availability); FAILED/ABORTED releases it; holds don't expire by time, but an overdue Leg times out (FAILED) when next checked. |
| NG-3 | Owner queue: dependencies ready → smallest deadline slack → aging → FIFO. Urgency computed by the owner from trusted data. |
| NG-4 | Future integration: the starter sends COMMIT after a deterministic execution policy passes; the owner re-checks and commits atomically; defined exceptions go to a human. **Built (Purchasing):** a human approves (all Legs COMMITTED in one transaction) or rejects a proposed Procurement Agreement through the Purchasing API. |
| NG-5 | One open negotiation per need and resource; no parallel alternative holds. |
| NG-6 | Fixed reason-code list for REJECT and COUNTER_OFFER (`architecture/negotiation.md` §5.1); Purchasing may add its own. |

### Quantity accounting (2026-10-17, see `architecture/quantity_accounting.md`)

| ID | Decision |
| --- | --- |
| QA-1 | Every quantity change is an append-only ledger row plus a balance update, in one transaction. |
| QA-2 | Normal promises never use safety stock; Inventory alone may release part of it (limits configurable, RD-6). |
| QA-3 | Order changes are handled as deltas; existing reservations stay. |
| QA-4 | Incoming supply may be promised by date (ATP with look-ahead). |
| QA-5 | Units: whole pieces; hours rounded up to 0.25 h per step and day; space units rounded up to whole numbers; stored as exact decimals. |

### From the manufacturing research (2026-10-17, see `research/real_manufacturing_mrpii_research.md` §14)

| ID | Decision |
| --- | --- |
| RD-1 | Multi-level BOM, planned level by level from the top (low-level codes). Each made sub-assembly is netted against its own stock with its own lead time. Any depth is allowed (loops are rejected); the demo factory uses 3 levels. The existing `core.bom` / `core.bom_items` tables already support this; only the calculation (`mrpii/mrp.py`, single-level today) changes. |
| RD-2 | Capacity uses work centers, routings and calendars, in hours per day. Each routing step names a work center (setup h + run h per unit; machine hours owned by Planning) and a required skill and crew size (worker hours owned by HR). A step fits a day only if both are free. Replaces the per-product `capacity_per_day` check (`mrpii/capacity.py`). No hour-by-hour job scheduling. |
| RD-3 | Planning owns production orders (create, release, status) and publishes their events. Warehouse keeps material issue and finished-goods storage; HR keeps worker hours. Progress enters through a simulated shop-floor adapter that reports to Planning's input (started, quantity completed, machine down), like the supplier adapter for Purchasing. |
| RD-4 | Production orders: PLANNED → FIRM (on `PlanCommitted`) → RELEASED (shortly before start; material and workers committed) → STARTED (shop-floor adapter) → COMPLETED, plus CANCELLED. Replanning changes PLANNED freely, FIRM only through negotiation, RELEASED/STARTED never automatically. Time fence: one fixed setting (starting value 2 days); orders starting inside it are not changed automatically. Purchase-order states are left to the Purchasing doc. |
| RD-5 | Pegging is stored by Planning (demand ↔ supply, quantity, BOM level) and rebuilt for an item whenever Planning replans that item. Owners' reservations and commitments are the fixed links; Planning's pegs are flexible planning records that reference other agents' ids but never change their records. Used to find which orders a fact change affects. |
| RD-6 | Safety stock: keep QA-2 (normal promises never use it; Inventory alone may release part of it for an urgent order and publishes `SafetyStockBreached`), plus the ERP practice that Planning immediately plans a refill on that event. The release share (default 50 %) and the maximum deadline slack (default 2 days) are **configurable settings** of the simulated factory, not hard-coded; Inventory enforces whatever values are set. Resolves QA-O1. |
| RD-7 | Add event `ProductionOrderReleased` (publisher Planning; subscribers Warehouse, HR, Inventory). Production events stay with Planning (resolves EV-O2 together with RD-3). |
| RD-8 | Safe replanning dampener: ignore only harmless changes — date shifts that still meet the need date and are within a date threshold (default 1 day), and demand decreases within a quantity threshold (default 5 %). Shortages and due-date breaks always replan. Thresholds are measured against the committed value and are configurable factory settings. |

### Planning Agent (2026-10-17, see `planning_agent/1_planning_agent_high_level_architecture.md`)

| ID | Decision |
| --- | --- |
| PL-1 | Only the best option (first feasible of REQUESTED → LATER_DATE → LESS_QUANTITY) gets 24 h holds; other options are read-function estimates marked "subject to re-check". |
| PL-2 | Per-request planning against the committed and held state (capable-to-promise), plus net-change replanning of affected items via pegging; full regeneration only as a manual check. |
| PL-3 | Made items: one production order per customer order line (lot-for-lot). Bought items: procurement requests may combine several orders per item and release date. |
| PL-4 | The LLM ranks deterministically generated feasible alternatives and writes rationale and negotiation wording; code validates; a fixed preference order decides if the model fails. |
| PL-5 | Planning's AI requests no tools; code prepares all alternatives and facts (`planning_agent/2_planning_agent_functions.md`). |
| PL-6 | Fixed ranking in plain code when the AI fails or chooses invalidly: hard-constraint filter; protect released/started/time-fence/committed (filter), fewest FIRM changes; full quantity on target, fewest days late; fewest orders moved, days moved; least safety stock, extra worker-hours, negotiations; earliest completion; fixed key. Never cuts committed quantity or changes numbers. The AI may only choose alternatives passing the filters. |
| PL-7 | Defaults (configurable): release lead 1 day, LATER_DATE horizon 60 days, 2 best-option re-picks. |
| PB-1 | Planning code in a new `backend/app/planning_agent/` with the Sales layout; calculations in `backend/app/mrpii/`; old `agents/planning/` retired after the Phase 2 review (`planning_agent/3_planning_agent_backend.md`). |
| PB-2 | Sales ↔ Planning over HTTP doors (Planning door 1, Sales door 3), both sending through an outbox with retries. |
| PB-3 | The simulator clock publishes the infrastructure event `SimulatedDayStarted(date)`; a documented exception to "triggers never publish" (time only, no business facts). |
| PB-4 | Planning work queue: one worker per order and per item (ORDER / ITEM scope), parallel across orders and items, no nested locks. |
| PD-1 | New `planning` tables; old `mps_plans` / `mrp_requirements` untouched until the Phase 2 review, then dropped. MPS = finished-goods production orders + customer demands (`planning_agent/4_planning_agent_database.md`). |
| PD-2 | `core` stays shared reference: `items` gains `sourcing` (MAKE/BUY) and `space_per_unit`; new `core.routings`. Work centers and calendars live in `planning`. |
| PD-3 | Ranked alternatives are stored as JSON in the decision's audit record. |

### Inventory Agent (2026-10-17, see `inventory_agent/1_inventory_agent_high_level_architecture.md`)

| ID | Decision |
| --- | --- |
| IN-1 | Inventory is the quantity truth per item (on-hand, reserved, held, incoming); Warehouse is the space and movement truth. One factory site. |
| IN-2 | New event `FinishedGoodsStored` (Warehouse) raises finished-goods on-hand, like `MaterialReceived` for materials. |
| IN-3 | Inventory is a responder only; it reports problems through events and never starts negotiations. |
| IN-4 | All Inventory decisions are deterministic, including the safety-stock release (fixed rule, configured limits, minimum needed); the LLM writes wording and rationale only. |
| IF-1 | Counter-offer: full quantity at the earliest date within the shared horizon, else the most available by the needed date; urgent requests check the safety-stock release first (`inventory_agent/2_inventory_agent_functions.md`). |
| IF-2 | Uncovered reservations become AT_RISK and are reported in `StockAvailabilityChanged`; Inventory never releases them on its own. |
| IB-1 | Inventory code in a new `backend/app/inventory_agent/` (Sales layout); reusable parts of `services/inventory_service.py` move into it; old service and `agents/inventory/` retired after the Phase 2 review. |
| IB-2 | **All agents:** read functions are an in-process read-only module (`<agent>/reads.py`); it is the only thing another agent may import (checked by a test); HTTP GET doors remain for demo and team. |
| ID-1 | New `inventory` tables; old `warehouses`, `inventory_balance`, `inventory_reservations` untouched until the Phase 2 review, then dropped (`inventory_agent/4_inventory_agent_database.md`). |
| ID-2 | Holds and reservations are made for a customer demand or a production order (Planning's ids), plus the case id. |

### Warehouse Agent (2026-10-17, see `warehouse_agent/1_warehouse_agent_high_level_architecture.md`)

| ID | Decision |
| --- | --- |
| WH-1 | Future integration: Purchasing negotiates a receiving slot + material space with Warehouse before committing a supplier date. **Built 2026-10-20 (step 8):** details under "Step 8" below. |
| WH-2 | Two storage zones by item type: MATERIALS and FINISHED_GOODS; space per piece from `core.items.space_per_unit`. |
| WH-3 | Receiving and shipping capacity per day are configured numbers; Warehouse does not use HR workers. |
| WH-4 | Warehouse ships on the committed delivery date when the order's finished goods are stored and reserved. |
| WH-5 | All Warehouse decisions are deterministic; the AI writes negotiation wording only. |
| WF-1 | Issue complete kits only (min over components of floor(available ÷ quantity per unit)); report issued and missing; Planning decides (`warehouse_agent/2_warehouse_agent_functions.md`). |
| WF-2 | Receive at most the committed quantity; short deliveries posted as they are, excess refused and reported to Purchasing. |
| WB-1 | Warehouse code in a new `backend/app/warehouse_agent/` (Sales layout) (`warehouse_agent/3_warehouse_agent_backend.md`). |
| WB-2 | One writer for all Warehouse changes; reads in parallel; split by resource only if measurements show waiting. |
| WB-3 | Daily routine on `SimulatedDayStarted`: expire holds → receive → issue kits → ship → release slots of missed deliveries. |
| WD-1 | Warehouse space uses a movement profile (occupied now + dated planned arrivals and departures + holds; free space computed cumulatively like ATP); receiving and shipping use one balance row per day (`warehouse_agent/4_warehouse_agent_database.md`). |

### HR Agent (2026-10-17, see `hr_agent/1_hr_agent_high_level_architecture.md`)

| ID | Decision |
| --- | --- |
| HR-1 | HR commits hours per skill pool per day; named workers are assigned when the production order is released. |
| HR-2 | Hours count in the worker's primary skill pool; HR alone may move a worker to another skill they hold, only with free hours and never breaking a commitment. |
| HR-3 | Overtime within configurable limits (defaults 2 h per worker per day, 8 h per worker per week). |
| HR-4 | All HR decisions are deterministic; the AI writes negotiation wording only. |
| HR-5 | After an absence HR reassigns, then moves workers, then uses overtime by itself (within limits); what remains uncovered becomes AT_RISK and is reported. |
| HF-1 | HR counter-offer order: normal hours → same-day moves → overtime only if the request allows it → earliest days → most hours that fit; offers state normal, moved and overtime hours (`hr_agent/2_hr_agent_functions.md`). |
| HF-2 | Named assignment at release: fewest assigned hours that day first, primary-skill workers before moved-in workers, ties by worker id. |
| HB-1 | HR code in a new `backend/app/hr_agent/` (Sales layout) (`hr_agent/3_hr_agent_backend.md`). |
| HB-2 | One writer for all HR changes; reads in parallel; split by skill pool only if measurements show waiting. |
| HB-3 | Daily routine on `SimulatedDayStarted`: expire holds → start/end absences (with cover) → mark worked assignments and free unused hours. |
| HD-1 | One HR balance row per skill pool and day (`pool_days`), created when first needed; moves and overtime are their own records; QA-1 ledger (`hr_agent/4_hr_agent_database.md`). |
| HD-2 | Workers are simulated and fictional (code, display name, skills, calendar); no real personal data, pay or contract fields. |

### System design (2026-10-17, see `architecture/system_design.md`)

| ID | Decision |
| --- | --- |
| SD-1 | Background workers run inside the FastAPI backend; all pending work is stored in PostgreSQL (standard queue shape, safe claims, leases, retries, idempotency keys); worker code is separate from agent logic so it can move to its own process. Run exactly one backend process until the items in §4.5 are changed. |
| SD-2 | Factory settings are stored per simulation run in the database and changed through validated operations; technical settings stay in environment variables. |
| SD-3 | Every AI model call is logged in `observability.llm_calls` (no prompt text). |
| SD-4 | No cap on parallel AI calls from our side; timeouts and deterministic fallbacks; add a cap only if measurements show a need. |

### Backend API (2026-10-17, see `architecture/backend_api.md`)

| ID | Decision |
| --- | --- |
| API-1 | RFC 9457 Problem Details with our fixed codes as `code`, field problems as `errors`, plus `correlation_id`; replaces the old body everywhere. **Built (step 1) for every route of the app, Sales and Purchasing included;** Purchasing's tests were moved to it on 2026-10-20. |
| API-2 | The frontend sees changes by cursor polling. |
| API-3 | Cross-agent views come from a read-only observer API that decides and writes nothing. |
| API-4 | Old routes keep running until the Phase 2 review, then are removed with the old agents. |
| API-5 | The RFC 9457 `type` is a URN per code: `urn:mrpii:problem:<code>`. |

### Demo and simulation (2026-10-17, see `architecture/demo.md`)

| ID | Decision |
| --- | --- |
| DM-1 | Time moves by "Next day" or by "Play", which advances only when the factory is quiet. |
| DM-2 | Starting states are database snapshots: build once, save, restore exactly; owners' reconcile checks run after restore. |
| DM-3 | A scripted customer driver plays customers through the normal Sales door with a fixed, seedable rule; live chat stays possible. |
| DM-4 | On reset a run report is saved, then all run data is cleared or restored. |
| DM-5 | Every simulated day is a working day unless HR's calendar says otherwise for a worker. |
| DM-6 | Randomness is optional, only for outside-world facts, and seeded per run. |
| DM-7 | The customer driver has two modes, chosen by a setting (decided 2026-10-20): **structured** (default; product, quantity and date reach Sales as data through a simulated-customer door, so only the language-reading step is skipped and everything after is Sales' normal code; for large runs such as 100 orders, no Ollama needed) and **chat** (simulated customers type messages that Sales reads with the model; for showing one or two orders live). Refines DM-3. |

### Implementation plan (2026-10-17, see `ROADMAP.md`)

| ID | Decision |
| --- | --- |
| IMP-1 | Implementation in 8 steps (S1 end to end at step 5); the separate code-review phase is folded into the steps: each step reviews, reuses or retires the old code it replaces. |
| IMP-2 | Deterministic first: owners use template wording and Planning the fixed ranking until S1 works; then the AI steps are switched on. **Done in step 7 (2026-10-20):** a factory setting `ai_enabled` (default 0) switches on the negotiation wording (all agents, reworded in the outbox outside any lock) and Planning's AI ranking (PL-4, first used in the S5 repair). Tests and large runs keep it off; the demo turns it on. |
| IMP-3 | Purchasing is designed and built by another contributor. Status 2026-10-18: built standalone, merged; connected to the negotiation contract in step 6 (PI-1 to PI-6) instead of a FAKE stub. |
| IMP-4 | About 14 high-value tests in total. After each step: tests pass → small commits → `master` fast-forwarded locally; the developer pushes. |

### Purchasing integration (2026-10-18, approved by the developer)

The real Purchasing Agent (another contributor) is connected in step 6 instead of a FAKE stub; S2/S3 run on it.

| ID | Decision |
| --- | --- |
| PI-1 | Suppliers answer automatically: a **simulated supplier** replies in Purchasing's strict chat format by seeded rules (accept on time; a later date for a delay scenario). The human supplier chat keeps working for manual tests. Continuous simulation is the default; manual input is supported, not required. |
| PI-2 | Planning's COMMIT is the approval of a procurement (NG-4 execution policy), recorded as `decided_by = PLANNING`; the human approve/reject stays for manual tests. |
| PI-3 | A thin adapter (`purchasing_agent/a2a.py`) gives Purchasing an inbox on the negotiation layer and calls Purchasing's own functions; it notices Purchasing's state changes by a hook after a supplier reply and a check at every simulated day start (no polling loop). Purchasing's own logic is not changed. |
| PI-4 | Deliveries: Warehouse's daily routine receives committed deliveries that are due (from Purchasing's read data) and publishes `MaterialReceived`; Inventory raises stock. |
| PI-5 | WH-1 (Purchasing negotiates a receiving slot with Warehouse before committing a supplier date) is deferred to step 8. **Built in step 8 (see WH-1 below).** |
| PI-6 | Planning plans bought items: if a bought item is short, the earliest supplier date (Purchasing read data) decides feasibility, and the case gets a SUPPLY negotiation with Purchasing. Purchasing runs on the simulated clock; items map by SKU between `core.items` and `supplier_service.items`. |

### Control panel (2026-10-20, approved by the developer)

| ID | Decision |
| --- | --- |
| FE-1 | The control panel is a living 3D view of the factory in the browser: Three.js through React Three Fiber and drei, inside the existing Next.js + React frontend (new libraries, approved). |
| FE-2 | ~~3D models are built in code from simple shapes (low-poly, soft blue and white); no downloaded model packs.~~ Superseded 2026-10-27 by FE-14 (`adr/ADR-004-city-models-hybrid.md`). |
| FE-3 | Everything that moves in the scene is driven by a real event or fact (a truck arrives because `MaterialReceived` happened, a line is busy because `ProductionStarted` happened); nothing is animated for show. |
| FE-4 | A collapsible "agent conversation" sidebar shows every negotiation message as a chat between agents and every published event as a notice, filterable by order; it can be widened into a side panel or minimised. |
| FE-5 | Working product name "Decentra" on the screens (to be confirmed); the repository and docs keep their names until then. |
| FE-6 | The panel reads only the observer and simulation doors and polls one `GET /observer/live` door plus the timeline cursor (API-2, API-3). |

### Control panel redesign: the MRPII city (2026-10-26, approved by the developer)

Reference: `dev_docs/3D world (Frontend Inspiration).mp4` (local only, gitignored: 125 MB, over GitHub's limit).

| ID | Decision |
| --- | --- |
| FE-7 | Visual style: exactly the reference video's style (bright isometric-like 3D, light grey/white world, royal-blue accents, yellow forklifts, round low-poly trees, white rounded floating cards with soft shadows). The goal is a striking, eye-catching world. 3D models are of the video's quality or better (2026-10-27), and every object and corner of the city is detailed, not only the main buildings. |
| FE-8 | The world is a city of districts, one per part of the project: town square (event board where agents read the events they subscribe to), Sales, Planning, factory, warehouse and docks, HR, Purchasing with the supplier road, customer neighbourhood. A site switcher in the top bar moves the camera to a district. |
| FE-9 | Navigation as in the video: drag to pan, scroll to zoom, rotate; a strip of zoom / rotate / home buttons on the right edge. No ‹ › arrows. |
| FE-10 | The whole city is shown in full detail while exploring, not only the district in view (as in the video). Performance must be reached within this rule. |
| FE-11 | Every element (building, truck, stack, line, worker, agent) can be clicked: it is highlighted, gets a tag, and the detail panel shows its live data from the backend, updating while selected. |
| FE-12 | Live movement comes only from live backend data (extends FE-3): an animation plays when a real event arrives; the resting picture is drawn from the live state, so a reload or missed event still shows the truth. |
| FE-13 | Video elements with nothing behind them in the project are left out: search box, notifications, user avatar. The agent conversation sidebar and negotiation threads stay prominent. |
| FE-14 | Hybrid models (`adr/ADR-004-city-models-hybrid.md`): buildings are built in code from blocks, one style kit per building type, shaped after the video; vehicles, people, trees and props come from free CC0 model packs, recoloured to the video's palette. |
| FE-15 | Performance target: 60 fps on the developer's laptop at full-screen 1080p, at least 30 fps on an ordinary laptop with built-in graphics, with the whole city shown (FE-10). An fps counter can be switched on in the panel; we measure, not promise. |
| FE-16 | Each of the six agents has an office building in its colour and a character; Inventory's and Warehouse's offices are attached to the warehouse. |
| FE-17 | An agent's character walks to the Town Square when an event it subscribes to is really delivered to it (a new read-only observer read of the existing per-subscriber delivery records). Negotiation and communication between agents is shown in the city from live negotiation data. |
| FE-18 | Many events in one poll play one after another in their real order, the batch squeezed into about 15 s at most; then the picture settles on the live state. |
| FE-19 | Desktop and laptop screens only (1280 px wide and up); no phone layout. |
| FE-20 | A time-of-day mode changes the whole city's look: morning (sunrise light), afternoon (strong sun), evening (sunset), night (dark, street lights on), midnight. |

### Local databases (2026-10-20, approved by the developer)

| ID | Decision |
| --- | --- |
| DB-1 | Tests and the demo run on a local PostgreSQL 17 (portable binaries, no installer or service, outside the repository and outside OneDrive, port 5433), with separate databases `decentra_test` and `decentra_demo`. Reason: the remote Neon database made every end-to-end test take 10–20 minutes and the panel refresh about 6 s, and a demo sharing the test database is wiped by every test run. Neon stays the shared, real database; nothing in the code depends on which one is used (`DATABASE_URL`, `TEST_DATABASE_URL`). |

### Step 8: competing orders and receiving slots (2026-10-20, approved by the developer)

| ID | Decision |
| --- | --- |
| S8-1 | When every option of a new request fails to be secured (the facts changed meanwhile, typically a competing order took the resources first), Planning replans **once** from today's facts and secures the best new option (usually a later date). If nothing fits, the order ends `NOT_FEASIBLE` and the customer is told; a demand never stays open without an answer. |
| WH-1 (built) | Purchasing asks Warehouse for a `RECEIVING_SLOT` per agreed delivery before it offers supply to Planning. Warehouse offers the day or counter-offers a later one; Purchasing takes a later day only if Planning's need date holds (the simulated supplier can always deliver later: no new supplier round), else declines and tells Planning `NO_RECEIVING_CAPACITY`. A slot whose day filled up before the hold (`STALE`) is asked for again, at most twice. On Planning's COMMIT: suppliers approved → slots committed → the deliveries take their slot days → `ProcurementCommitted`. Warehouse turns the committed slot into the delivery record (no second booking). Planning reads Warehouse's free receiving when it plans bought deliveries and plans a delivery earlier when the dock is full (within the supplier's lead time). |
| WH-6 | Warehouse capacities change only through Warehouse's own input (`change_capacity`, simulator trigger `WAREHOUSE_CAPACITY`, S4); commitments already made stay; `StorageCapacityChanged` is published. |

### Quotes and agent decisions (2026-10-26, approved by the developer, see `architecture/quotes_and_agent_decisions.md`)

| ID | Decision |
| --- | --- |
| QD-1 | New message types `QUOTE_REQUEST` / `QUOTE` (non-binding, no hold), separate from the binding lifecycle. |
| QD-2 | Planning keeps its own machine-hours; no seventh agent. |
| QD-3 | Each decision is recorded in the deciding agent's own `audit_log` (`event_type = DECISION`). |
| QD-4 | Inventory may ask Purchasing directly for a replenishment quote; Purchasing decides the purchase. |
| QD-5 | AI decisions only for small runs: setting `ai_decision_max_orders` (default 10); load runs use the fallbacks. |
| QD-6 | On `STALE` Planning re-asks the same owner (at most 2 times per need) before S8-1's replan once. |
| QD-7 | At a decision point the agent thinks: reads the situation, its goals and facts, proposes its own action and parameters; code only validates (one revision allowed); the menu is a hint and the fallback. |
| QD-8 | Start with `qwen3.5:4b`; move to a larger model only if S9 shows too many refused proposals. |
| QD-9 | The agent's thinking text is shown in the UI, collapsed under its thinking card. |
| QD-10 | Local `qwen3.5:4b` for now. Measured 2026-10-26: the model's hidden thinking mode did not finish a decision in 300 s on this laptop (Ollama runs it on CPU), so the agent writes its reasoning into its JSON answer (`thinking`, shown in the UI) with the hidden mode off; ~50 s per decision call on CPU, ~34 s with the RTX 2050 (model split about 50/50 GPU/CPU), timeout 90 s. |
| QD-11 | About one model call per decision (facts in the prompt, at most one extra lookup round); one agent may decide several of its own requests in one call, never two agents in one call. A provider fallback chain (free cloud tiers) is optional and later. |

### Rule editor, event manager, replenishment (2026-10-27, approved by the developer, see `architecture/rules_events_replenishment.md`)

| ID | Decision |
| --- | --- |
| RE-1 | One rule registry (owner, label, kind, unit, bounds, default, `BUSINESS`/`SYSTEM` visibility) over the existing versioned settings table. |
| RE-2 | Per-item policies are stored by the owning agent (Inventory) through its own input, never in a shared table. |
| RE-3 | Agent guidelines: free sentences per agent, added to that agent's think-loop prompt; they never override a parameter or a hard check. |
| RE-4 | A natural-language "command" box that proposes a rule change for the user to confirm comes later, after the editor works. |
| RE-5 | Rule-like code constants (Sales offer validity, Planning re-asks, Purchasing slot retries) move into the registry one by one. |
| EM-1 | One event catalogue: per event publisher, subscribers (required/optional), payload model, description, version, status (`ACTIVE`/`DEPRECATED`/`RETIRED`); checked at publish and subscribe. |
| EM-2 | The Events screen is read-only: no runtime subscribe/unsubscribe from the UI. |
| EM-3 | A payload that does not match its model is refused in tests and development, logged loudly in the demo. |
| EM-4 | (Developer, 2026-10-27) The Events page is organised agents → events → event story (meaning, causes, each receiver's reaction taken from its handler's description, follow-ups, payload, live numbers, removal impact). An event manager assistant (shared local model) explains events and guides adding, changing or removing them, grounded in the catalogue and the deterministic checks (`impact_of_removing`, `check_new_event`); advisory only — it never changes code or the catalogue; without the model it answers from the checks. |
| RE-6 | (2026-10-27, found while building RE-1) Starting a scenario or restoring a state resets `simulation.settings`, which would silently undo the user's rules. So the user's business-rule values form a rule profile (`simulation.rule_values`) with its history (`simulation.rule_changes`); both survive restores and the profile is applied to the settings after every restore. |
| RP-1 | New event `ReplenishmentNeeded` (publisher Inventory; subscribers Planning, Purchasing). |
| RP-2 | Target stock level per item as a % of a maximum stock per item, both set in the rule editor. |
| RP-3 | Stock production orders use only free capacity and never displace customer commitments. |
| RP-4 | Decision points D9 (Inventory refill) and D10 (Planning stock production) run through the think loop. |

### One order end to end (2026-10-27, approved by the developer, see `architecture/one_order_production_simulation.md`)

| ID | Decision |
| --- | --- |
| SIM-1 | The simulated clock has hours: working hours per day (`shift_start` 08:00, `shift_hours` 8); Next hour and Next day; Play advances one simulated hour per tick (`seconds_per_sim_hour`). Day routines run at the start of the shift. |
| SIM-2 | The shop floor runs each production order's routing in batches (`batch_size` per item, default 25) on the routing's setup and run hours; a batch is done when its hours have passed on the work center. |
| SIM-3 | Each finished batch is reported to Planning; Planning publishes `ProductionBatchCompleted`; Warehouse stores the batch and Inventory counts it, so components exist as soon as they are made. |
| SIM-4 | A missing input stops an operation (`BLOCKED`, with the reason) and Planning decides what to do — built after SIM-1..3, AB-1. |
| SIM-5 | After the customer's confirmation the order runs to delivery without clicks as the clock moves. |
| DC-1 | Feasibility comes from the owners' quotes (QD-1); `app/mrpii` is a shared calculator each agent uses on its own data and never decides; no central planning engine outside Planning. |
| AB-1 | The think loop becomes a tool loop: up to 4 tool calls and 6 model calls per decision, one agent per call. |
| AB-2 | Every agent's goal names two objectives with numbers to compare: optimal (on time, full quantity, least cost and overtime) and stable (fewest changes to what is already committed). |

## Open

| ID | Question | Notes |
| --- | --- | --- |
| O-3 | Execution policy details per agent | Resolved 2026-10-17: starter policy in `negotiation.md` §8 (Planning); owners' commit re-checks in each agent's note 2. |
| O-7 | Reuse of existing code | Old Planning/Inventory/Purchasing code and the old human-approval workflow are still in `backend/`. Review one agent at a time (roadmap Phase 2). |
| O-8 | Purchasing design incl. price/cost | Resolved 2026-10-17: `adr/ADR-002-price-in-supplier-selection.md`; design in `purchasing_agent/`. |
| O-10 | City redesign: 3D models in code (FE-2) or CC0 model files? | Resolved 2026-10-27: FE-14, `adr/ADR-004-city-models-hybrid.md`. |
| O-11 | City redesign: performance target | Resolved 2026-10-27: FE-15. |
| O-12 | City redesign: data the backend does not serve yet | Partly resolved 2026-10-27: per-subscriber deliveries get a read-only observer read (FE-17). Other gaps: each becomes a small backend read or a simpler visual; the frontend never invents data. |
| O-9 | Agent roster: separate Production agent? | Resolved 2026-10-18 (developer): no separate Production agent; the roster is the six agents of `adr/ADR-001.md` §2. Legacy `production` items (schema section in `OVERALL_DATABASE_SCHEMA.md` §6, empty `app/models/production.py`) are legacy only. |
| O-10 | Quote-based feasibility and agent decisions | Resolved 2026-10-26: QD-1 to QD-11 approved (section above). Build in the order of the design doc §12. |
| O-11 | Rule editor, event manager, replenishment | Resolved 2026-10-27: RE-1..5, EM-1..3, RP-1..4 approved (section above). Build in the order of the design doc §6. |
| O-12 | One order end to end | Resolved 2026-10-27: SIM-1..5, DC-1, AB-1..2 approved (section above). Build in the order of the design doc §6. |
