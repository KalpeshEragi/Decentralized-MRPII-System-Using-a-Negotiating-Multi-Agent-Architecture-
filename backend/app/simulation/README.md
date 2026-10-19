# backend/app/simulation

The simulator (`dev_docs/architecture/demo.md`): infrastructure, not an agent. It moves simulated time, plays the
outside world (shop floor, suppliers) and fires triggers; agents decide every response. Built so far (step 7a): clock,
settings, the day cycle with Play / Pause, the simulated shop floor and suppliers, triggers. Starting states,
scenarios, the customer driver and runs come next.

| File | Purpose |
| --- | --- |
| `models.py` | `Clock` (one row: current simulated day, status: PAUSED / PLAYING), `Setting` (versioned factory settings) and `TriggerLog` (every trigger, fired now or scheduled for a day; migration `012`) in the `simulation` schema. |
| `clock.py` | `get_clock` (created on first use at `simulation_start_day`), `today`, `next_day` (locks the clock row, advances one day, publishes `SimulatedDayStarted` in the same transaction). |
| `settings.py` | `DEFAULTS` (every factory setting with its documented default and decision id), `read_settings` (values + version), `setting`, `update_settings` (validated; one new version per change). |
| `suppliers.py` | Simulated suppliers (PI-1): answer Purchasing's offers automatically through the supplier chat path, in Purchasing's strict format; deterministic (accept what they can meet, else counter with their available quantity by their earliest date). Work item `SUPPLIER_TURN` of the Purchasing adapter's queue. Setting `simulated_suppliers` (1 on, 0 = a person answers). |
| `shop_floor.py` | Simulated shop floor (RD-3): released orders start on their start day and complete their whole quantity on their end day, reported to Planning's shop-floor input. Deterministic. |
| `runner.py` | The day cycle: advance the clock and fire the triggers due → wait until quiet (no PENDING/RUNNING work in any queue) → shop floor → wait until quiet. A day that does not become quiet within `quiet_limit_seconds` pauses Play and reports what is waiting. Play / Pause (one background thread; the clock row holds the status). |
| `triggers.py` | Triggers through the owner's input (demo.md §7): `WORKER_ABSENT` (HR), `SUPPLIER_DELAY` (Purchasing). Now or scheduled; logged; an owner's refusal is recorded as FAILED. |
| `api.py` | Doors: `GET /simulation/clock` (day, status, what is waiting), `POST /simulation/clock/next-day` (one day cycle in the background), `/clock/play`, `/clock/pause`, `GET`/`POST /simulation/settings` (K), `POST /simulation/triggers` (K, now or `day`), `GET /simulation/triggers`. |

**Tests:** the day cycle and shop floor run in every end-to-end test (`tests/platform/phone_factory.py` `run_day`); triggers in the S2 test (`test_supply_flow.py`).
