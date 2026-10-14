"""The order-details check and phone cleaning. No database needed."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.sales_agent.models import Product
from app.sales_agent.rules import check_order_details, normalize_phone

TODAY = date(2026, 10, 15)
X1 = Product(id=uuid.uuid4(), sku="X1-PHONE", name="SmartPhone X1")
X2 = Product(id=uuid.uuid4(), sku="X2-PHONE", name="SmartPhone X2")
PRODUCTS = [X1, X2]


def check(product="SmartPhone X1", quantity=500, requested_date="2026-11-10", products=PRODUCTS):
    return check_order_details(products, product, quantity, requested_date, TODAY)


def problem_fields(result) -> list[str]:
    return [problem.field for problem in result.problems]


# -- phone numbers --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("+919876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("+91-98765-43210", "+919876543210"),
        ("(+91) 98765.43210", "+919876543210"),
        ("  +100  ", "+100"),
    ],
)
def test_phone_numbers_are_cleaned_the_same_way(typed, expected):
    assert normalize_phone(typed) == expected


# -- valid details --------------------------------------------------------------------------------------------------


def test_valid_details_give_the_cleaned_up_values():
    result = check()

    assert result.valid is True
    assert result.problems == []
    assert result.product_id == str(X1.id)
    assert result.product_name == "SmartPhone X1"
    assert result.quantity == Decimal("500")
    assert result.requested_date == date(2026, 11, 10)


@pytest.mark.parametrize("typed", ["smartphone x1", "  SMARTPHONE   X1 ", "x1-phone", "X1-PHONE"])
def test_a_product_is_found_by_name_or_code_ignoring_capitals_and_spaces(typed):
    assert check(product=typed).product_id == str(X1.id)


@pytest.mark.parametrize("typed", [500, "500", " 500 ", 500.0, Decimal("500")])
def test_the_quantity_can_be_a_number_or_text_with_a_number(typed):
    assert check(quantity=typed).quantity == Decimal("500")


def test_the_date_can_be_a_date_or_text_and_today_is_allowed():
    assert check(requested_date=date(2026, 11, 10)).requested_date == date(2026, 11, 10)
    assert check(requested_date=TODAY).valid is True


# -- wrong details --------------------------------------------------------------------------------------------------


def test_an_unknown_product_is_refused():
    result = check(product="SmartPhone X9")

    assert result.valid is False
    assert problem_fields(result) == ["product"]
    assert "SmartPhone X9" in result.problems[0].message
    assert result.product_id is None


def test_a_product_that_matches_two_products_is_refused_instead_of_guessed():
    same_name = Product(id=uuid.uuid4(), sku="X1-OTHER", name="smartphone x1")

    result = check(products=[X1, same_name])

    assert problem_fields(result) == ["product"]
    assert "more than one" in result.problems[0].message


@pytest.mark.parametrize("bad_quantity", [0, -5, "0", "-1", "many", "5 hundred", float("nan"), float("inf"), True, [500]])
def test_a_quantity_that_is_not_a_number_above_zero_is_refused(bad_quantity):
    result = check(quantity=bad_quantity)

    assert problem_fields(result) == ["quantity"]


@pytest.mark.parametrize(
    "bad_date",
    ["2026-10-14", date(2026, 1, 1), "tomorrow", "10/11/2026", "2026-13-40", 20261110, "20261110", "2026-W45-2"],
)
def test_a_date_in_the_past_or_in_the_wrong_form_is_refused(bad_date):
    result = check(requested_date=bad_date)

    assert problem_fields(result) == ["requested_date"]


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_missing_details_are_reported_as_missing(empty):
    assert [(p.field, p.message) for p in check(product=empty).problems] == [("product", "is missing")]
    assert [(p.field, p.message) for p in check(quantity=empty).problems] == [("quantity", "is missing")]
    assert [(p.field, p.message) for p in check(requested_date=empty).problems] == [("requested_date", "is missing")]


def test_every_problem_is_reported_at_once():
    result = check(product="Banana", quantity=-1, requested_date="2020-01-01")

    assert problem_fields(result) == ["product", "quantity", "requested_date"]
    assert result.valid is False


def test_a_check_with_problems_gives_no_cleaned_up_values():
    result = check(quantity=-1)

    assert (result.product_id, result.quantity, result.requested_date) == (None, None, None)
