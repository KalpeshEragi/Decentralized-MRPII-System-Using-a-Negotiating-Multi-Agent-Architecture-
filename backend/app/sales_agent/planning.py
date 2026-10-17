"""The contact point to Planning: what Sales sends, what Planning answers, and a FAKE Planning for testing.

Planning is outside the Sales Agent and is not built yet. Sales sends a request (`build_request`) and Planning answers
later through door 3 (`PlanningResult`). Until the real Planning exists, `FakePlanning` answers with scripted results.
Sales never works out dates or quantities itself: it only passes on and explains what Planning says.
"""

import threading
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field, model_validator

MAX_RECENT_ORDERS_IN_CONTEXT = 5
MAX_INSIGHTS_IN_CONTEXT = 3
MAX_PREFERENCES_IN_CONTEXT = 10

# Part-now-rest-later is not offered yet (the plan cannot schedule two deliveries), so it is not accepted from Planning.
OptionKind = Literal["REQUESTED", "LATER_DATE", "LESS_QUANTITY"]
ResultStatus = Literal["READY", "WORKING", "NOTHING_FEASIBLE", "NEEDS_STAFF"]


# -- what Planning answers ------------------------------------------------------------------------------------------


class OfferedOption(BaseModel):
    kind: OptionKind
    quantity: Annotated[Decimal, Field(gt=0)]
    delivery_date: date
    reason_code: str | None = None  # why this option, for example SUPPLIER_LEAD_TIME


class PlanningResult(BaseModel):
    """Planning's answer to one request. Options are in the order Planning wants them shown."""

    request_ref: str
    status: ResultStatus
    options: list[OfferedOption] = []
    reason_code: str | None = None

    @model_validator(mode="after")
    def _options_only_when_ready(self) -> "PlanningResult":
        if self.status == "READY" and not self.options:
            raise ValueError("a READY result needs at least one option")
        if self.status != "READY" and self.options:
            raise ValueError(f"a {self.status} result must not have options")
        return self


def check_result_against_request(result: PlanningResult, order: dict) -> list[str]:
    """Is the answer consistent with what we asked? (This is not a feasibility check: that is Planning's job.)"""
    asked_quantity, asked_date = Decimal(str(order["quantity"])), date.fromisoformat(order["requested_date"])
    problems = []
    for option in result.options:
        if option.kind == "REQUESTED" and (option.quantity != asked_quantity or option.delivery_date != asked_date):
            problems.append("a REQUESTED option must have the asked quantity and date")
        if option.kind == "LATER_DATE" and (option.quantity != asked_quantity or option.delivery_date <= asked_date):
            problems.append("a LATER_DATE option must have the asked quantity and a later date")
        if option.kind == "LESS_QUANTITY" and (option.quantity >= asked_quantity or option.delivery_date != asked_date):
            problems.append("a LESS_QUANTITY option must have a smaller quantity and the asked date")
    if len({option.kind for option in result.options}) != len(result.options):
        problems.append("each kind of option may appear only once")
    return problems


# -- what Sales sends -----------------------------------------------------------------------------------------------


def build_request(
    request_ref: str, inquiry_id: str, phone: str, customer_info: dict, recent_orders: list[dict], product_id: str,
    product_name: str, quantity: Decimal, requested_date: date, today: date,
) -> dict:
    """The request to Planning: the order, and a small summary of what we know about the customer.

    The customer summary is for information only. It carries no price, no priority and no judgement about the customer.
    """
    known = customer_info.get("found", False)
    memory = customer_info.get("memory", [])
    return {
        "request_ref": request_ref,
        "inquiry_id": inquiry_id,
        "customer": {
            "id": customer_info["customer"]["id"] if known else None,
            "phone": phone,
            "name": customer_info["customer"]["name"] if known else None,
        },
        "order": {
            "product_id": product_id,
            "product_name": product_name,
            "quantity": int(quantity) if quantity == quantity.to_integral_value() else float(quantity),
            "requested_date": requested_date.isoformat(),
            "order_date": today.isoformat(),
        },
        "customer_context": {
            "is_known_customer": known,
            "recent_orders": recent_orders[:MAX_RECENT_ORDERS_IN_CONTEXT],
            "preferences": [_note(m) for m in memory if m["source"] == "STATED"][:MAX_PREFERENCES_IN_CONTEXT],
            "insights": [_note(m) for m in memory if m["source"] == "INFERRED"][:MAX_INSIGHTS_IN_CONTEXT],
            "open_questions": [],
        },
    }


def _note(memory_item: dict) -> dict:
    return {"type": memory_item["type"], "scope": memory_item["scope"], "source": memory_item["source"]}


# -- the connector, and a fake Planning for testing -----------------------------------------------------------------


class PlanningConnector(Protocol):
    def send_request(self, request: dict) -> None: ...

    def send_confirmation(self, notice: dict) -> None: ...


def new_request_ref() -> str:
    return f"REQ-{uuid.uuid4().hex[:12].upper()}"


