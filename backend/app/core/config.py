"""Application settings, read from environment variables or the repository-root `.env` file."""

from functools import lru_cache
from pathlib import Path

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
