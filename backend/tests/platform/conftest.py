"""Fixtures for the shared infrastructure tests. They need TEST_DATABASE_URL (a separate database) and skip without it.

Each test starts with empty infrastructure, agent and reference tables and no registered handlers.
"""

import os
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import make_engine
from app.core import workers
from app.core.platform_base import PlatformBase
from app.events import channel
from app.models import Base
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
    tables = [*PlatformBase.metadata.sorted_tables, *Base.metadata.sorted_tables]
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE " + ", ".join(f'"{t.schema}"."{t.name}"' for t in tables)
                                + " RESTART IDENTITY CASCADE"))
    _clear_registrations()
    yield sessionmaker(bind=engine, expire_on_commit=False)
    _clear_registrations()


def _clear_registrations() -> None:
    channel.unsubscribe_all()
    layer.unregister_all()
    workers.runner.registrations.clear()


@pytest.fixture
def agents(session_factory):
    """All built agents registered (inboxes + event subscriptions), as the background workers would do.
    Returns the inbox registrations, for running work items directly in the test."""
    workers.register_all()
    return [r for r in workers.runner.registrations if r.name.startswith("negotiation-inbox-")]


@pytest.fixture
def pump(session_factory, agents):
    """Run all queued work (outbox sends, inboxes, event deliveries) until nothing is left — what the background
    workers do. Uses in-process A2A (TestClient) on the test database."""
    from fastapi.testclient import TestClient

    from app.core import work_runner as wr
    from app.events.models import EventDelivery
    from app.main import app
    from app.negotiation import a2a_endpoints, transport
    from app.negotiation.models import Message, Outbox

    a2a_endpoints.set_session_factory(session_factory)
    transport.set_http_client(TestClient(app))

    agent_work = [r for r in workers.runner.registrations
                  if r.mode == "short" and r.model not in (Message, EventDelivery)]

    trace = os.environ.get("PUMP_TRACE")  # set to see how long each pump round takes

    def run(extra_inboxes=()) -> None:
        inboxes = [*agents, *extra_inboxes]
        for round_no in range(500):
            if trace:
                print(f"pump round {round_no} at {time.strftime('%X')}", flush=True)
            worked = wr.run_one_long(session_factory, Outbox, layer.send_outbox_item, "test-sender")
            for registration in inboxes:
                worked |= wr.run_one_short(session_factory, Message, layer.handle_inbox, where=registration.where)
            worked |= wr.run_one_short(session_factory, EventDelivery, channel.deliver)
            for registration in agent_work:  # agents' own short queues (e.g. Planning's work items)
                worked |= wr.run_one_short(session_factory, registration.model, registration.handler)
            if not worked:
                return
        raise AssertionError("work did not settle")

    yield run
    transport.set_http_client(None)
    a2a_endpoints.set_session_factory(a2a_endpoints.new_session)


@pytest.fixture
def fake_planning():
    """A FAKE Planning starter: accepts offers, rejects counter-offers, commits agreements. Returns its inbox
    registration (pass it to `pump`) and a `request` helper that queues a REQUEST from Planning."""
    import uuid
    from datetime import datetime, timezone

    from app.negotiation.envelope import Envelope, MessageType as M, ReasonCode

    def handler(db, message, session):
        if message.message_type == M.OFFER:
            layer.send(db, layer.reply_to(message, M.ACCEPT))
        elif message.message_type == M.COUNTER_OFFER:
            layer.send(db, layer.reply_to(message, M.REJECT, reason_code=ReasonCode.INSUFFICIENT))
        elif message.message_type == M.AGREEMENT_PROPOSED:
            layer.send(db, layer.reply_to(message, M.COMMIT))

    registration = layer.register_inbox("PLANNING", handler)

    def request(db, receiver: str, terms, case_id: str) -> str:
        session_id = str(uuid.uuid4())
        layer.send(db, Envelope(message_id=str(uuid.uuid4()), session_id=session_id, case_id=case_id,
                                sender="PLANNING", receiver=receiver, message_type=M.REQUEST, terms=terms,
                                sent_at=datetime.now(timezone.utc)))
        return session_id

    return registration, request
