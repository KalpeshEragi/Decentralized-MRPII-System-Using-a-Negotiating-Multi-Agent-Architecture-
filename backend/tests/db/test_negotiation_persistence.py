"""Persisted negotiation for the X1 Display shortage (500, required by 2026-10-26). Needs TEST_DATABASE_URL."""

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError, ErrorCode
from app.models import audit, negotiation as tables
from app.schemas.negotiation import MessageType as M
from app.services import negotiation_service, planning_service

EARLY, LATE = date(2026, 10, 15), date(2026, 10, 30)  # LATE misses required_by 2026-10-26


def session_row(db, conversation):
    return db.get(tables.NegotiationSession, uuid.UUID(conversation.negotiation_id))


def audit_types(db):
    return [row[0] for row in db.execute(select(audit.DecisionAudit.decision_type).order_by(audit.DecisionAudit.created_at))]


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


def test_agreement_path_then_supplier_stored_without_agent_id(db, display_session):
    c = display_session
    c.send("PUR", "SUP", M.OFFER, 500, EARLY)
    view = negotiation_service.submit_supplier_response(db, uuid.UUID(c.negotiation_id), 1, M.ACCEPT)
    assert view["awaiting_supplier"] is False
    view = c.send("PUR", "INV", M.AGREEMENT_PROPOSED, 500, EARLY)
    assert (view["status"], view["outcome"]) == ("AGREEMENT_PROPOSED", "AGREEMENT")
    assert view["agreement"]["validated"] is True and view["agreement"]["committed"] is False
    supplier_message = db.scalars(select(tables.NegotiationMessage).where(tables.NegotiationMessage.sender_type == "SUPPLIER_INTERFACE")).one()
    assert supplier_message.sender_agent_id is None and supplier_message.receiver_agent_id is not None
    assert [o["status"] for o in view["offers"]] == ["ACCEPTED"] and view["offers"][0]["terms"]["quantity"] == 500
    assert "AGREEMENT_PROPOSED" in audit_types(db)


def test_infeasible_agreement_is_stored_but_not_validated_and_cannot_commit(db, display_session):
    c = display_session
    c.send("PUR", "SUP", M.OFFER, 500, LATE)
    negotiation_service.submit_supplier_response(db, uuid.UUID(c.negotiation_id), 1, M.ACCEPT)
    view = c.send("PUR", "INV", M.AGREEMENT_PROPOSED, 500, LATE)
    assert view["agreement"]["validated"] is False
    with pytest.raises(AppError) as exc:
        c.send("APP", "INV", M.COMMIT)
    assert exc.value.code == ErrorCode.BUSINESS_RULE_VIOLATION


def test_commit_makes_the_agreement_a_scheduled_receipt(db, display_session, order_id):
    from app.data import x1_fixture as x1

    c = display_session
    c.send("PUR", "SUP", M.OFFER, 500, EARLY)
    negotiation_service.submit_supplier_response(db, uuid.UUID(c.negotiation_id), 1, M.ACCEPT)
    c.send("PUR", "INV", M.AGREEMENT_PROPOSED, 500, EARLY)
    assert negotiation_service.scheduled_receipts(db, {x1.COMPONENT_IDS["Display"]}) == []  # not committed yet
    view = c.send("APP", "INV", M.COMMIT)
    assert view["status"] == "COMMITTED" and view["agreement"]["committed"] is True
    plan = planning_service.run_plan(db, order_id)
    display = next(r for r in plan.requirements if r.item_id == x1.COMPONENT_IDS["Display"])
    assert (display.scheduled_receipts, display.net_requirement, display.status.value) == (500, 0, "COVERED")


def test_supplier_reject_gives_rejected_and_planning_outcome_failed(db, display_session):
    c = display_session
    c.send("PUR", "SUP", M.OFFER, 500, EARLY)
    view = negotiation_service.submit_supplier_response(db, uuid.UUID(c.negotiation_id), 1, M.REJECT)
    assert (view["status"], view["outcome"]) == ("REJECTED", "FAILED")
    assert session_row(db, c).completed_at is not None
    assert "NEGOTIATION_REJECTED" in audit_types(db)


def test_purchasing_can_reject_early(db, display_session):
    view = display_session.send("PUR", "INV", M.REJECT)
    assert (view["status"], view["outcome"], view["round_number"]) == ("REJECTED", "FAILED", 0)


def test_failed_after_three_rounds_and_no_fourth_round(db, display_session):
    c = display_session
    c.send("PUR", "SUP", M.OFFER, 500, EARLY)
    for round_number in (1, 2, 3):
        view = negotiation_service.submit_supplier_response(db, uuid.UUID(c.negotiation_id), round_number, M.COUNTER_OFFER, 300, LATE)
        assert view["round_number"] == round_number
        if round_number < 3:
            c.send("PUR", "SUP", M.COUNTER_OFFER, 450, EARLY)
    view = c.send("PUR", "SUP", M.COUNTER_OFFER, 450, EARLY)  # would be round 4
    assert (view["status"], view["outcome"], view["round_number"]) == ("FAILED", "FAILED", 3)
    purchasing_offers = db.scalar(select(func.count()).select_from(tables.NegotiationMessage).where(
        tables.NegotiationMessage.sender_type == "PURCHASING", tables.NegotiationMessage.message_type.in_(["OFFER", "COUNTER_OFFER"])))
    assert purchasing_offers == 4  # rounds 1-3 plus the refused-as-round-4 message, which opened no offer
    assert db.scalar(select(func.count()).select_from(tables.NegotiationOffer)) == 6
    assert "NEGOTIATION_FAILED" in audit_types(db)
    with pytest.raises(AppError) as exc:
        negotiation_service.submit_supplier_response(db, uuid.UUID(c.negotiation_id), 4, M.ACCEPT)
    assert exc.value.code == ErrorCode.INVALID_STATE_TRANSITION


def test_invalid_messages_are_rejected_and_change_nothing(db, display_session):
    c = display_session
    before = len(negotiation_service.get_session_view(db, uuid.UUID(c.negotiation_id))["messages"])
    with pytest.raises(AppError):  # wrong sequence number
        c.send("PUR", "SUP", M.OFFER, 500, EARLY, seq=7)
    with pytest.raises(AppError):  # AGREEMENT_PROPOSED before any supplier response
        c.send("PUR", "INV", M.AGREEMENT_PROPOSED, 500, EARLY)
    with pytest.raises(AppError):  # a supplier response when no round is open
        negotiation_service.submit_supplier_response(db, uuid.UUID(c.negotiation_id), 1, M.ACCEPT)
    assert len(negotiation_service.get_session_view(db, uuid.UUID(c.negotiation_id))["messages"]) == before
