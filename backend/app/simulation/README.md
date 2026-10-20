# backend/app/simulation

The simulator (`dev_docs/architecture/demo.md`): infrastructure, not an agent. It moves simulated time, plays the
outside world (shop floor, suppliers) and fires triggers; agents decide every response. Built so far: clock, settings,
the day cycle with Play / Pause, the simulated shop floor, suppliers and customers (structured or chat), triggers, saved starting states.
Scenarios and run reports come next.

| File | Purpose |
| --- | --- |
| `models.py` | `Clock` (one row: current simulated day, status: PAUSED / PLAYING), `Setting` (versioned factory settings) and `TriggerLog` (every trigger, fired now or scheduled for a day; migration `012`) in the `simulation` schema. |
| `clock.py` | `get_clock` (created on first use at `simulation_start_day`), `today`, `next_day` (locks the clock row, advances one day, publishes `SimulatedDayStarted` in the same transaction). |
| `settings.py` | `DEFAULTS` (every factory setting with its documented default and decision id), `read_settings` (values + version), `setting`, `update_settings` (validated; one new version per change). |
| `suppliers.py` | Simulated suppliers (PI-1): answer Purchasing's offers automatically through the supplier chat path, in Purchasing's strict format; deterministic (accept what they can meet, else counter with their available quantity by their earliest date). Work item `SUPPLIER_TURN` of the Purchasing adapter's queue. Setting `simulated_suppliers` (1 on, 0 = a person answers). |
| `customers.py` | Customer driver, structured mode (DM-3, DM-7): `customer_orders_per_day` new requests each morning (seeded per day, DM-6), then the fixed decision rule on Planning's answers (accept REQUESTED, else LATER_DATE up to `customer_later_date_max_days`, else decline). Only through Sales' doors (HTTP). Off by default (0 orders a day). Chat mode (`customer_chat_mode` 1): customers write test-chat messages that Sales reads with the model, then answer with a letter and "yes". |
| `shop_floor.py` | Simulated shop floor (RD-3): released orders start on their start day and complete their whole quantity on their end day, reported to Planning's shop-floor input. Deterministic. |
| `runner.py` | The day cycle: advance the clock and fire the triggers due → customers' requests → wait until quiet → customers decide → wait until quiet (no PENDING/RUNNING work in any queue) → shop floor → wait until quiet. A day that does not become quiet within `quiet_limit_seconds` pauses Play and reports what is waiting. Play / Pause (one background thread; the clock row holds the status). |
| `triggers.py` | Triggers through the owner's input (demo.md §7): `WORKER_ABSENT` (HR), `SUPPLIER_DELAY` (Purchasing). Now or scheduled; logged; an owner's refusal is recorded as FAILED. |
| `states.py` | Starting states (DM-2): `save` (only when quiet; every run table as JSON, failed work not saved), `restore` (one transaction: empty, load, counters, clock paused) and every owner's `reconcile` check. |
| `api.py` | Doors: `GET /simulation/clock` (day, status, what is waiting), `POST /simulation/clock/next-day` (one day cycle in the background), `/clock/play`, `/clock/pause`, `GET`/`POST /simulation/settings` (K), `POST /simulation/triggers` (K, now or `day`), `GET /simulation/triggers`, `POST /simulation/states` (K, save), `GET /simulation/states`, `POST /simulation/states/{name}/restore` (K). Setting `ai_enabled` switches the agents' AI steps on. |

**Tests:** `test_customer_driver.py` (a simulated customer's order from request to shipment by the simulator alone); the day cycle and shop floor run in every end-to-end test (`tests/platform/phone_factory.py` `run_day`); triggers in the S2 test (`test_supply_flow.py`).
