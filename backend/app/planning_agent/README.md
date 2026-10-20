# backend/app/planning_agent

The Planning Agent (`dev_docs/planning_agent/`): owner of the plan, the production orders and the machine-hours.
Its AI step (PL-4) is switched on by the factory setting `ai_enabled`; otherwise (and whenever the model fails or picks
something not allowed) the fixed ranking (PL-6) decides and template wording is sent.

| File | Purpose |
| --- | --- |
| `models.py` | `planning` schema: work centers and their days (capacity / committed / held machine-hours), machine-hours ledger, customer demands, options, cases (one per option being secured: its negotiation sessions), production orders (pegged to a demand or a parent production order), work items and Sales outbox (runner queues), shop-floor reports, event versions, audit log. |
| `plan.py` | One plan for a request: multi-level MRP and backward scheduling on free machine-hours and free worker-hours (`app/mrpii`), against Inventory's and HR's read modules. `options` = REQUESTED, else LATER_DATE and LESS_QUANTITY. Production starts tomorrow at the earliest (today's kits are already issued). |
| `manager.py` | Door 1 (`accept_request` → work item), `plan_request` (options; the best one is secured: machine-hours held + one negotiation per owner need, in parallel), Planning's inbox (accept offers; any counter-offer fails the option in step 5 and the next one is tried), READY / NOTHING_FEASIBLE to Sales (outbox → door 3), `OrderConfirmed` → COMMIT to every owner → `PlanCommitted` (or compensation and `PlanCommitFailed`), release at day start (`ProductionOrderReleased`), shop-floor reports (`ProductionStarted` / `ProductionCompleted`), shipments, cancellation (`OrderCancelled`: orders not yet released are cancelled and their machine-hours freed; released or started ones finish and their output goes to free stock; one `PlanRevised` lists exactly what each owner releases), `setup`, `register`. |
| `ai.py` | The AI ranking step (PL-4): the model picks one of the code-made alternatives that pass the filters and gives a one-line rationale; `check_ai_choice` falls back to the fixed ranking. Called outside any lock; logged in `observability.llm_calls`. |
| `reads.py` | Read module (IB-2): `production_orders_starting`, `production_orders`, `shipments_due` (used by Warehouse's daily routine), `get_order_plan`. |
| `api.py` | `POST /planning/requests` (door 1, `X-Door-Key` = `PLANNING_DOOR_KEY`), `POST /planning/shop-floor/reports` and `POST /planning/setup` (simulator key), `GET /planning/orders/{ref}`, `GET /planning/production-orders`. |

Sales reaches this agent when `PLANNING_CONNECTOR=real` (`sales_agent/planning.py` `RealPlanning`); the default is still
the fake Planning.

Also (step 6): worker absence repair (S5: a queued long-mode REPAIR job turns every other day into a PL-6 alternative,
ranks them (AI pick when on, else fixed), re-checks the facts and moves the missing hours through HR; `PlanAtRisk`
inside the time fence or when nothing fits), order change as a delta (S7, QA-3, RD-8 dampener), buying short items through Purchasing (PI-6; a
supply need arrives the day before production), a late supplier delivery → `PlanAtRisk` with an estimated date (S2).
Not yet: alternatives for counter-offers on a new request (a counter-offer still fails the option and the next one is
tried).

**Tests:** `backend/tests/platform/test_s1_order_flow.py` (S1), `test_replanning.py` (S5, S6, S7), `test_supply_flow.py` (S2, S3).
