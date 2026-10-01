"""C6 agent state shapes and offer-history rebuilding, no database."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.agents.base import AgentStateData, offer_history

AT = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
RECORD = {"negotiation_id": "n1", "message_id": "m1", "round": 1, "message_type": "OFFER",
          "terms": {"quantity": 500, "delivery_date": "2026-10-15"}, "at": AT.isoformat()}


def test_c6_purchasing_example_shape_is_accepted():
    state = AgentStateData.model_validate({
        "current_goal": {"goal_type": "SECURE_MATERIAL", "description": "Procure 500", "refs": {"negotiation_id": "n1"}},
        "current_task": {"task_type": "AWAIT_SUPPLIER_RESPONSE", "status": "WAITING", "refs": {}, "started_at": None},
        "preferred_terms": {"quantity": 500, "delivery_date": "2026-10-15"},
        "reserved_limits": {"latest_acceptable_delivery": "2026-10-26", "min_quantity": 500, "max_quantity": 600},
        "initial_proposal": {"quantity": 500, "delivery_date": "2026-10-15"},
        "own_offer_history": [RECORD],
        "opponent_offer_history": [],
        "dialogue_history": [{"round": 1, "counterpart": "SUPPLIER_INTERFACE", "summary": "ok", "at": AT.isoformat()}],
        "negotiation_rules": {"max_rounds": 3, "policy": {"procurement_strategy": "meet required date first"}},
    })
    assert state.own_offer_history[0].terms.delivery_date == date(2026, 10, 15)


@pytest.mark.parametrize(
    "bad",
    [
        {"reserved_limits": {"max_price": 10}},
        {"negotiation_rules": {"max_rounds": 3, "policy": {"cost_weight": 0.5}}},
        {"preferred_terms": {"quantity": 500, "price": 10}},
        {"negotiation_rules": {"max_rounds": 4, "policy": {}}},
        {"own_offer_history": [{**RECORD, "round": 4}]},
        {"own_offer_history": [RECORD] * 4},
        {"dialogue_history": [{"counterpart": "SUPPLIER_AGENT", "summary": "x", "at": AT.isoformat()}]},
        {"unknown_field": 1},
    ],
)
def test_invalid_state_is_refused(bad):
    with pytest.raises(ValidationError):
        AgentStateData.model_validate(bad)


def message(seq, kind, sender, quantity=None, delivery=None):
    terms = None if quantity is None else {"quantity": quantity, "delivery_date": delivery, "required_date": None,
                                           "priority": None}
    return {"message_id": f"m{seq}", "sequence_number": seq, "message_type": kind, "sender": sender,
            "receiver": "", "payload": {"terms": terms, "message": None}, "timestamp": AT}


def test_offer_history_of_a_failed_session_has_three_rounds():
    messages = [message(1, "REQUEST", "INVENTORY", 500, None), message(2, "OFFER", "PURCHASING", 500, "2026-10-15")]
    for seq in (3, 5, 7):
        messages.append(message(seq, "COUNTER_OFFER", "SUPPLIER_INTERFACE", 500, "2026-10-30"))
        messages.append(message(seq + 1, "COUNTER_OFFER", "PURCHASING", 500, "2026-10-26"))  # the last one trips FAILED
    history = offer_history({"id": "n1", "messages": messages})
    assert [r.round for r in history["PURCHASING"]] == [1, 2, 3]
    assert [r.round for r in history["SUPPLIER_INTERFACE"]] == [1, 2, 3]
    assert history["AGREEMENT"] == []


def test_offer_history_of_an_agreement():
    messages = [message(1, "REQUEST", "INVENTORY", 500, None), message(2, "OFFER", "PURCHASING", 500, "2026-10-15"),
                message(3, "ACCEPT", "SUPPLIER_INTERFACE"), message(4, "AGREEMENT_PROPOSED", "PURCHASING", 500, "2026-10-15")]
    history = offer_history({"id": "n1", "messages": messages})
    accepted = history["SUPPLIER_INTERFACE"][0]
    assert (accepted.round, accepted.message_type.value, accepted.terms.quantity) == (1, "ACCEPT", 500)
    assert history["AGREEMENT"][0].terms.delivery_date == date(2026, 10, 15)
