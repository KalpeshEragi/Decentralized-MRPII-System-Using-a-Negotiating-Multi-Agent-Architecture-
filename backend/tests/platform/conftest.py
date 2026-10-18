"""Fixtures for the shared infrastructure tests. They need TEST_DATABASE_URL (a separate database) and skip without it.

Each test starts with empty infrastructure, agent and reference tables and no registered handlers.
"""

import os
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, literal, select, text, union_all
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core import workers
from app.core.platform_base import PlatformBase
from app.events import channel
from app.models import Base
from app.negotiation import layer

BACKEND = Path(__file__).resolve().parents[2]
NOT_PUMPED = ("planning-sales-outbox",)  # it would POST to Sales door 3: tests read Planning's results from the outbox


@pytest.fixture(scope="session")
def engine():
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.attributes["url"] = url
    command.upgrade(config, "head")
    # Fail fast instead of hanging for hours on a dead connection (remote database) or a stuck lock.
    return create_engine(url, pool_pre_ping=True, connect_args={
        "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3,
        "options": "-c statement_timeout=120000 -c lock_timeout=60000"})


@pytest.fixture
def session_factory(engine):
    from app.negotiation_engine.models import NegotiationEngineBase
    from app.purchasing_agent.models import PurchasingAgentBase
    from app.supplier_service.models import SupplierServiceBase

    tables = [*PlatformBase.metadata.sorted_tables, *Base.metadata.sorted_tables,
              *SupplierServiceBase.metadata.sorted_tables, *PurchasingAgentBase.metadata.sorted_tables,
              *NegotiationEngineBase.metadata.sorted_tables]
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


@pytest.fixture(autouse=True)
def no_language_model(monkeypatch):
    """Platform tests never call Ollama: Purchasing's model calls fail at once, so its templates and strict parser
    are used (exactly what happens when the model is down)."""
    from app.llm.client import FakeLLMClient
    from app.purchasing_agent import a2a

    monkeypatch.setattr(a2a, "llm_client", lambda: FakeLLMClient([]))


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

    # Every queue the pump drains: (model, how one item is run). Inbox messages go to the handler registered for their
    # receiver (layer.handle_inbox), so a test's fake inbox (e.g. a FAKE Planning) is served like a real one.
    queues = [(Outbox, lambda: wr.run_one_long(session_factory, Outbox, layer.send_outbox_item, "test-sender")),
              (Message, lambda: wr.run_one_short(session_factory, Message, layer.handle_inbox)),
              (EventDelivery, lambda: wr.run_one_short(session_factory, EventDelivery, channel.deliver))]
    for registration in workers.runner.registrations:  # agents' own queues (Planning's work, Purchasing's adapter)
        if registration.model in (Message, EventDelivery, Outbox) or registration.name in NOT_PUMPED:
            continue
        if registration.mode == "short":
            queues.append((registration.model,
                           lambda r=registration: wr.run_one_short(session_factory, r.model, r.handler, where=r.where)))
        else:
            queues.append((registration.model, lambda r=registration: wr.run_one_long(
                session_factory, r.model, r.handler, "test-worker", where=r.where)))
    trace = os.environ.get("PUMP_TRACE")  # set to see each pump round

    def unfinished(db) -> dict[type, int]:
        """One query: how many unfinished items each queue has (the remote test database makes every trip count)."""
        parts = [select(literal(i).label("q"), func.count().label("n")).select_from(model)
                 .where(model.status.not_in(wr.FINISHED)) for i, (model, _) in enumerate(queues)]
        return {queues[q][0]: n for q, n in db.execute(union_all(*parts)).all() if n}

    def run(extra_inboxes=()) -> None:  # extra_inboxes: kept for older tests; every inbox is served anyway
        for round_no in range(200):
            with session_factory() as db:
                waiting = unfinished(db)
            if trace:
                print(f"pump round {round_no} at {time.strftime('%X')}: "
                      f"{ {m.__tablename__: n for m, n in waiting.items()} }", flush=True)
            worked = False
            for model, run_one in queues:
                if model in waiting:
                    while run_one():  # drain this queue before asking again
                        worked = True
            if not worked:
                break
        else:
            raise AssertionError("work did not settle")
        with session_factory() as db:  # nothing may be left behind: a failing handler would only be retried later
            stuck = [(model.__tablename__, row.kind, row.status, row.last_error)
                     for model, _ in queues
                     for row in db.scalars(select(model).where(model.status.not_in(wr.FINISHED)))]
        assert not stuck, f"unfinished work after the pump: {stuck}"

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


@pytest.fixture
def factory(session_factory, monkeypatch):
    """The phone factory of `phone_factory.py`, with the doors keyed and the API on the test database.
    Returns the item ids, the start day and a `client` for the doors."""
    from fastapi.testclient import TestClient

    from app.core.database import get_db
    from app.main import app
    from tests.platform import phone_factory

    monkeypatch.setattr(get_settings(), "planning_door_key", phone_factory.KEY)
    monkeypatch.setattr(get_settings(), "simulation_door_key", phone_factory.KEY)

    def test_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with session_factory() as db:
        built = phone_factory.build(db)
        db.commit()
    yield {**built, "client": TestClient(app)}
    app.dependency_overrides.pop(get_db, None)
