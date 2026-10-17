"""Negotiation v2 (negotiation.md §4, §10.3): a starter and an owner reach a commitment through the outbox, the A2A
endpoints (store and acknowledge) and the inboxes; a repeated message is a harmless duplicate; the protocol refuses
out-of-turn messages; a stale commit ends REJECTED; NG-5 allows one open negotiation per need.

Planning plays the starter and HR the owner, with tiny fake handlers (the real agents come in steps 4-5)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import work_runner as wr
from app.main import app
from app.negotiation import a2a_endpoints, layer, transport
from app.negotiation.envelope import Envelope, Hold, MessageType as M, ReasonCode, ResourceType, Terms
from app.negotiation.models import Message, Outbox, Session

TERMS = Terms(resource_type=ResourceType.WORKFORCE, resource_ref="ASSEMBLY", quantity=Decimal("23.5"), unit="h",
              date_from=date(2026, 11, 13), date_to=date(2026, 11, 14), order_id="SO-1",
              extra={"allow_overtime": False})


@pytest.fixture
def wire(session_factory):
    """Endpoints and transport on the test database, through the app in-process."""
    a2a_endpoints.set_session_factory(session_factory)
    transport.set_http_client(TestClient(app))
    yield session_factory
    transport.set_http_client(None)
    a2a_endpoints.set_session_factory(a2a_endpoints.new_session)


def request(case_id="CASE-1") -> Envelope:
    message_id, session_id = layer.new_ids()
    return Envelope(message_id=message_id, session_id=session_id, case_id=case_id, sender="PLANNING",
                    receiver="HR", message_type=M.REQUEST, terms=TERMS, sent_at=datetime.now(timezone.utc))


def pump(session_factory, registrations) -> None:
    """Run outbox and inbox work until nothing is left (what the background workers do)."""
    for _ in range(100):
        worked = wr.run_one_long(session_factory, Outbox, layer.send_outbox_item, "test-sender")
        for registration in registrations:
            worked |= wr.run_one_short(session_factory, Message, layer.handle_inbox, where=registration.where)
        if not worked:
            return
    raise AssertionError("work did not settle")


def start(session_factory, envelope: Envelope) -> None:
    with session_factory() as db:
        layer.send(db, envelope)
        db.commit()


def session_row(session_factory, session_id) -> Session:
    with session_factory() as db:
        return db.get(Session, session_id)


def test_starter_and_owner_reach_a_commitment_over_a2a(wire):
    seen = []

    def hr_owner(db, message, session):
        seen.append(("HR", message.message_type))
        if message.message_type == M.REQUEST:
            layer.send(db, layer.reply_to(message, M.OFFER, terms=message.terms))
        elif message.message_type == M.ACCEPT:
            hold = Hold(hold_id="H-1", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
            layer.send(db, layer.reply_to(message, M.AGREEMENT_PROPOSED, terms=Terms.model_validate(session.last_offer),
                                          hold=hold))
        elif message.message_type == M.COMMIT:
            layer.send(db, layer.reply_to(message, M.ACCEPT))  # re-checked and committed

    def planning_starter(db, message, session):
        seen.append(("PLANNING", message.message_type))
        if message.message_type == M.OFFER:
            layer.send(db, layer.reply_to(message, M.ACCEPT))
        elif message.message_type == M.AGREEMENT_PROPOSED:
            layer.send(db, layer.reply_to(message, M.COMMIT))

    registrations = [layer.register_inbox("HR", hr_owner), layer.register_inbox("PLANNING", planning_starter)]
    first = request()
    start(wire, first)
    pump(wire, registrations)

    row = session_row(wire, first.session_id)
    assert (row.status, row.round, row.hold_id, row.message_count) == ("COMMITTED", 1, "H-1", 6)
    assert seen == [("HR", M.REQUEST), ("PLANNING", M.OFFER), ("HR", M.ACCEPT), ("PLANNING", M.AGREEMENT_PROPOSED),
                    ("HR", M.COMMIT), ("PLANNING", M.ACCEPT)]

    # A repeated delivery is acknowledged as a duplicate and changes nothing.
    duplicate = transport.send("HR", first.model_dump(mode="json"))
    assert duplicate["accepted"] and duplicate["duplicate"]
    # A message after the end is refused, and the session stays as it is.
    late = layer.reply_to(layer.reply_to(first, M.OFFER, terms=TERMS), M.ABORT)
    refused = transport.send("HR", late.model_dump(mode="json"))
    assert not refused["accepted"] and refused["error"]["code"] == "SESSION_ENDED"
    assert session_row(wire, first.session_id).message_count == 6


def test_stale_commit_is_rejected_and_one_open_negotiation_per_need(wire):
    def hr_owner(db, message, session):
        if message.message_type == M.REQUEST:
            layer.send(db, layer.reply_to(message, M.OFFER, terms=message.terms))
        elif message.message_type == M.ACCEPT:
            hold = Hold(hold_id="H-2", expires_at=datetime.now(timezone.utc) + timedelta(days=1))
            layer.send(db, layer.reply_to(message, M.AGREEMENT_PROPOSED, terms=Terms.model_validate(session.last_offer),
                                          hold=hold))
        elif message.message_type == M.COMMIT:  # facts changed in the meantime
            layer.send(db, layer.reply_to(message, M.REJECT, reason_code=ReasonCode.STALE))

    def planning_starter(db, message, session):
        if message.message_type == M.OFFER:
            layer.send(db, layer.reply_to(message, M.ACCEPT))
        elif message.message_type == M.AGREEMENT_PROPOSED:
            layer.send(db, layer.reply_to(message, M.COMMIT))

    registrations = [layer.register_inbox("HR", hr_owner), layer.register_inbox("PLANNING", planning_starter)]
    first = request("CASE-2")
    start(wire, first)
    # While the first negotiation is open, a second one for the same need is refused (NG-5).
    wr.run_one_long(wire, Outbox, layer.send_outbox_item, "test-sender")  # the first REQUEST arrives
    second = transport.send("HR", request("CASE-2").model_dump(mode="json"))
    assert not second["accepted"] and second["error"]["code"] == "CONFLICT"
    # Out of turn: Planning may not accept before HR has offered anything.
    early = transport.send("HR", layer.reply_to(layer.reply_to(first, M.OFFER, terms=TERMS), M.ACCEPT)
                           .model_dump(mode="json"))
    assert not early["accepted"] and early["error"]["code"] == "INVALID_STATE_TRANSITION"

    pump(wire, registrations)
    row = session_row(wire, first.session_id)
    assert (row.status, row.last_reason_code) == ("REJECTED", "STALE")
