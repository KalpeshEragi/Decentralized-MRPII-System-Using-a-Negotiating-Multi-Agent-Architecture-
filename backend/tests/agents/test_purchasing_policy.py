"""Purchasing Agent decisions on the X1 fixture, no database: supplier choice, limits, own policy, LLM validation."""

import json
from datetime import date

import pytest

from app.agents.purchasing.purchasing_agent import LLM, POLICY, Situation, decide, limits_for
from app.data import x1_fixture as x1
from app.llm.client import FakeLLMClient
from app.schemas.domain import Shortage
from app.schemas.negotiation import MessageType as M
from app.schemas.negotiation import OfferTerms

REQUIRED = date(2026, 10, 26)
NO_LLM = FakeLLMClient([])  # every call raises LLMError: the agent's own deterministic policy decides


def situation(item="Display", quantity=500, required=REQUIRED, overrides=None, round_number=0, response=None, table=None):
    shortage = Shortage(
        item_id=x1.COMPONENT_IDS[item], order_id=x1.ORDER_ID, mps_entry_id="6f1c0e2a-0000-4000-8000-000000000400",
        shortage_quantity=quantity, required_by=required, priority=1, available_quantity=0, projected_available_quantity=0,
    )
    options = tuple(o for o in x1.x1_suppliers(overrides) if o.item_id == shortage.item_id)
    return Situation(shortage, x1.PLANNING_DATE, options, round_number, response, table)


def countered(quantity, delivery, round_number=1):
    return situation(round_number=round_number, response=M.COUNTER_OFFER, table=OfferTerms(quantity=quantity, delivery_date=delivery))


def reply(action, quantity=None, delivery=None, **extra_terms):
    data = {"action": action, "rationale": "short reason"}
    if quantity is not None:
        data["terms"] = {"quantity": quantity, "delivery_date": delivery.isoformat(), **extra_terms}
    return FakeLLMClient([json.dumps(data)])


def result(decision):
    return decision.message_type, None if decision.terms is None else (decision.terms.quantity, decision.terms.delivery_date)


def test_supplier_choice_and_limits_follow_fixture_rule():
    display = limits_for(situation().shortage, situation().options, x1.PLANNING_DATE)
    assert (display.supplier.supplier, display.min_quantity, display.max_quantity) == ("Alpha Displays", 500, 600)
    assert (display.earliest_delivery, display.latest_delivery) == (date(2026, 10, 15), REQUIRED)
    battery = situation("Battery", 600)
    limits = limits_for(battery.shortage, battery.options, x1.PLANNING_DATE)
    assert (limits.supplier.supplier, limits.min_quantity, limits.max_quantity) == ("Volt Power", 600, 700)
    assert limits.earliest_delivery == date(2026, 10, 13)


def test_first_offer_by_policy_when_no_llm():
    decision = decide(situation(), NO_LLM)
    assert result(decision) == (M.OFFER, (500, date(2026, 10, 15)))
    assert (decision.terms.required_date, decision.terms.priority) == (REQUIRED, 1)
    assert decision.source == POLICY and decision.llm_problems


def test_no_usable_supplier_rejects_before_round_1():
    # S7 + S2: required by 10-16, Volt delayed to 27 days, Cell arrives 10-23.
    s = situation("Battery", 600, date(2026, 10, 16), {"Volt Power": {"lead_time_days": 27}})
    assert result(decide(s, NO_LLM)) == (M.REJECT, None)


def test_split_procurement_is_not_offered():
    # S3: Display 800, no supplier covers it alone.
    assert result(decide(situation(quantity=800), NO_LLM)) == (M.REJECT, None)


def test_supplier_accept_of_own_offer_becomes_agreement():
    s = situation(round_number=1, response=M.ACCEPT, table=OfferTerms(quantity=500, delivery_date=date(2026, 10, 15)))
    assert result(decide(s, NO_LLM)) == (M.AGREEMENT_PROPOSED, (500, date(2026, 10, 15)))


