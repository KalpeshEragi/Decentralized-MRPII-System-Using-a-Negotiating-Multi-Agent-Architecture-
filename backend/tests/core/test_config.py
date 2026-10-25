from app.core.config import Settings


def test_defaults_without_env(monkeypatch):
    for name in ("DATABASE_URL", "OLLAMA_BASE_URL", "OLLAMA_MODEL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url is None
    assert settings.ollama_base_url == "http://127.0.0.1:11434/v1"
    assert settings.ollama_model == "qwen3.5:4b"


def test_environment_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@host/db?sslmode=require")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("OLLAMA_MODEL", "other-model")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://u:p@host/db?sslmode=require"
    assert settings.ollama_base_url == "http://ollama:11434/v1"
    assert settings.ollama_model == "other-model"
