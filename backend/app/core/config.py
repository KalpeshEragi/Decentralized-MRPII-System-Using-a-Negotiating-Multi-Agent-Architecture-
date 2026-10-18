"""Application settings, read from environment variables or the repository-root `.env` file."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # PostgreSQL on Neon (P0-03). Optional so that pure-logic code and tests run without a database.
    database_url: str | None = None
    # A separate Neon database/branch for DB tests (P0-03, Phase 2). Tests never use DATABASE_URL.
    test_database_url: str | None = None
    # Public base URL written into the A2A agent cards (the three A2A endpoints live in this same app).
    a2a_base_url: str = "http://localhost:8000"
    # Local Ollama, OpenAI-compatible endpoint.
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3.5:4b"
    # Shared secret for the Sales Agent door where Planning sends its answers (header X-Planning-Key). Unset = the door
    # refuses everyone.
    sales_planning_key: str | None = None
    # Background work runner (system_design.md §4, SD-1). Tests switch it off and run work items directly.
    background_workers: bool = True
    worker_poll_seconds: float = 0.5
    event_dispatcher_workers: int = 4
    # X-Door-Key of the simulator's write doors (settings). Unset = those doors refuse everyone.
    simulation_door_key: str | None = None
    # X-Door-Key of Planning's door 1 (requests from Sales). Unset = refuses everyone.
    planning_door_key: str | None = None
    # How Sales reaches Planning: "fake" (the built-in FakePlanning) or "real" (Planning door 1 over HTTP).
    planning_connector: str = "fake"
    # Purchasing Agent working values (dev_docs/purchasing_agent/purchasing_agent_architecture.md). The selection date
    # is today's date in this timezone.
    purchasing_timezone: str = "Asia/Kolkata"
    purchasing_response_deadline_hours: int = Field(default=24, ge=1)
    purchasing_max_rounds: int = Field(default=3, ge=1)
    purchasing_max_clarifications: int = Field(default=2, ge=0)  # per pending offer; clarifications are not rounds
    # A Cost-Saving Split must save at least this fraction against the best priced single supplier (0.10 = 10%).
    purchasing_cost_saving_split_threshold: Decimal = Field(default=Decimal("0.10"), ge=0, lt=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
