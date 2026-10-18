"""Persisted negotiation for the X1 Display shortage (500, required by 2026-10-26). Needs TEST_DATABASE_URL."""

import uuid
from datetime import date

import pytest

from app.core.errors import AppError, ErrorCode
from app.models import negotiation as tables
from app.schemas.negotiation import MessageType as M
from app.services import negotiation_service

EARLY = date(2026, 10, 15)


def session_row(db, conversation):
    return db.get(tables.NegotiationSession, uuid.UUID(conversation.negotiation_id))


def test_open_session_stores_the_shortage_as_objective(db, display_session):
    row = session_row(db, display_session)
    assert (row.status, row.negotiation_type) == ("NEGOTIATING", "SHORTAGE_PROCUREMENT")
    assert row.objective["shortage_quantity"] == 500 and row.objective["required_by"] == "2026-10-26"
    assert row.completed_at is None
    assert row.deadline.date() == date(2026, 10, 26)


def test_one_session_per_shortage(db, display_session, order_id):
    from app.data import x1_fixture as x1

    with pytest.raises(AppError) as exc:
        negotiation_service.open_session(db, order_id, uuid.UUID(x1.COMPONENT_IDS["Display"]))
    assert exc.value.code == ErrorCode.CONFLICT










def test_purchasing_can_reject_early(db, display_session):
    view = display_session.send("PUR", "INV", M.REJECT)
    assert (view["status"], view["outcome"], view["round_number"]) == ("REJECTED", "FAILED", 0)




def test_invalid_messages_are_rejected_and_change_nothing(db, display_session):
    c = display_session
    before = len(negotiation_service.get_session_view(db, uuid.UUID(c.negotiation_id))["messages"])
    with pytest.raises(AppError):  # wrong sequence number
        c.send("PUR", "SUP", M.OFFER, 500, EARLY, seq=7)
    with pytest.raises(AppError):  # AGREEMENT_PROPOSED before any supplier response
        c.send("PUR", "INV", M.AGREEMENT_PROPOSED, 500, EARLY)
    assert len(negotiation_service.get_session_view(db, uuid.UUID(c.negotiation_id))["messages"]) == before
