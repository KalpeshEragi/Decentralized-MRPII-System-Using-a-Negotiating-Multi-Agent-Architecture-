"""Reading a supplier's free-text reply into structured terms. No database.

The LLM (the shared client) extracts action, quantity and delivery date into a fixed shape. Its output is checked
before it is used: a term it reports must actually be written in the reply (a quantity as a quantity, not inside a
date, a reference or a code), so missing terms are never invented. When the LLM is unavailable or its output is
invalid, the strict-format fallback parser reads the reply instead (`ACCEPT`, `COUNTER <qty> <yyyy-mm-dd>`, `REJECT`,
any letter case). Whatever reads the reply, Purchasing still validates the
terms (`negotiation.py`); a reply that can't be read is unclear, never guessed.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.llm.client import LLMClient, LLMError
from app.llm.reasoning import StructuredOutputError, propose
from app.purchasing_agent.messages import quantity_text

LLM = "LLM"
FALLBACK_PARSER = "FALLBACK_PARSER"

_COUNTER = re.compile(r"COUNTER\s+(\d+)\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_NUMBER = re.compile(r"\d+")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")  # 1,000 → 1000
MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
               "november", "december")
# "Nov", "november", "Sept"; "may" only next to a number ("12 May", "May 12"), as it is also a verb.
_MONTH = re.compile(r"\b(jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|(?<=\d\s)may\b|\bmay(?=\s\d)",
                    re.IGNORECASE)
_MONTH_NAME = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_ORDINAL = r"(?:st|nd|rd|th)?"
# A date as a supplier may write it: 2026-11-12, 12/11, 12/11/2026, 12 Nov, 12th of November 2026, Nov 12, 2026,
# the 12th. Its numbers are never a quantity, and a year counts only when written inside such a date.
_DATE_TEXT = re.compile(
    rf"\b\d{{4}}-\d{{1,2}}-\d{{1,2}}\b|\b\d{{1,2}}[/.-]\d{{1,2}}(?:[/.-]\d{{2,4}})?\b"
    rf"|\b\d{{1,2}}{_ORDINAL}\s+(?:of\s+)?{_MONTH_NAME}(?:,?\s+\d{{4}}\b)?"
    rf"|\b{_MONTH_NAME}\s+\d{{1,2}}{_ORDINAL}\b(?:,?\s+\d{{4}}\b)?|\b\d{{1,2}}(?:st|nd|rd|th)\b",
    re.IGNORECASE)
# A number that names something rather than counting units: "order 300", "PO #4411", "ref: 12", DSP-100.
_NOT_A_QUANTITY = re.compile(
    r"\b(?:order|ref|reference|no|number|po|invoice|id|item|sku)\s*[#:.]?\s*\d+|#\s*\d+"
    r"|\b(?=[\w-]*[A-Za-z])(?=[\w-]*\d)[\w-]+\b", re.IGNORECASE)
_YEAR = re.compile(r"\b\d{4}\b")


@dataclass(frozen=True)
class SupplierReply:
    action: str  # ACCEPT, COUNTER, REJECT
    # COUNTER only. The fallback parser always reads both; the LLM may report one of them only when the supplier
    # stated just that one (e.g. "we can only do 250"). A COUNTER always has at least one.
    quantity: Decimal | None = None
    delivery_date: date | None = None


@dataclass(frozen=True)
class Interpretation:
    reply: SupplierReply | None  # None: unclear
    source: str  # LLM, FALLBACK_PARSER


@dataclass(frozen=True)
class OfferedTerms:
    """Purchasing's current offer, which the reply answers, and the selection date (for the year of "12 Nov")."""

    quantity: Decimal
    delivery_date: date
    today: date


def parse_strict(text: str) -> SupplierReply | None:
    """The strict reply format, or None when the text doesn't match it exactly."""
    text = text.strip()
    if text.upper() in ("ACCEPT", "REJECT"):
        return SupplierReply(text.upper())
    if (match := _COUNTER.fullmatch(text)) is None:
        return None
    quantity = Decimal(match[1])
    try:
        delivery_date = date.fromisoformat(match[2])
    except ValueError:  # e.g. 2026-02-30
        return None
    return SupplierReply("COUNTER", quantity, delivery_date) if quantity > 0 else None


class ExtractedTerms(BaseModel):
    """What the LLM must answer. Unknown fields are ignored; the values are checked by `_checked`."""

    model_config = ConfigDict(extra="ignore")

    action: Literal["ACCEPT", "COUNTER", "REJECT", "UNCLEAR"]
    quantity: int | float | str | None = None  # the model may write 500 or "500"
    delivery_date: str | None = None


class InvalidExtraction(Exception):
    """The LLM's terms can't be trusted: malformed, or not written in the supplier's reply."""


