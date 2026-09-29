# backend/app/core

Cross-cutting infrastructure used by the rest of the backend. No business logic.

## Files

| File | Purpose |
| --- | --- |
| `config.py` | `Settings` (pydantic-settings) and `get_settings()` (cached). Reads environment variables, then the repository-root `.env`. |
| `logging.py` | Empty placeholder. |

## Settings

| Variable | Default | Used for |
| --- | --- | --- |
| `DATABASE_URL` | none | PostgreSQL on Neon (P0-03), SQLAlchemy URL with the psycopg driver. Used from Phase 2. |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama's OpenAI-compatible endpoint for the LLM client (Phase 1). |
| `OLLAMA_MODEL` | `qwen3.5:4b` | Default model (`DECISIONS.md`). |

Business limits such as 3 negotiation rounds and 2 planning attempts are decisions, not environment settings.

The API error format (contract C5, `docs/contracts/C5_errors.md`) will be implemented here when the API exists.

**Tests:** `backend/tests/core/test_config.py`.
