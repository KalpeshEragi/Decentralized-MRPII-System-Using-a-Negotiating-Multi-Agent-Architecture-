"""DB test fixtures. They need TEST_DATABASE_URL (a separate Neon database, never DATABASE_URL) and skip without it.

The session fixture migrates the test database to head; every test starts from the deterministic X1 baseline.
"""

import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import make_engine
from app.data.seed_data import BASELINE_ORDER_ID, reset_and_seed
from app.models.negotiation import NegotiationMessage as NegotiationMessageRow
from app.schemas.negotiation import AgentRef, AgentType, MessagePayload, MessageType, NegotiationMessage, OfferTerms
from app.services import negotiation_service

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
def db(engine):
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    reset_and_seed(session)
    yield session
    session.close()


@pytest.fixture
def order_id() -> uuid.UUID:
    return BASELINE_ORDER_ID


class Conversation:
    """Builds correctly numbered C4 messages for one persisted session and submits them through the service."""

    def __init__(self, db, negotiation_id: str):
        self.db, self.negotiation_id = db, negotiation_id
        ids = negotiation_service._agent_ids(db)
        self.refs = {
            "INV": AgentRef(agent_id=ids[AgentType.INVENTORY], agent_type=AgentType.INVENTORY),
            "PUR": AgentRef(agent_id=ids[AgentType.PURCHASING], agent_type=AgentType.PURCHASING),
            "SUP": AgentRef(agent_id=ids[AgentType.SUPPLIER_INTERFACE], agent_type=AgentType.SUPPLIER_INTERFACE),
            "APP": AgentRef(agent_id=ids[AgentType.APPROVAL_WORKFLOW], agent_type=AgentType.APPROVAL_WORKFLOW),
        }

    def _next_sequence(self) -> int:
        """Next number after everything stored so far, including supplier responses sent through the service."""
        count = self.db.scalar(select(func.count()).select_from(NegotiationMessageRow).where(
            NegotiationMessageRow.negotiation_id == uuid.UUID(self.negotiation_id)))
        return (count or 0) + 1

    def send(self, sender: str, receiver: str, kind: MessageType, quantity=None, delivery=None, required=None, seq=None):
        terms = None if quantity is None else OfferTerms(quantity=quantity, delivery_date=delivery, required_date=required)
        message = NegotiationMessage(
            message_id=str(uuid.uuid4()),
            negotiation_id=self.negotiation_id,
            sender=self.refs[sender],
            receiver=self.refs[receiver],
            message_type=kind,
            sequence_number=seq or self._next_sequence(),
            timestamp=datetime(2026, 10, 1, tzinfo=timezone.utc),
            payload=MessagePayload(terms=terms),
        )
        return negotiation_service.submit_message(self.db, uuid.UUID(self.negotiation_id), message)


@pytest.fixture
def display_session(db, order_id):
    """A planned X1 baseline with an INITIATED session for the Display shortage (500, required by 2026-10-26)."""
    from app.data import x1_fixture as x1
    from app.services import planning_service

    planning_service.run_plan(db, order_id)
    view = negotiation_service.open_session(db, order_id, uuid.UUID(x1.COMPONENT_IDS["Display"]))
    conversation = Conversation(db, view["id"])
    conversation.send("INV", "PUR", MessageType.REQUEST, 500, required=date(2026, 10, 26))
    return conversation


@pytest.fixture
def api(db, engine, monkeypatch):
    """Phase 3+: the app on the test database. A2A calls go through the app's own endpoints in-process (TestClient,
    same wire format); no LLM (FakeLLMClient without replies), so Purchasing's deterministic policy decides."""
    from fastapi.testclient import TestClient

    from app.agents import base
    from app.api import a2a
    from app.core import a2a_client
    from app.core.database import get_db
    from app.llm.client import FakeLLMClient
    from app.main import app

    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(a2a, "new_session", factory)
    client = TestClient(app)
    monkeypatch.setattr(a2a_client, "_http_client", client)
    monkeypatch.setattr(base, "_llm_client", FakeLLMClient([]))
    yield client
    app.dependency_overrides.clear()
