"""Checks on what the customer tells us. Plain functions: no database and no clock (the caller passes `today`).

The language model only suggests details. This code decides whether they are valid.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from app.sales_agent.agent import AgentTurn, Details
from app.sales_agent.models import Product

MAX_QUESTIONS_PER_REPLY = 2

# The next steps the chatting model may choose, by inquiry stage. Only GATHERING may start a request to Planning.
# Choosing, confirming and declining are never chosen here: a separate classification decides them (decision_to_step).
ALLOWED_STEPS = {
    "GATHERING": {"ask_more", "send_request", "pass_to_staff"},
    "WAITING_FOR_PLANNING": {"ask_more", "pass_to_staff"},
    "OPTIONS_PRESENTED": {"ask_more", "pass_to_staff"},
    "AWAITING_CONFIRMATION": {"ask_more", "pass_to_staff"},
    "NEEDS_STAFF": {"ask_more", "pass_to_staff"},
}

# The only preferences a customer can ask us to remember (the database allows the same list). There is deliberately no
# "tolerates delay" or "flexible" type: what a customer accepted once must never become a reason to treat them worse.
PREFERENCE_TYPES = ("PREFERS_WHATSAPP_UPDATES", "WANTS_EARLY_DATE_CHANGE_NOTICE")

# FREQUENT_PRODUCT insight: the same product in at least this many of the customer's last orders.
FREQUENT_PRODUCT_WINDOW = 10
FREQUENT_PRODUCT_MIN_ORDERS = 3

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


def read_preference(suggestion) -> tuple[str, str] | None:
    """The preference type and scope (GENERAL or THIS_ORDER) if the model's suggestion is on the allowed list."""
    if suggestion is None:
        return None
    kind = suggestion.type.strip().upper().replace(" ", "_")
    if kind not in PREFERENCE_TYPES:
        return None
    return kind, "THIS_ORDER" if suggestion.applies_to == "this_order" else "GENERAL"


def frequent_product(product_ids: Sequence[str]) -> tuple[str, int, str] | None:
    """The insight rule: (product id, number of orders, strength) if one product is in at least three of the last ten
    orders (given newest first), else None. It looks at products only, never at delays or dates."""
    counts: dict[str, int] = {}
    for product_id in product_ids[:FREQUENT_PRODUCT_WINDOW]:
        counts[product_id] = counts.get(product_id, 0) + 1
    if not counts:
        return None
    best = max(counts, key=lambda product_id: counts[product_id])  # a tie goes to the more recently ordered product
    if counts[best] < FREQUENT_PRODUCT_MIN_ORDERS:
        return None
    return best, counts[best], "HIGH" if counts[best] >= 5 else "MEDIUM" if counts[best] >= 4 else "LOW"


def is_action_allowed(stage: str, step: str) -> bool:
    return step in ALLOWED_STEPS.get(stage, set())


MAX_WORDS_IN_A_PLAIN_YES = 8


def is_plain_agreement(text: str) -> bool:
    """A "yes" that can become an order must be short and contain no number: "yes but make it 300" is a change."""
    return not re.search(r"\d", text) and len(text.split()) <= MAX_WORDS_IN_A_PLAIN_YES


def decision_to_step(decision, stage: str, option_letters: str, customer_text: str) -> tuple[str, str | None] | None:
    """What a classified reply means: ("select_option", letter), ("confirm_order", None), ("decline", None), or None
    when the chatting model should simply answer. Anything uncertain gives None, so nothing happens by accident."""
    if decision.decision == "no":
        return "decline", None
    if decision.decision == "choose":
        letter = (decision.option or "").strip().upper()
        return ("select_option", letter) if letter and letter in option_letters else None
    if decision.decision == "yes" and is_plain_agreement(customer_text):
        if stage == "AWAITING_CONFIRMATION":
            return "confirm_order", None
        if stage == "OPTIONS_PRESENTED" and len(option_letters) == 1:  # only one option: a yes can only mean that one
            return "select_option", option_letters
    return None


def confirmation_problem(
    stage: str, option_chosen: bool, offer_valid_until: datetime | None, now: datetime, messages_at_once: int,
    last_reply: str | None, confirmation_question: str,
) -> str | None:
    """Why a "yes" cannot become an order yet, or None if it can. This is the guard at the riskiest moment: the model
    only says the customer sounded like they said yes, and these rules decide whether that is enough.

    The "yes" must be the one message answering our question, and our last words before it must be exactly the
    question that repeats the quantity, the date and the payment note.
    """
    if stage != "AWAITING_CONFIRMATION" or not option_chosen:
        return "no option is waiting for a confirmation"
    if offer_valid_until is None or now > offer_valid_until:
        return "the offer has expired"
    if messages_at_once != 1:
        return "more than one message arrived at once"
    if last_reply != confirmation_question:
        return "the customer was not answering our confirmation question"
    return None


