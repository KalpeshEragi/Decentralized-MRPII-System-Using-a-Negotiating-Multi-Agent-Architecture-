"""Checks on what the customer tells us. Plain functions: no database and no clock (the caller passes `today`).

The language model only suggests details. This code decides whether they are valid.
"""

import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from app.sales_agent.agent import AgentTurn, Details
from app.sales_agent.models import Product

MAX_QUESTIONS_PER_REPLY = 2

# The next steps the model may choose, by inquiry stage. Only the first stage is in use so far.
ALLOWED_STEPS = {"GATHERING": {"ask_more", "send_request", "pass_to_staff"}}

FIELD_LABELS = {"product": "product", "quantity": "quantity", "requested_date": "delivery date"}


class Problem(BaseModel):
    field: str  # "product", "quantity" or "requested_date"
    message: str


class OrderDetailsCheck(BaseModel):
    """The result of checking product, quantity and date. The cleaned-up values are filled in only when they are valid."""

    valid: bool
    problems: list[Problem]
    product_id: str | None = None
    product_name: str | None = None
    quantity: Decimal | None = None
    requested_date: date | None = None


def normalize_phone(phone: str) -> str:
    """Remove spaces, dashes, dots and brackets, so "+91 98765-43210" and "+919876543210" are the same number."""
    return re.sub(r"[\s\-.()]", "", phone)


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _find_product(products: Sequence[Product], text: str) -> tuple[Product | None, str | None]:
    """The one product whose name or product code matches the text (ignoring capitals and extra spaces)."""
    wanted = _normalize_text(text)
    matches = [p for p in products if wanted in (_normalize_text(p.name), _normalize_text(p.sku))]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"is not one of our products ('{text.strip()}')"
    return None, f"matches more than one product ('{text.strip()}')"


def _read_quantity(value) -> tuple[Decimal | None, str | None]:
    if isinstance(value, bool):  # True would otherwise count as the number 1
        return None, "must be a number"
    try:
        quantity = Decimal(str(value).strip())
    except InvalidOperation:
        return None, "must be a number"
    if not quantity.is_finite():
        return None, "must be a number"
    if quantity <= 0:
        return None, "must be above 0"
    return quantity, None


def _read_date(value, today: date) -> tuple[date | None, str | None]:
    if isinstance(value, date):
        requested = value
    else:
        text = str(value).strip()
        # Only the form YYYY-MM-DD. (date.fromisoformat alone would also accept forms like 20261110 or 2026-W45-2.)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return None, "must be a date written as YYYY-MM-DD"
        try:
            requested = date.fromisoformat(text)
        except ValueError:  # the right form but not a real day, like 2026-13-40
            return None, "must be a date written as YYYY-MM-DD"
    if requested < today:
        return None, "is in the past"
    return requested, None


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def check_order_details(
    products: Sequence[Product], product, quantity, requested_date, today: date
) -> OrderDetailsCheck:
    """Check all three details and report every problem at once, so the customer can fix them in one message.

    `products` are the products we can sell. `today` is passed in, so the result never depends on the clock.
    """
    problems: list[Problem] = []
    found_product = None
    read_quantity = None
    read_date = None

    for field, value in (("product", product), ("quantity", quantity), ("requested_date", requested_date)):
        if _is_missing(value):
            problems.append(Problem(field=field, message="is missing"))

    if not _is_missing(product):
        found_product, problem = _find_product(products, str(product))
        if problem:
            problems.append(Problem(field="product", message=problem))
    if not _is_missing(quantity):
        read_quantity, problem = _read_quantity(quantity)
        if problem:
            problems.append(Problem(field="quantity", message=problem))
    if not _is_missing(requested_date):
        read_date, problem = _read_date(requested_date, today)
        if problem:
            problems.append(Problem(field="requested_date", message=problem))

    if problems:
        return OrderDetailsCheck(valid=False, problems=problems)
    return OrderDetailsCheck(
        valid=True,
        problems=[],
        product_id=str(found_product.id),
        product_name=found_product.name,
        quantity=read_quantity,
        requested_date=read_date,
    )


# -- what is collected so far, and checking the language model's answer ---------------------------------------------


