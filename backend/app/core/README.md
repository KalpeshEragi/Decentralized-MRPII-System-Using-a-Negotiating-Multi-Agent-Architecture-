# backend/app/core

Cross-cutting infrastructure used by the rest of the backend. No business logic.

## Files

| File | Purpose |
| --- | --- |
| `config.py` | `Settings` (pydantic-settings) and `get_settings()` (cached). Reads environment variables, then the repository-root `.env`. |
| `database.py` | Engine (from `DATABASE_URL`, created on first use), `new_session()`, `get_db()` FastAPI dependency, `make_engine(url)`. |
| `errors.py` | HTTP errors as RFC 9457 Problem Details (API-1, API-5): `ErrorCode`, `AppError` (raised by services), the exception handlers, and `install_correlation_id` (every response carries `X-Correlation-Id`). |
| `doors.py` | `require_door_key(setting)`: the `X-Door-Key` check for machine-to-machine doors (backend_api.md §3). |
| `work_runner.py` | The shared work runner (system_design.md §4, SD-1): `QueueMixin` (standard queue shape), `enqueue`, `claim` (one item per `scope_key` at a time, in `seq` order, `FOR UPDATE SKIP LOCKED`), `run_one_short` (claim + handle + done in one transaction), `run_one_long` (lease; handler runs outside a transaction; takeover after expiry), retries with backoff 1/5/30/120 s then FAILED, `retry_failed`, and `WorkRunner` (background threads). Knows nothing about business. |
| `workers.py` | Which queues the runner serves (`register_all`), `start_workers` / `stop_workers` (called by the FastAPI lifespan). |
| `platform_base.py` | `PlatformBase`: ORM base of the new infrastructure tables (events, simulation clock/settings, observability), separate from the old `app.models.Base` so the old demo reset cannot truncate them. |
| `a2a_client.py` | A2A client used by the agents and the supplier interface: sends one C4 envelope as a JSON-RPC `SendMessage` (one data part) to `/a2a/{inventory,purchasing,supplier-interface}` at `A2A_BASE_URL` and returns the acknowledgement. `set_http_client` lets tests route it through a TestClient. |
| `logging.py` | Empty placeholder. |

## Settings

| Variable | Default | Used for |
| --- | --- | --- |
| `DATABASE_URL` | none | PostgreSQL on Neon (P0-03), SQLAlchemy URL with the psycopg driver. Without it, database routes answer `SERVICE_UNAVAILABLE`. |
| `TEST_DATABASE_URL` | none | A separate Neon database for `tests/db/`; those tests skip without it. Never point it at `DATABASE_URL`: the tests reset it. |
| `A2A_BASE_URL` | `http://localhost:8000` | Public URL written into the A2A agent cards, and the base URL the agents send A2A messages to (the endpoints are in this same app). |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama's OpenAI-compatible endpoint for the LLM client (Phase 1). |
| `OLLAMA_MODEL` | `qwen3.5:4b` | Default model (`DECISIONS.md`). |
| `SALES_PLANNING_KEY` | none | Sales door 3 key (`X-Planning-Key`). |
| `BACKGROUND_WORKERS` | `true` | Start the work runner threads with the app. Tests set `false` (`tests/conftest.py`). |
| `WORKER_POLL_SECONDS` | `0.5` | How often an idle worker looks for work. |
| `EVENT_DISPATCHER_WORKERS` | `4` | Threads delivering events. |
| `SIMULATION_DOOR_KEY` | none | `X-Door-Key` of the simulator's write doors. Unset = refused. |

Business settings of the simulated factory (safety-stock limits, horizons, time fence, ...) are not environment settings: they live in the database (`app/simulation/settings.py`, SD-2).

**Tests:** `backend/tests/core/test_config.py` (settings), `backend/tests/api/test_errors_and_a2a.py` (error format), `backend/tests/platform/test_work_runner.py` (work runner).
