"""The rules that check what the customer and the language model give us. Plain code: no database needed."""

import uuid
from datetime import date
from decimal import Decimal

from app.sales_agent.agent import AgentTurn, Details
from app.sales_agent.models import Product
from app.sales_agent.rules import (
    CollectedDetails, check_ai_output, check_order_details, fallback_reply, merge_details,
)

TODAY = date(2026, 10, 15)
X1 = Product(id=uuid.uuid4(), sku="X1-PHONE", name="SmartPhone X1")
X2 = Product(id=uuid.uuid4(), sku="X2-PHONE", name="SmartPhone X2")
PRODUCTS = [X1, X2]


def check(product="SmartPhone X1", quantity=500, requested_date="2026-11-10", products=PRODUCTS):
    return check_order_details(products, product, quantity, requested_date, TODAY)


def problem_fields(result) -> list[str]:
    return [problem.field for problem in result.problems]


def merge(current=None, **suggested):
    return merge_details(PRODUCTS, current or CollectedDetails(), Details(**suggested), TODAY)


def test_valid_order_details_are_cleaned_up_and_the_product_is_found_by_name_or_code():
    result = check(product="  smartphone   X1 ", quantity=" 500 ", requested_date="2026-11-10")

    assert result.valid is True
    assert (result.product_id, result.product_name) == (str(X1.id), "SmartPhone X1")
    assert (result.quantity, result.requested_date) == (Decimal("500"), date(2026, 11, 10))
    assert check(product="x2-phone").product_id == str(X2.id)  # by product code
    assert check(requested_date=TODAY).valid is True  # today is allowed; Planning decides if it is possible


def test_wrong_or_missing_details_are_all_reported_and_nothing_is_guessed():
    # Every problem is reported at once, so the customer can fix them in a single message.
    result = check(product="Banana", quantity=-1, requested_date="2020-01-01")
    assert problem_fields(result) == ["product", "quantity", "requested_date"]
    assert (result.valid, result.product_id, result.quantity, result.requested_date) == (False, None, None, None)

    # Two products with the same name: refuse instead of picking one.
    same_name = Product(id=uuid.uuid4(), sku="X1-OTHER", name="smartphone x1")
    assert problem_fields(check(products=[X1, same_name])) == ["product"]

    # Quantities that are not a real number above zero. True would silently count as 1.
    for bad_quantity in (0, "0", -5, "many", "5 hundred", float("nan"), float("inf"), True, [500]):
        assert problem_fields(check(quantity=bad_quantity)) == ["quantity"], bad_quantity

    # Dates in the past, or not written exactly as YYYY-MM-DD (Python alone would accept 20261110 and 2026-W45-2).
    for bad_date in ("2026-10-14", "tomorrow", "10/11/2026", "2026-13-40", "20261110", "2026-W45-2", 20261110):
        assert problem_fields(check(requested_date=bad_date)) == ["requested_date"], bad_date

    # Empty is "missing", not "wrong".
    for empty in (None, "", "   "):
        assert [(p.field, p.message) for p in check(product=empty).problems] == [("product", "is missing")]


def test_new_details_are_merged_safely_into_what_is_already_collected():
    known = CollectedDetails(product_id=str(X1.id), product_name="SmartPhone X1", quantity=Decimal("500"))

    # The model leaves out what it does not know: that never erases what we have.
    result = merge(known, requested_date="2026-11-10")
    assert result.collected.is_complete and result.collected.quantity == Decimal("500")

    # A customer correction replaces the old value.
    assert merge(known, quantity=300).collected.quantity == Decimal("300")

    # A wrong suggestion is reported, and the old value stays.
    wrong = merge(known, quantity=-5, requested_date="2020-01-01", product="Banana")
    assert [p.field for p in wrong.problems] == ["product", "quantity", "requested_date"]
    assert wrong.collected.quantity == Decimal("500") and wrong.collected.product_name == "SmartPhone X1"

    assert CollectedDetails(quantity=Decimal("5")).missing_fields() == ["product", "requested_date"]


def test_a_bad_model_answer_is_caught_and_the_safe_reply_asks_for_what_is_wrong():
    def turn(reply="Which product do you need?", next_step="ask_more", **details):
        return AgentTurn(reply=reply, next_step=next_step, details=Details(**details))

    everything = merge(product="SmartPhone X1", quantity=500, requested_date="2026-11-10")

    assert check_ai_output(turn(), "GATHERING", merge()) == []
    assert check_ai_output(turn(next_step="send_request"), "GATHERING", everything) == []
    assert check_ai_output(turn(), "CLOSED", merge()) == ["The next_step 'ask_more' is not allowed now."]
    assert check_ai_output(turn(reply="Which model? How many? By when?"), "GATHERING", merge()) == [
        "Your reply has 3 questions. Ask at most 2."]
    # Telling the customer "I will check with planning" while a detail is missing would be a false claim.
    incomplete = merge(product="SmartPhone X1", quantity=500)
    [problem] = check_ai_output(turn(next_step="send_request"), "GATHERING", incomplete)
    assert problem.startswith("You chose send_request, but these details are still missing: requested_date.")
    assert "write them in details" in problem  # the model is told how to fix it
    assert check_ai_output(turn(), "GATHERING", merge(quantity=0)) == [
        "The quantity in details is wrong: it must be above 0."]

    names = ["SmartPhone X1", "SmartPhone X2"]
    assert fallback_reply(["quantity"], ["product", "quantity", "requested_date"], names) == (
        "That quantity does not look right. How many units do you need? "
        "Which product would you like? We offer: SmartPhone X1, SmartPhone X2."  # at most two questions
    )
    assert fallback_reply(["requested_date"], [], names).startswith("I could not use that delivery date.")
    assert fallback_reply([], [], names) == "Sorry, I did not quite get that. Could you say that again, please?"


def test_a_yes_becomes_an_order_only_when_every_guard_passes():
    from datetime import datetime, timedelta, timezone

    from app.sales_agent.rules import confirmation_problem

    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    question = "Just to be sure: ... Shall I confirm this order?"
    good = dict(stage="AWAITING_CONFIRMATION", option_chosen=True, offer_valid_until=now + timedelta(hours=1), now=now,
                messages_at_once=1, last_reply=question, confirmation_question=question)

    assert confirmation_problem(**good) is None
    for broken in ({"stage": "OPTIONS_PRESENTED"}, {"option_chosen": False}, {"offer_valid_until": now - timedelta(seconds=1)},
                   {"offer_valid_until": None}, {"messages_at_once": 2}, {"last_reply": "You can ask me anything."},
                   {"last_reply": None}):
        assert confirmation_problem(**{**good, **broken}), broken
