# backend/app/simulation

The simulator (`dev_docs/architecture/demo.md`): infrastructure, not an agent. Step 1 has the clock and the factory
settings; states, scenarios, triggers, Play/Pause and runs come in step 7.

| File | Purpose |
| --- | --- |
| `models.py` | `Clock` (one row: current simulated day, status) and `Setting` (versioned factory settings) in the `simulation` schema. |
| `clock.py` | `get_clock` (created on first use at `simulation_start_day`), `today`, `next_day` (locks the clock row, advances one day, publishes `SimulatedDayStarted` in the same transaction). |
| `settings.py` | `DEFAULTS` (every factory setting with its documented default and decision id), `read_settings` (values + version), `setting`, `update_settings` (validated; one new version per change). |
| `api.py` | Doors: `GET /simulation/clock`, `POST /simulation/clock/next-day`, `GET /simulation/settings`, `POST /simulation/settings` (`X-Door-Key` = `SIMULATION_DOOR_KEY`). |

The old `POST /simulation/reset` (`app/api/simulation.py`) and the old tables `simulation_scenarios` /
`simulation_events` (`app/models/simulation.py`) belong to the old design and are retired in Phase 2.

**Tests:** the clock is exercised by `backend/tests/platform/test_event_channel.py`.
