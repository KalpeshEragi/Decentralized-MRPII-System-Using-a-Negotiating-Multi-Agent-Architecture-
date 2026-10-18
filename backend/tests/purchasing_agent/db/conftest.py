"""Database fixtures for the Purchasing Agent, Supplier Service and Negotiation Engine. They need TEST_DATABASE_URL (a
separate Neon database, never DATABASE_URL) and skip without it.

The first test brings the test database up to the latest migration. Every test then starts from the fixture data
(dev_docs/purchasing_agent/seed_data.md): only the three new schemas are emptied and re-seeded; nothing else is touched.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import get_db, make_engine
from app.core.errors import install_error_handlers
from app.llm.client import FakeLLMClient
from app.purchasing_agent import api
from app.purchasing_agent.seed import reset_and_seed

BACKEND = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # the fixture's selection date


@pytest.fixture(scope="session")
def engine():
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.attributes["url"] = url
    command.upgrade(config, "head")
    return make_engine(url)


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    reset_and_seed(session)
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(db, engine) -> TestClient:
    """The Purchasing API on the freshly seeded test database, with the clock fixed at NOW and no LLM: every call to
    the model fails, so replies go to the fallback parser and messages use the templates. A test that wants the LLM
    overrides `api.get_llm_client` with its own fake."""
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def session_per_request():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    install_error_handlers(app)  # the same error format as the real backend
    app.include_router(api.router)
    app.dependency_overrides[get_db] = session_per_request
    app.dependency_overrides[api.get_clock] = lambda: lambda: NOW
    app.dependency_overrides[api.get_llm_client] = lambda: FakeLLMClient([])  # no replies: every call raises LLMError
    return TestClient(app)
