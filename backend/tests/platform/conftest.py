"""Fixtures for the shared infrastructure tests. They need TEST_DATABASE_URL (a separate database) and skip without it.

Each test starts with empty event, clock, settings and negotiation tables and no registered handlers.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import make_engine
from app.events import channel
from app.negotiation import layer

BACKEND = Path(__file__).resolve().parents[2]


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
def session_factory(engine):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE events.event_deliveries, events.events, simulation.clock, "
                                "simulation.settings, negotiation.outbox, negotiation.messages, negotiation.sessions "
                                "RESTART IDENTITY CASCADE"))
    channel.unsubscribe_all()
    layer.unregister_all()
    yield sessionmaker(bind=engine, expire_on_commit=False)
    channel.unsubscribe_all()
    layer.unregister_all()
