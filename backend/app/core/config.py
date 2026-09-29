"""Application settings, read from environment variables or the repository-root `.env` file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # PostgreSQL on Neon (P0-03). Optional until the database layer exists (Phase 2).
    database_url: str | None = None
    # Local Ollama, OpenAI-compatible endpoint.
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3.5:4b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