def check_ai_output(
    turn: AgentTurn, stage: str, merge: MergeResult, allowed: "AllowedValues | None" = None,
    must_present: "Iterable[tuple[Decimal, date]]" = (),
) -> list[str]:
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
    if allowed is not None:
        problems += check_reply_values(turn.reply, allowed)
    problems += check_options_presented(turn.reply, must_present)
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


# -- every date and number in a reply must come from somewhere we trust ---------------------------------------------

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6,
    "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_NAME = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_FIRST = re.compile(rf"\b({_MONTH_NAME})\.?\s+(\d{{1,2}})(?!\d)(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.I)
_DAY_FIRST = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_NAME})\b\.?(?:,?\s+(\d{{4}}))?", re.I)
_OPTION_LABEL = re.compile(r"\boptions?\s+[a-z0-9]\b", re.I)  # "option A" or "option 2" is a label, not a quantity
_NUMBER = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?(?!\w)")

DateFact = tuple[int, int, int | None]  # month, day, year (the year may be missing)


@dataclass
class AllowedValues:
    """The numbers and dates a reply may contain."""

    numbers: set[Decimal] = field(default_factory=set)
    dates: set[DateFact] = field(default_factory=set)


def _dates_in(text: str) -> tuple[list[tuple[str, DateFact]], str]:
    """The dates written in the text (as written, and as month/day/year), and the text with them removed."""
    found: list[tuple[str, DateFact]] = []

    def take(pattern, to_fact, text):
        def replace(match):
            fact = to_fact(match)
            if fact is not None:
                found.append((match.group(0).strip(), fact))
                return " "
            return match.group(0)
        return pattern.sub(replace, text)

    def valid(month, day, year):
        return (month, day, year) if 1 <= month <= 12 and 1 <= day <= 31 else None

    text = take(_ISO_DATE, lambda m: valid(int(m[2]), int(m[3]), int(m[1])), text)
    text = take(_MONTH_FIRST, lambda m: valid(_MONTHS[m[1].lower()], int(m[2]), int(m[3]) if m[3] else None), text)
    text = take(_DAY_FIRST, lambda m: valid(_MONTHS[m[2].lower()], int(m[1]), int(m[3]) if m[3] else None), text)
    return found, text


def _numbers_in(text: str) -> list[Decimal]:
    text = _OPTION_LABEL.sub(" ", text)
    return [Decimal(match.replace(",", "")) for match in _NUMBER.findall(text)]


def facts_in(text: str) -> tuple[set[Decimal], set[DateFact]]:
    dates, rest = _dates_in(text)
    return set(_numbers_in(rest)), {fact for _, fact in dates}


def allowed_values(
    customer_texts: Iterable[str], collected: CollectedDetails | None, options: Iterable[tuple[Decimal, date]]
) -> AllowedValues:
    """What a reply may say: what the customer wrote, the collected details, and Planning's options."""
    allowed = AllowedValues()
    for text in customer_texts:
        numbers, dates = facts_in(text)
        allowed.numbers |= numbers
        allowed.dates |= dates
    if collected is not None:
        if collected.quantity is not None:
            allowed.numbers.add(collected.quantity)
        if collected.requested_date is not None:
            allowed.dates.add((collected.requested_date.month, collected.requested_date.day, collected.requested_date.year))
    for quantity, day in options:
        allowed.numbers.add(Decimal(quantity))
        allowed.dates.add((day.month, day.day, day.year))
    return allowed


def _date_is_allowed(fact: DateFact, allowed: AllowedValues) -> bool:
    month, day, year = fact
    return any(
        (m, d) == (month, day) and (year is None or y is None or year == y) for m, d, y in allowed.dates
    )


def check_reply_values(reply: str, allowed: AllowedValues) -> list[str]:
    """Every date and number in the reply must be one we were given. This is what stops the agent inventing a date."""
    dates, rest = _dates_in(reply)
    problems = [
        f"The date '{written}' in your reply is not one of the dates you were given. Use only given dates."
        for written, fact in dates if not _date_is_allowed(fact, allowed)
    ]
    for number in _numbers_in(rest):
        if number not in allowed.numbers:
            problems.append(f"The number {number.normalize():f} in your reply is not one of the numbers you were given.")
    return problems


def check_options_presented(reply: str, options: Iterable[tuple[Decimal, date]]) -> list[str]:
    """When options are explained, the reply must present every one of them (its quantity and its date)."""
    numbers, dates = facts_in(reply)
    days_in_reply = {(month, day) for month, day, _ in dates}
    return [
        f"Your reply must present the option of {Decimal(quantity).normalize():f} on {day.isoformat()}."
        for quantity, day in options
        if Decimal(quantity) not in numbers or (day.month, day.day) not in days_in_reply
    ]
