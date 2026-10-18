"""Purchasing's decision on one supplier reply (`negotiation.validate`): the clarification limit and counter-offers
with an unstated term. Plain code: no database. The API seam (N5) is in db/test_deadlines_abort_api.py."""

from datetime import date
from decimal import Decimal

from app.purchasing_agent.interpretation import SupplierReply
from app.purchasing_agent.negotiation import validate

REQUIRED = date(2026, 11, 20)
TODAY = date(2026, 11, 2)


def decide(reply, rounds_left=2, clarifications_left=2):
    return validate(reply, Decimal(500), REQUIRED, REQUIRED, rounds_left, clarifications_left, today=TODAY)


def test_an_unclear_reply_asks_for_clarification_while_clarifications_are_left():
    assert decide(None, clarifications_left=1).outcome == "CLARIFICATION_REQUEST"


def test_an_unclear_reply_with_no_clarifications_left_fails_the_leg():
    decision = decide(None, clarifications_left=0)
    assert (decision.outcome, decision.reason) == ("FAILED", "unclear_response")


def test_an_unclear_reply_does_not_depend_on_the_rounds_left():
    assert decide(None, rounds_left=0, clarifications_left=2).outcome == "CLARIFICATION_REQUEST"


def test_a_readable_reply_is_decided_even_with_no_clarifications_left():
    decision = decide(SupplierReply("ACCEPT", None, None), clarifications_left=0)
    assert decision.outcome == "AGREED"


# A counter-offer the LLM read with a term unstated (the supplier didn't write it; it is never invented).


def test_a_counter_with_another_quantity_and_no_date_is_reallocated():
    decision = decide(SupplierReply("COUNTER", Decimal(250), None))
    assert (decision.outcome, decision.quantity) == ("REALLOCATE", Decimal(250))


def test_a_counter_with_a_late_date_and_no_quantity_is_countered_with_the_required_date():
    decision = decide(SupplierReply("COUNTER", None, date(2026, 11, 25)))
    assert (decision.outcome, decision.quantity, decision.delivery_date) == ("COUNTER_OFFER", Decimal(500), REQUIRED)


def test_a_counter_that_leaves_the_deciding_term_unstated_asks_for_clarification():
    assert decide(SupplierReply("COUNTER", Decimal(500), None)).outcome == "CLARIFICATION_REQUEST"
    assert decide(SupplierReply("COUNTER", None, date(2026, 11, 15))).outcome == "CLARIFICATION_REQUEST"


def test_a_counter_with_an_unstated_term_and_no_clarifications_left_fails_the_leg():
    decision = decide(SupplierReply("COUNTER", Decimal(500), None), clarifications_left=0)
    assert (decision.outcome, decision.reason) == ("FAILED", "unclear_response")


# A delivery date before today is never agreed (confirmed 2026-10-18, code review): handled like a late date.


def test_a_counter_with_a_past_date_is_countered_with_the_required_date():
    for reply in (SupplierReply("COUNTER", Decimal(500), date(2026, 11, 1)),
                  SupplierReply("COUNTER", None, date(2025, 11, 12))):
        decision = decide(reply)
        assert (decision.outcome, decision.quantity, decision.delivery_date) == (
            "COUNTER_OFFER", Decimal(500), REQUIRED), reply


def test_a_counter_with_a_past_date_and_no_rounds_left_fails_the_leg():
    decision = decide(SupplierReply("COUNTER", Decimal(500), date(2026, 11, 1)), rounds_left=0)
    assert (decision.outcome, decision.reason) == ("FAILED", "round_limit_exceeded")


def test_delivery_today_is_not_in_the_past():
    assert decide(SupplierReply("COUNTER", Decimal(500), TODAY)).outcome == "AGREED"
