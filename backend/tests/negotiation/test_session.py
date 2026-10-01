"""Pure negotiation protocol: agreement, REJECTED, FAILED after 3 rounds and refused messages."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.negotiation.messages import parse_message
from app.negotiation.protocol import ProtocolError, ProtocolErrorCode
from app.negotiation.session import NegotiationSession
from app.schemas.negotiation import (
    AgentRef, AgentType, MessagePayload, MessageType as M, NegotiationMessage, OfferTerms, SessionStatus as S,
)

REF = {
    "INV": AgentRef(agent_id="inv", agent_type=AgentType.INVENTORY),
    "PUR": AgentRef(agent_id="pur", agent_type=AgentType.PURCHASING),
    "SUP": AgentRef(agent_id="sup", agent_type=AgentType.SUPPLIER_INTERFACE),
    "APP": AgentRef(agent_id="approval-workflow", agent_type=AgentType.APPROVAL_WORKFLOW),
}
DELIVERY = date(2026, 10, 15)


def msg(session, sender, receiver, kind, qty=None, delivery=DELIVERY, seq=None):
    terms = None
    if qty is not None:
        terms = OfferTerms(quantity=Decimal(qty), delivery_date=delivery,
                           required_date=date(2026, 10, 26) if kind == M.REQUEST else None)
    n = seq or len(session.messages) + 1
    return NegotiationMessage(
        message_id=f"m{n}-{kind}", negotiation_id="n1", sender=REF[sender], receiver=REF[receiver],
        message_type=kind, sequence_number=n, timestamp=datetime(2026, 10, 1, tzinfo=timezone.utc),
        payload=MessagePayload(terms=terms),
    )


def new_session():
    return NegotiationSession("n1", "inv", "pur", "sup")


def opened():
    s = new_session()
    s.submit(msg(s, "INV", "PUR", M.REQUEST, 500))
    s.submit(msg(s, "PUR", "SUP", M.OFFER, 500))
    return s


def test_agreement_then_commit():
    s = opened()
    s.submit(msg(s, "SUP", "PUR", M.ACCEPT))
    assert s.submit(msg(s, "PUR", "INV", M.AGREEMENT_PROPOSED, 500)) == S.AGREEMENT_PROPOSED
    assert s.outcome == "AGREEMENT" and s.agreed_terms.quantity == 500
    # Inventory and Purchasing cannot commit; only the approval workflow can, and only after AGREEMENT_PROPOSED.
    for sender, receiver in (("INV", "PUR"), ("PUR", "INV")):
        with pytest.raises(ProtocolError) as exc:
            s.submit(msg(s, sender, receiver, M.COMMIT))
        assert exc.value.code == ProtocolErrorCode.INVALID_MESSAGE
    assert s.status == S.AGREEMENT_PROPOSED
    assert s.submit(msg(s, "APP", "INV", M.COMMIT)) == S.COMMITTED


def test_commit_before_agreement_is_refused():
    s = opened()
    with pytest.raises(ProtocolError) as exc:
        s.submit(msg(s, "APP", "INV", M.COMMIT))
    assert exc.value.code == ProtocolErrorCode.INVALID_STATE_TRANSITION


def test_purchasing_can_reject_early_in_round_one_or_after_a_supplier_counter():
    s = opened()  # round 1 open, supplier has not answered yet: Purchasing cannot act out of turn
    with pytest.raises(ProtocolError):
        s.submit(msg(s, "PUR", "SUP", M.REJECT))
    s.submit(msg(s, "SUP", "PUR", M.COUNTER_OFFER, 300, date(2026, 10, 25)))
    assert s.submit(msg(s, "PUR", "SUP", M.REJECT)) == S.REJECTED
    assert s.round_number == 1 and s.outcome == "FAILED" and s.is_ended
    s2 = new_session()
    s2.submit(msg(s2, "INV", "PUR", M.REQUEST, 500))
    assert s2.submit(msg(s2, "PUR", "INV", M.REJECT)) == S.REJECTED  # no acceptable proposal at all


def test_supplier_reject_is_rejected_and_outcome_failed():  # REJECTED is distinct from FAILED (round limit)
    s = opened()
    assert s.submit(msg(s, "SUP", "PUR", M.REJECT)) == S.REJECTED
    assert s.outcome == "FAILED"


def test_failed_after_three_rounds():
    s = opened()
    for round_no in (1, 2, 3):
        assert s.round_number == round_no
        s.submit(msg(s, "SUP", "PUR", M.COUNTER_OFFER, 300, date(2026, 10, 25)))
        if round_no < 3:
            s.submit(msg(s, "PUR", "SUP", M.COUNTER_OFFER, 450))
    assert s.status == S.NEGOTIATING
    assert s.submit(msg(s, "PUR", "SUP", M.COUNTER_OFFER, 450)) == S.FAILED
    assert s.round_number == 3 and s.outcome == "FAILED" and s.is_ended


def test_purchasing_can_accept_supplier_counter_in_round_three():
    s = opened()
    for _ in range(2):
        s.submit(msg(s, "SUP", "PUR", M.COUNTER_OFFER, 300))
        s.submit(msg(s, "PUR", "SUP", M.COUNTER_OFFER, 450))
    s.submit(msg(s, "SUP", "PUR", M.COUNTER_OFFER, 300))
    assert s.submit(msg(s, "PUR", "INV", M.AGREEMENT_PROPOSED, 300)) == S.AGREEMENT_PROPOSED


@pytest.mark.parametrize(
    "build, code",
    [
        (lambda s: msg(s, "PUR", "SUP", M.OFFER, 500), ProtocolErrorCode.INVALID_STATE_TRANSITION),  # no REQUEST first
        (lambda s: msg(s, "INV", "PUR", M.REQUEST, 500, seq=2), ProtocolErrorCode.INVALID_SEQUENCE),
        (lambda s: msg(s, "SUP", "PUR", M.REQUEST, 500), ProtocolErrorCode.INVALID_MESSAGE),  # wrong route
        (lambda s: msg(s, "INV", "PUR", M.REQUEST), ProtocolErrorCode.INVALID_MESSAGE),  # missing terms
    ],
)
def test_refused_messages_leave_session_unchanged(build, code):
    s = new_session()
    with pytest.raises(ProtocolError) as exc:
        s.submit(build(s))
    assert exc.value.code == code
    assert s.status == S.INITIATED and s.messages == []


def test_agreement_terms_must_match_the_table_and_ended_session_refuses():
    s = opened()
    s.submit(msg(s, "SUP", "PUR", M.ACCEPT))
    with pytest.raises(ProtocolError) as exc:
        s.submit(msg(s, "PUR", "INV", M.AGREEMENT_PROPOSED, 400))
    assert exc.value.code == ProtocolErrorCode.TERMS_MISMATCH
    s2 = opened()
    s2.submit(msg(s2, "SUP", "PUR", M.REJECT))
    with pytest.raises(ProtocolError) as exc:
        s2.submit(msg(s2, "PUR", "SUP", M.OFFER, 500))
    assert exc.value.code == ProtocolErrorCode.SESSION_ENDED


def test_price_field_is_rejected():
    data = msg(new_session(), "INV", "PUR", M.REQUEST, 500).model_dump(mode="json")
    data["payload"]["terms"]["price"] = 10
    with pytest.raises(ProtocolError) as exc:
        parse_message(data)
    assert exc.value.code == ProtocolErrorCode.INVALID_MESSAGE
