"""Database fixtures for the Purchasing Agent, Supplier Service and Negotiation Engine. They need TEST_DATABASE_URL (a
separate Neon database, never DATABASE_URL) and skip without it.

The first test brings the test database up to the latest migration. Every test then starts from the fixture data
(docs/purchasing_agent_fixture.md): only the three new schemas are emptied and re-seeded; nothing else is touched.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import make_engine
from app.purchasing_agent.seed import reset_and_seed

BACKEND = Path(__file__).resolve().parents[3]


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