class FakePlanning:
    """A FAKE Planning that answers by the quantity asked (so the tester can choose the scenario):

        up to 500     READY: the requested quantity by the requested date
        501 to 1000   READY: the full quantity later (+14 days), or 500 by the requested date
        1001 to 5000  READY: the full quantity later (+30 days) only
        above 5000    NOTHING_FEASIBLE
        77            NEEDS_STAFF
        13            never answers

    It is not authoritative: the real Planning will calculate these from capacity, stock and supplier terms.
    """

    def __init__(self, deliver: Callable[[PlanningResult], None] | None = None, delay_seconds: float = 2.0):
        self.deliver = deliver  # how an answer gets back to Sales (door 3)
        self.delay_seconds = delay_seconds  # 0 answers at once, in the same call (used by tests)
        self.confirmations: list[dict] = []  # the confirmation notices received (kept so a tester can look at them)

    def send_request(self, request: dict) -> None:
        result = self.answer_for(request)
        if result is None or self.deliver is None:
            return
        if self.delay_seconds <= 0:
            self.deliver(result)
        else:
            threading.Timer(self.delay_seconds, self.deliver, args=(result,)).start()

    def send_confirmation(self, notice: dict) -> None:
        """The customer confirmed an option. The real Planning will start its binding work here."""
        self.confirmations.append(notice)

    @staticmethod
    def answer_for(request: dict) -> PlanningResult | None:
        order = request["order"]
        quantity, requested_date = Decimal(str(order["quantity"])), date.fromisoformat(order["requested_date"])
        ref = request["request_ref"]

        def requested() -> OfferedOption:
            return OfferedOption(kind="REQUESTED", quantity=quantity, delivery_date=requested_date)

        def later(days: int) -> OfferedOption:
            return OfferedOption(kind="LATER_DATE", quantity=quantity, delivery_date=requested_date + timedelta(days=days),
                                 reason_code="SUPPLIER_LEAD_TIME")

        if quantity == 13:
            return None
        if quantity == 77:
            return PlanningResult(request_ref=ref, status="NEEDS_STAFF", reason_code="UNUSUAL_REQUEST")
        if quantity <= 500:
            return PlanningResult(request_ref=ref, status="READY", options=[requested()])
        if quantity <= 1000:
            less = OfferedOption(kind="LESS_QUANTITY", quantity=Decimal(500), delivery_date=requested_date,
                                 reason_code="CAPACITY")
            return PlanningResult(request_ref=ref, status="READY", options=[later(14), less])
        if quantity <= 5000:
            return PlanningResult(request_ref=ref, status="READY", options=[later(30)])
        return PlanningResult(request_ref=ref, status="NOTHING_FEASIBLE", reason_code="CAPACITY")


# -- the words used for options when our own code writes the reply --------------------------------------------------

OPTION_LETTERS = "ABCDEFG"


def _number(value: Decimal | int | float) -> str:
    value = Decimal(str(value))
    return str(int(value)) if value == value.to_integral_value() else str(value)


def describe_option(kind: str, quantity, delivery_date: date, product_name: str) -> str:
    """One option in plain words. Used by our own replies and shown to the model as the only wording it may build on."""
    what = f"{_number(quantity)} x {product_name} by {delivery_date.isoformat()}"
    if kind == "REQUESTED":
        return f"{what} (exactly what you asked for)"
    if kind == "LATER_DATE":
        return f"{what} (the full quantity, but later than you asked)"
    return f"{what} (a smaller quantity, on the date you asked for)"


def options_reply(options: list[tuple[str, Decimal, date]], product_name: str) -> str:
    """Our own reply that presents the options, written from the structured values only."""
    lines = ["Here is what we can offer:"]
    lines += [f"{OPTION_LETTERS[i]}) {describe_option(kind, quantity, day, product_name)}"
              for i, (kind, quantity, day) in enumerate(options)]
    lines.append("Which option would you like?")
    return "\n".join(lines)


def nothing_feasible_reply(product_name: str) -> str:
    return (f"I am sorry, we cannot offer {product_name} for that request. Would you like to try a different quantity "
            "or delivery date?")


def needs_staff_reply() -> str:
    return "Thank you. A member of our team needs to look at your request personally and will get back to you."


# -- the words used when the customer chooses, confirms, declines, or the offer ran out -----------------------------


def confirmation_question(quantity, delivery_date: date, product_name: str) -> str:
    """Asked before an order is made. Repeats the exact quantity and date; a "yes" counts only after this exact text."""
    return (f"Just to be sure: you would like {_number(quantity)} x {product_name}, delivered by "
            f"{delivery_date.isoformat()}. For this prototype the payment is assumed to be made. "
            "Shall I confirm this order? Please answer yes or no.")


def order_confirmed_reply(order_number: str, quantity, delivery_date: date, product_name: str) -> str:
    return (f"Thank you! Your order {order_number} is confirmed: {_number(quantity)} x {product_name}, delivered by "
            f"{delivery_date.isoformat()}. The payment is assumed to be made (prototype).")


def declined_reply() -> str:
    return "No problem, I have not placed any order. Message me any time if you would like to order something."


def offer_expired_reply() -> str:
    return "That offer is no longer valid, so I am checking with the planning team again. I will come back to you shortly."


def planning_late_reply() -> str:
    return ("The planning team needs a little more time for your request. It is still open, and a team member has been "
            "told. I will write to you as soon as I have an answer.")


def request_changed_reply() -> str:
    return "Thank you, I have noted your change. Nothing is ordered yet. I am checking the new request with the planning team."