class CollectedDetails(BaseModel):
    """The order details known so far for the current inquiry. Each one can still be missing."""

    product_id: str | None = None
    product_name: str | None = None
    quantity: Decimal | None = None
    requested_date: date | None = None

    def missing_fields(self) -> list[str]:
        missing = []
        if self.product_id is None:
            missing.append("product")
        if self.quantity is None:
            missing.append("quantity")
        if self.requested_date is None:
            missing.append("requested_date")
        return missing

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields()


class MergeResult(BaseModel):
    collected: CollectedDetails
    problems: list[Problem]


def merge_details(
    products: Sequence[Product], current: CollectedDetails, suggested: Details, today: date
) -> MergeResult:
    """Put the details the model suggested on top of what is already collected.

    Only valid values are accepted. A wrong value is reported as a problem and the old value stays. A detail the
    model leaves out (null) never erases what we already know.
    """
    collected = current.model_copy()
    problems: list[Problem] = []

    if not _is_missing(suggested.product):
        product, problem = _find_product(products, str(suggested.product))
        if problem:
            problems.append(Problem(field="product", message=problem))
        else:
            collected.product_id, collected.product_name = str(product.id), product.name
    if not _is_missing(suggested.quantity):
        quantity, problem = _read_quantity(suggested.quantity)
        if problem:
            problems.append(Problem(field="quantity", message=problem))
        else:
            collected.quantity = quantity
    if not _is_missing(suggested.requested_date):
        requested_date, problem = _read_date(suggested.requested_date, today)
        if problem:
            problems.append(Problem(field="requested_date", message=problem))
        else:
            collected.requested_date = requested_date

    return MergeResult(collected=collected, problems=problems)


def is_action_allowed(stage: str, step: str) -> bool:
    return step in ALLOWED_STEPS.get(stage, set())


def check_ai_output(turn: AgentTurn, stage: str, merge: MergeResult) -> list[str]:
    """What is wrong with the model's answer, as plain sentences. An empty list means the answer can be used.

    The sentences are also what the model is told when it is asked to answer again.
    """
    problems = []
    if not is_action_allowed(stage, turn.next_step):
        problems.append(f"The next_step '{turn.next_step}' is not allowed now.")
    question_count = turn.reply.count("?")
    if question_count > MAX_QUESTIONS_PER_REPLY:
        problems.append(f"Your reply has {question_count} questions. Ask at most {MAX_QUESTIONS_PER_REPLY}.")
    for problem in merge.problems:
        problems.append(f"The {FIELD_LABELS[problem.field]} in details is wrong: it {problem.message}.")
    if turn.next_step == "send_request" and not merge.collected.is_complete:
        missing = ", ".join(merge.collected.missing_fields())
        problems.append(
            f"You chose send_request, but these details are still missing: {missing}. If the customer gave them in "
            "their latest message, write them in details. Otherwise choose ask_more and ask for them."
        )
    return problems


_QUESTION_FOR_FIELD = {
    "product": "Which product would you like? We offer: {products}.",
    "quantity": "How many units do you need?",
    "requested_date": "By what date would you like it delivered? Please give a date that is not in the past.",
}


_WHAT_WAS_WRONG = {
    "product": "I could not find that product.",
    "quantity": "That quantity does not look right.",
    "requested_date": "I could not use that delivery date. It may be in the past.",
}


def fallback_reply(wrong_fields: list[str], missing_fields: list[str], product_names: list[str]) -> str:
    """A safe reply written by our code. It says what could not be used and asks for it again, at most two questions.

    Used when a detail the customer gave is wrong (the model cannot fix that), and when the model's answer could not
    be used even after a second try.
    """
    to_ask = (wrong_fields + [field for field in missing_fields if field not in wrong_fields])[:MAX_QUESTIONS_PER_REPLY]
    opening = " ".join(_WHAT_WAS_WRONG[field] for field in wrong_fields) or "Sorry, I did not quite get that."
    if not to_ask:
        return f"{opening} Could you say that again, please?"
    questions = [_QUESTION_FOR_FIELD[field].format(products=", ".join(product_names)) for field in to_ask]
    return " ".join([opening, *questions])
