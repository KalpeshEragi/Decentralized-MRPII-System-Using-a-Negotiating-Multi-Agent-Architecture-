"""Database fixtures for the Sales Agent tables. They need TEST_DATABASE_URL (a separate Neon database, never
DATABASE_URL) and skip without it.

The first test brings the test database up to the latest migration. Every test then starts with empty Sales Agent
tables. Only the tables of the `sales_agent` schema are emptied; nothing else in the database is touched.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import make_engine
from app.sales_agent.models import SalesAgentBase

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
    tables = ", ".join(f'"{table.schema}"."{table.name}"' for table in SalesAgentBase.metadata.sorted_tables)
    session.execute(text(f"TRUNCATE {tables} CASCADE"))
    session.commit()
    yield session
    session.rollback()
    session.close()