@pytest.mark.parametrize(
    "table, expected",
    [
        ((500, date(2026, 10, 30)), (M.COUNTER_OFFER, (500, date(2026, 10, 26)))),  # late -> latest acceptable
        ((400, date(2026, 10, 20)), (M.COUNTER_OFFER, (500, date(2026, 10, 20)))),  # short -> shortage quantity
        ((700, date(2026, 10, 20)), (M.COUNTER_OFFER, (600, date(2026, 10, 20)))),  # above supplier availability
        ((550, date(2026, 10, 20)), (M.AGREEMENT_PROPOSED, (550, date(2026, 10, 20)))),  # acceptable
    ],
)
def test_supplier_counter_policy(table, expected):
    assert result(decide(countered(*table), NO_LLM)) == expected


def test_last_round_unacceptable_counter_is_the_round_limit_counter():
    decision = decide(countered(500, date(2026, 10, 30), round_number=3), NO_LLM)
    assert result(decision) == (M.COUNTER_OFFER, (500, date(2026, 10, 26)))  # the protocol ends the session FAILED
    assert "round limit" in decision.rationale


def test_valid_llm_proposal_is_used():
    decision = decide(countered(500, date(2026, 10, 30)), reply("COUNTER_OFFER", 520, date(2026, 10, 24)))
    assert result(decision) == (M.COUNTER_OFFER, (520, date(2026, 10, 24)))
    assert decision.source == LLM and not decision.llm_problems


def test_llm_first_offer_is_sent_as_offer():
    decision = decide(situation(), reply("COUNTER_OFFER", 500, date(2026, 10, 18)))
    assert result(decision) == (M.OFFER, (500, date(2026, 10, 18))) and decision.source == LLM


def test_llm_cannot_change_required_date_or_priority():
    decision = decide(situation(), reply("COUNTER_OFFER", 500, date(2026, 10, 18), required_date="2026-11-30", priority=5))
    assert (decision.terms.required_date, decision.terms.priority) == (REQUIRED, 1)


@pytest.mark.parametrize(
    "s, llm, expected",
    [
        (situation(), reply("ACCEPT"), M.OFFER),  # nothing to accept yet
        (situation(), reply("REJECT"), M.OFFER),  # a supplier can cover the shortage
        (situation(), reply("COUNTER_OFFER", 150, date(2026, 10, 18)), M.OFFER),  # below MOQ and shortage
        (situation(), reply("COUNTER_OFFER", 500, date(2026, 10, 10)), M.OFFER),  # earlier than the lead time allows
        (situation(), reply("COUNTER_OFFER", 500, date(2026, 10, 30)), M.OFFER),  # after required_by
        (countered(500, date(2026, 10, 30)), reply("ACCEPT"), M.COUNTER_OFFER),  # late terms cannot be accepted
        (countered(550, date(2026, 10, 20)), reply("REJECT"), M.AGREEMENT_PROPOSED),  # acceptable terms not discarded
        (countered(550, date(2026, 10, 20)), reply("COUNTER_OFFER", 550, date(2026, 10, 20)), M.AGREEMENT_PROPOSED),
        (countered(550, date(2026, 10, 20), 3), reply("COUNTER_OFFER", 500, date(2026, 10, 18)), M.AGREEMENT_PROPOSED),
        (countered(500, date(2026, 10, 30), 3), reply("REJECT"), M.COUNTER_OFFER),  # round exhaustion is FAILED
    ],
)
def test_invalid_llm_proposal_is_replaced_by_policy(s, llm, expected):
    decision = decide(s, llm)
    assert decision.message_type == expected
    assert decision.source == POLICY and decision.llm_problems and decision.llm_proposal is not None


def test_llm_price_field_is_refused():
    llm = FakeLLMClient(['{"action": "COUNTER_OFFER", "terms": {"quantity": 500, "delivery_date": "2026-10-20", '
                         '"price": 9}, "rationale": "x"}'])
    decision = decide(situation(), llm)
    assert decision.source == POLICY and "no usable LLM proposal" in decision.llm_problems[0]
    assert "price" not in (decision.terms.model_dump() if decision.terms else {})