def interpret(text: str, llm_client: LLMClient, offered: OfferedTerms | None) -> Interpretation:
    """`offered` is None when there is no offer to answer: the reply is then only parsed, never sent to the LLM."""
    if offered is not None:
        try:
            extracted = propose(llm_client, _prompt(text, offered), ExtractedTerms, retries=1)
            return Interpretation(_checked(extracted, text, offered), LLM)
        except (LLMError, StructuredOutputError, InvalidExtraction):
            pass
    return Interpretation(parse_strict(text), FALLBACK_PARSER)


def _prompt(text: str, offered: OfferedTerms) -> list[dict[str, str]]:
    system = (
        "You read a supplier's chat reply to a purchase offer and extract its terms. You decide nothing.\n"
        f"The offer was: {quantity_text(offered.quantity)} units delivered by {offered.delivery_date.isoformat()}. "
        f"Today is {offered.today.isoformat()}.\n"
        'Answer with one JSON object only: {"action": "ACCEPT" | "COUNTER" | "REJECT" | "UNCLEAR", '
        '"quantity": <number or null>, "delivery_date": "<yyyy-mm-dd>" or null}.\n'
        "- ACCEPT: the supplier agrees to the offer. COUNTER: the supplier proposes another quantity or delivery "
        "date. REJECT: the supplier refuses. UNCLEAR: anything else, or you are not sure.\n"
        "- quantity and delivery_date: only what the supplier wrote in this reply. Use null for a term the supplier "
        "did not state; never copy it from the offer and never guess.\n"
        "- If the supplier gives a date without a year, use the first such date on or after today."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


def _checked(extracted: ExtractedTerms, text: str, offered: OfferedTerms) -> SupplierReply | None:
    """The LLM's terms as a reply, or None for unclear. Raises InvalidExtraction for terms that are malformed or not
    written in the reply."""
    if extracted.action == "UNCLEAR":
        return None
    if extracted.action == "REJECT":
        return SupplierReply("REJECT")
    quantity, delivery_date = _quantity(extracted.quantity), _date(extracted.delivery_date)
    numbers = written_numbers(text)
    if quantity is not None and quantity not in quantity_numbers(text):
        raise InvalidExtraction(f"quantity {quantity} is not written in the reply as a quantity")
    if delivery_date is not None and not _date_written(delivery_date, text, numbers, offered.today):
        raise InvalidExtraction(f"delivery date {delivery_date} is not written in the reply")
    if extracted.action == "ACCEPT":
        # "ok, 500 by 12 Nov works": an acceptance stating other terms than the offer proposes those terms.
        if quantity in (None, offered.quantity) and delivery_date in (None, offered.delivery_date):
            return SupplierReply("ACCEPT")
    if quantity is None and delivery_date is None:
        return None  # a counter-offer without terms is unclear
    return SupplierReply("COUNTER", quantity, delivery_date)


def _quantity(value: int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):  # true would otherwise read as 1
        raise InvalidExtraction("quantity is not a number")
    try:
        quantity = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise InvalidExtraction("quantity is not a number") from exc
    if not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value():
        raise InvalidExtraction("quantity is not a positive whole number")
    return quantity.to_integral_value()


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise InvalidExtraction("delivery_date is not a yyyy-mm-dd date") from exc


def written_numbers(text: str) -> set[Decimal]:
    """Every whole number written in `text` (1,000 counts as 1000)."""
    return {Decimal(n) for n in _NUMBER.findall(_THOUSANDS.sub("", text))}


def quantity_numbers(text: str) -> set[Decimal]:
    """The whole numbers in `text` that can be a quantity: not part of a date, a code or a reference."""
    return written_numbers(_NOT_A_QUANTITY.sub(" ", _DATE_TEXT.sub(" ", _THOUSANDS.sub("", text))))


def month_mentions(text: str) -> set[int]:
    """The months named in `text` (1–12)."""
    return {next(i for i, name in enumerate(MONTH_NAMES, start=1) if name.startswith(match[0].lower()[:3]))
            for match in _MONTH.finditer(text)}


def _date_written(value: date, text: str, numbers: set[Decimal], today: date) -> bool:
    """The day is written as a number and the month as a number or a name ("12 Nov", "12/11", "2026-11-12"). The year
    is written in the date too, or the date is the first such day on or after today (as the prompt asks). A 4-digit
    number outside a date (a quantity such as 2500) is not a year."""
    if Decimal(value.day) not in numbers:
        return False
    if Decimal(value.month) not in numbers and value.month not in month_mentions(text):
        return False
    if years := {int(year) for written in _DATE_TEXT.findall(text) for year in _YEAR.findall(written)}:
        return value.year in years
    return value == _next_on_or_after(value.month, value.day, today)


def _next_on_or_after(month: int, day: int, today: date) -> date | None:
    for year in (today.year, today.year + 1, today.year + 4):  # +4: a 29 February
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None
