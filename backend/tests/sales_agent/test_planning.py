"""The contact point to Planning (fake Planning, the answer rules, the request shape) and the reply checker.
No database needed."""

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.sales_agent.planning import (
    FakePlanning, OfferedOption, PlanningResult, build_request, check_result_against_request, options_reply,
)
from app.sales_agent.rules import allowed_values, check_options_presented, check_reply_values

ASKED_FOR = date(2026, 11, 10)


def request(quantity, **order):
    return {"request_ref": "REQ-1", "order": {"quantity": quantity, "requested_date": ASKED_FOR.isoformat(), **order}}


def test_the_fake_planning_answers_by_the_quantity_asked():
    def answer(quantity):
        return FakePlanning.answer_for(request(quantity))

    assert [(o.kind, o.quantity, o.delivery_date) for o in answer(500).options] == [("REQUESTED", 500, ASKED_FOR)]
    assert [(o.kind, o.quantity, o.delivery_date) for o in answer(800).options] == [
        ("LATER_DATE", 800, date(2026, 11, 24)), ("LESS_QUANTITY", 500, ASKED_FOR)]
    assert [(o.kind, o.delivery_date) for o in answer(3000).options] == [("LATER_DATE", date(2026, 12, 10))]
    assert answer(9000).status == "NOTHING_FEASIBLE" and answer(77).status == "NEEDS_STAFF"
    assert answer(13) is None  # never answers

    # With no delay the answer is delivered in the same call; with nothing to deliver to, nothing happens.
    delivered = []
    FakePlanning(deliver=delivered.append, delay_seconds=0).send_request(request(800))
    FakePlanning(delay_seconds=0).send_request(request(800))
    assert [r.status for r in delivered] == ["READY"]


def test_planning_answers_are_checked_for_shape_and_for_consistency_with_the_request():
    option = {"kind": "REQUESTED", "quantity": 500, "delivery_date": "2026-11-10"}

    # Shape: READY needs options, other statuses must not have them, quantities are above zero, kinds are known.
    with pytest.raises(ValidationError):
        PlanningResult(request_ref="R", status="READY")
    with pytest.raises(ValidationError):
        PlanningResult(request_ref="R", status="NOTHING_FEASIBLE", options=[option])
    with pytest.raises(ValidationError):
        PlanningResult(request_ref="R", status="READY", options=[{**option, "quantity": 0}])
    with pytest.raises(ValidationError):
        PlanningResult(request_ref="R", status="READY", options=[{**option, "kind": "PART_NOW_REST_LATER"}])

    # Consistency: each kind of option must look like what it says, and a kind appears once.
    order = request(800)["order"]
    def problems(*options):
        return check_result_against_request(PlanningResult(request_ref="R", status="READY", options=list(options)), order)

    later = OfferedOption(kind="LATER_DATE", quantity=800, delivery_date=date(2026, 11, 24))
    less = OfferedOption(kind="LESS_QUANTITY", quantity=500, delivery_date=ASKED_FOR)
    assert problems(later, less) == []
    assert problems(OfferedOption(kind="LATER_DATE", quantity=800, delivery_date=ASKED_FOR))  # not later
    assert problems(OfferedOption(kind="LESS_QUANTITY", quantity=900, delivery_date=ASKED_FOR))  # not less
    assert problems(OfferedOption(kind="REQUESTED", quantity=500, delivery_date=ASKED_FOR))  # not what was asked
    assert problems(later, later)  # twice the same kind


def test_the_request_to_planning_has_no_price_or_priority_and_a_bounded_customer_summary():
    orders = [{"order_number": f"SA-{n}"} for n in range(8)]
    memory = ([{"type": "FREQUENT_PRODUCT", "scope": "GENERAL", "source": "INFERRED"}] * 5
              + [{"type": "PREFERS_WHATSAPP_UPDATES", "scope": "GENERAL", "source": "STATED"}])
    info = {"found": True, "customer": {"id": "c-1", "name": "Asha", "phone": "+100"}, "memory": memory}

    known = build_request("REQ-1", "i-1", "+100", info, orders, "p-1", "SmartPhone X1", Decimal("500"), ASKED_FOR,
                          date(2026, 10, 15))
    unknown = build_request("REQ-2", "i-2", "+200", {"found": False}, [], "p-1", "SmartPhone X1", Decimal("500"),
                            ASKED_FOR, date(2026, 10, 15))

    assert known["order"] == {"product_id": "p-1", "product_name": "SmartPhone X1", "quantity": 500,
                              "requested_date": "2026-11-10", "order_date": "2026-10-15"}
    context = known["customer_context"]
    assert len(context["recent_orders"]) == 5 and len(context["insights"]) == 3 and len(context["preferences"]) == 1
    assert unknown["customer"] == {"id": None, "phone": "+200", "name": None}
    assert unknown["customer_context"]["is_known_customer"] is False
    for text in (json.dumps(known).lower(), json.dumps(unknown).lower()):
        assert "price" not in text and "cost" not in text and "priority" not in text  # Sales never sends these


def test_the_reply_checker_catches_invented_dates_and_numbers_and_missing_options():
    allowed = allowed_values(
        ["I need 500 units by December 10", "SmartPhone X1 please"], None,
        [(Decimal(300), date(2026, 12, 24)), (Decimal(500), date(2026, 12, 10))],
    )

    # Real values pass, written in different ways, and product names with digits are not numbers.
    for fine in ("So 500 SmartPhone X1 by December 10, 2026.", "A) 300 x SmartPhone X1 by 2026-12-24. B) 500 by 10 December",
                 "Option 2 is 300 units on Dec 24th.", "We offer SmartPhone X2 and Tablet T1."):
        assert check_reply_values(fine, allowed) == [], fine

    # Anything invented is caught: a date, a calculated number, a thousands separator.
    assert check_reply_values("We can deliver by December 12.", allowed)
    assert check_reply_values("That is 14 days later.", allowed)
    assert check_reply_values("About 1,000 units.", allowed)
    assert check_reply_values("Delivery on 2026-12-31.", allowed)

    # When options are explained, every option must be presented.
    both = [(Decimal(300), date(2026, 12, 24)), (Decimal(500), date(2026, 12, 10))]
    assert check_options_presented("300 units by December 24 or 500 units by December 10.", both) == []
    assert len(check_options_presented("300 units by December 24.", both)) == 1
    assert len(check_options_presented("Which one would you like?", both)) == 2

    # Our own text for options is written from the values only, so it always passes the same checks.
    own_text = options_reply([("LATER_DATE", Decimal(300), date(2026, 12, 24)), ("LESS_QUANTITY", Decimal(500), date(2026, 12, 10))],
                             "SmartPhone X1")
    assert check_reply_values(own_text, allowed) == [] and check_options_presented(own_text, both) == []
