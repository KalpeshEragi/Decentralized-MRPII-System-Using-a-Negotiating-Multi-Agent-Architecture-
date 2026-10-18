# backend/app/core

Cross-cutting infrastructure used by the rest of the backend. No business logic.

## Files

| File | Purpose |
| --- | --- |
| `config.py` | `Settings` (pydantic-settings) and `get_settings()` (cached). Reads environment variables, then the repository-root `.env`. |
| `database.py` | Engine (from `DATABASE_URL`, created on first use), `new_session()`, `get_db()` FastAPI dependency, `make_engine(url)`. |
| `errors.py` | C5 error format: `ErrorCode`, `AppError` (raised by services) and the exception handlers installed by `main.py`. |
| `a2a_client.py` | A2A client used by the legacy agents: sends one C4 envelope as a JSON-RPC `SendMessage` (one data part) to `/a2a/{inventory,purchasing}` at `A2A_BASE_URL` and returns the acknowledgement. `set_http_client` lets tests route it through a TestClient. |
| `logging.py` | Empty placeholder. |

## Settings

| Variable | Default | Used for |
| --- | --- | --- |
| `DATABASE_URL` | none | PostgreSQL on Neon (P0-03), SQLAlchemy URL with the psycopg driver. Without it, database routes answer `SERVICE_UNAVAILABLE`. |
| `TEST_DATABASE_URL` | none | A separate Neon database for `tests/db/`; those tests skip without it. Never point it at `DATABASE_URL`: the tests reset it. |
| `A2A_BASE_URL` | `http://localhost:8000` | Public URL written into the A2A agent cards, and the base URL the agents send A2A messages to (the endpoints are in this same app). |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama's OpenAI-compatible endpoint for the LLM client (Phase 1). |
| `OLLAMA_MODEL` | `qwen3.5:4b` | Default model (`DECISIONS.md`). |

Business limits such as 3 negotiation rounds and 2 planning attempts are decisions, not environment settings.

**Tests:** `backend/tests/core/test_config.py` (settings), `backend/tests/api/test_errors_and_a2a.py` (error format).
