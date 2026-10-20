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
| WH-1 | Future integration: Purchasing negotiates a receiving slot + material space with Warehouse before committing a supplier date. **Not built:** Purchasing has no Warehouse step yet. |
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
| API-1 | Future target: RFC 9457 Problem Details with our fixed codes as `code`, field problems as `errors`, plus `correlation_id`; replaces the old body everywhere (incl. Sales) during integration. **Today:** Sales and Purchasing return the C5 body `{"error": {code, message, details}}`. |
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
| PI-5 | WH-1 (Purchasing negotiates a receiving slot with Warehouse before committing a supplier date) is deferred to step 8. |
| PI-6 | Planning plans bought items: if a bought item is short, the earliest supplier date (Purchasing read data) decides feasibility, and the case gets a SUPPLY negotiation with Purchasing. Purchasing runs on the simulated clock; items map by SKU between `core.items` and `supplier_service.items`. |

### Control panel (2026-10-20, approved by the developer)

| ID | Decision |
| --- | --- |
| FE-1 | The control panel is a living 3D view of the factory in the browser: Three.js through React Three Fiber and drei, inside the existing Next.js + React frontend (new libraries, approved). |
| FE-2 | 3D models are built in code from simple shapes (low-poly, soft blue and white); no downloaded model packs. |
| FE-3 | Everything that moves in the scene is driven by a real event or fact (a truck arrives because `MaterialReceived` happened, a line is busy because `ProductionStarted` happened); nothing is animated for show. |
| FE-4 | A collapsible "agent conversation" sidebar shows every negotiation message as a chat between agents and every published event as a notice, filterable by order; it can be widened into a side panel or minimised. |
| FE-5 | Working product name "Decentra" on the screens (to be confirmed); the repository and docs keep their names until then. |
| FE-6 | The panel reads only the observer and simulation doors and polls one `GET /observer/live` door plus the timeline cursor (API-2, API-3). |

## Open

| ID | Question | Notes |
| --- | --- | --- |
| O-3 | Execution policy details per agent | Resolved 2026-10-17: starter policy in `negotiation.md` §8 (Planning); owners' commit re-checks in each agent's note 2. |
| O-7 | Reuse of existing code | Old Planning/Inventory/Purchasing code and the old human-approval workflow are still in `backend/`. Review one agent at a time (roadmap Phase 2). |
| O-8 | Purchasing design incl. price/cost | Resolved 2026-10-17: `adr/ADR-002-price-in-supplier-selection.md`; design in `purchasing_agent/`. |
| O-9 | Agent roster: separate Production agent? | Resolved 2026-10-18 (developer): no separate Production agent; the roster is the six agents of `adr/ADR-001.md` §2. Legacy `production` items (schema section in `OVERALL_DATABASE_SCHEMA.md` §6, empty `app/models/production.py`) are legacy only. |
