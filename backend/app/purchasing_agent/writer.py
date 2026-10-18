"""LLM-written text, behind guardrails. No database. The LLM is never the source of business truth: it only words
what our code already decided, and anything it writes is checked before use.

- `MessageWriter`: Purchasing's offer, counter-offer, revised-offer and clarification text. The LLM rewords the
  template; the echo of the supplier's reply ("Understood: …") and the reply-format line stay exactly as the template
  has them. Output that drops or changes a quantity or date, adds any other number or month, writes a quantity or date
  in words, repeats a number with another meaning, mentions price, payment or money, or names another supplier is
  rejected and the template is sent instead.
- `explain_selection`: a short explanation of the deterministic selection, stored as `llm_explanation` (explanation
  only, never evidence). Rejected (None) when it states a number that isn't in the decision, treats Not Registered as
  zero or free or gives it a price, claims a cost or value comparison the decision can't support, or talks about
  negotiating price.
"""

import json
import logging
import re
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.llm.client import LLMClient, LLMError
from app.llm.reasoning import StructuredOutputError, propose
from app.purchasing_agent.interpretation import month_mentions, written_numbers
from app.purchasing_agent.messages import REPLY_FORMAT

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 600
MAX_EXPLANATION_LENGTH = 1200

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DECIMAL = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_CODE = re.compile(r"\b(?=[\w-]*[A-Za-z])(?=[\w-]*\d)[\w-]+\b")  # a word mixing letters and digits, e.g. DSP-100
# Supplier messages never talk about money: price is not negotiated (ADR-002).
_MONEY = re.compile(
    r"[₹$€£]|\b(prices?|priced|pricing|costs?|costing|rates?|discounts?|cheap\w*|expensive|inr|rs|rupees?|usd|"
    r"dollars?|euros?|budget|pay\w*|paid|invoice\w*|charges?|charged|tariffs?|quot(e|es|ed|ation)|free(?!\s+to\b)|"
    r"zero|fees?|amounts?|sums?|bill\w*|lakhs?|crores?)\b",
    re.IGNORECASE)
# Quantities and dates in other forms than the template's digits and yyyy-mm-dd: words never seen by the number checks.
_OTHER_QUANTITY_OR_DATE = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?|"
    r"dozens?|half|double|twice|couple|monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tonight|"
    r"tomorrow|yesterday|days?|weeks?|weekends?|fortnights?|months?|years?|quarters?)\b", re.IGNORECASE)
# An allowed number given another meaning: "500 more units later".
_EXTRA_QUANTITY = re.compile(r"\d\s+(more|additional|extra|further)\b|\b(another|additional|extra|further)\s+\d",
                             re.IGNORECASE)
_ZERO_PRICE = re.compile(r"\b(free|zero[- ]cost|no cost|costs? nothing|at no charge|no charge)\b", re.IGNORECASE)
_COST_COMPARISON = re.compile(
    r"\b(cheap\w*|lowest[- ]cost|least expensive|less expensive|lower[- ]cost|most economical|saving\w*|saves?|"
    r"saved|(better|best|good|great)[- ]value|value for money|economical|affordable|pricier|costlier|"
    r"more expensive|higher[- ]cost|(lower|better|best)[- ]prices?)\b", re.IGNORECASE)
# In a sentence about a Not Registered supplier: a price stated as a value ("price is 1200", "1200 a unit") or as zero.
_PRICE_WORD = re.compile(r"[₹$€£]|\b(inr|rs|rupees?|prices?|priced|costs?|per unit|a unit|each|unit price)\b",
                         re.IGNORECASE)
_NOTHING = re.compile(r"\b(zero|nil|nothing|free)\b", re.IGNORECASE)
_PRONOUN = re.compile(r"\b(it|its|it's|they|their|them|this supplier)\b", re.IGNORECASE)
_PRICE_NEGOTIATION = re.compile(r"\b(discount\w*|negotiat\w*\s+(the\s+)?prices?|lower\s+(the\s+)?prices?)\b",
                                re.IGNORECASE)


class WrittenText(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str


@dataclass(frozen=True)
class MessageWriter:
    llm_client: LLMClient
    supplier_names: Mapping[uuid.UUID, str]  # the item's suppliers; a message may name only its addressee

    def write(self, supplier_id: uuid.UUID, template: str, terms: dict | None = None, prefix: str = "") -> str:
        """The LLM's wording of `template` for `supplier_id`, or `template` itself when the LLM fails or breaks a
        guardrail. `terms` (quantity, delivery_date) must appear exactly; `prefix` (the echo) is kept as it is."""
        body = template.removeprefix(prefix).strip() if prefix else template
        suffix = REPLY_FORMAT if body.endswith(REPLY_FORMAT) else ""
        body = body.removesuffix(suffix).strip()
        others = [name for sid, name in self.supplier_names.items() if sid != supplier_id]
        try:
            written = propose(self.llm_client, _writer_prompt(body), WrittenText, retries=0).text.strip()
        except (LLMError, StructuredOutputError) as error:
            logger.info("message writer unavailable, template used: %s", error)
            return template
        if (problem := message_violation(body, written, terms, others)) is not None:
            logger.info("message writer output rejected, template used: %s", problem)
            return template
        return " ".join(part for part in (prefix.strip(), written, suffix) if part)


def _writer_prompt(body: str) -> list[dict[str, str]]:
    system = (
        "You reword a short chat message from a company's Purchasing team to one of its suppliers so it reads "
        "naturally and politely. Keep the meaning exactly.\n"
        "- Keep every quantity and every date exactly as written (dates stay yyyy-mm-dd).\n"
        "- Do not add any other number, date, price, cost, discount, payment term or company name.\n"
        "- Two or three sentences at most.\n"
        'Answer with one JSON object only: {"text": "<the reworded message>"}.'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": body}]


def message_violation(template: str, written: str, terms: dict | None, other_supplier_names: list[str]) -> str | None:
    """Why `written` can't replace `template`, or None when it may. Pure."""
    if not written or len(written) > MAX_MESSAGE_LENGTH:
        return "empty or too long"
    if _MONEY.search(written):
        return "mentions price or payment"
    if any(name.lower() in written.lower() for name in other_supplier_names):
        return "names another supplier"
    for value in (terms or {}).values():
        if value is not None and not re.search(rf"(?<![\d-]){re.escape(value)}(?![\d-])", written):
            return f"drops or changes {value}"
    # Dates and codes such as the SKU are compared whole, so their digits can't come back as a new quantity.
    if extra := set(_ISO_DATE.findall(written)) - set(_ISO_DATE.findall(template)):
        return f"adds the date(s) {sorted('-'.join(d) for d in extra)}"
    if extra := set(_CODE.findall(_ISO_DATE.sub(" ", written))) - set(_CODE.findall(_ISO_DATE.sub(" ", template))):
        return f"adds {sorted(extra)}"
    if extra := _loose_numbers(written) - _loose_numbers(template):
        return f"adds the number(s) {sorted(extra)}"
    if _EXTRA_QUANTITY.search(written) or _number_counts(written) - _number_counts(template):
        return "repeats a number with another meaning"
    if extra := _words(_OTHER_QUANTITY_OR_DATE, written) - _words(_OTHER_QUANTITY_OR_DATE, template):
        return f"adds a quantity or date in words {sorted(extra)}"
    if month_mentions(written) - {int(month) for _, month, _ in _ISO_DATE.findall(template)}:
        return "names another month"
    return None


def _loose_numbers(text: str) -> set[Decimal]:
    """The numbers in `text` outside dates and codes: in a template, only its quantities."""
    return written_numbers(_CODE.sub(" ", _ISO_DATE.sub(" ", text)))


def _number_counts(text: str) -> Counter:
    """How often each number outside dates and codes is written: the wording may not say a quantity more often than
    the template does."""
    return Counter(Decimal(n) for n in _DECIMAL.findall(_THOUSANDS.sub("", _CODE.sub(" ", _ISO_DATE.sub(" ", text)))))


def _words(pattern: re.Pattern, text: str) -> set[str]:
    return {match[0].lower() for match in pattern.finditer(text)}


def explain_selection(llm_client: LLMClient, facts: dict) -> str | None:
    """A short plain-language explanation of the selection in `facts` (the deterministic decision, as JSON), or None
    when the LLM fails or the explanation breaks a guardrail."""
    try:
        explanation = propose(llm_client, _explanation_prompt(facts), WrittenText, retries=0).text.strip()
    except (LLMError, StructuredOutputError) as error:
        logger.info("selection explanation unavailable: %s", error)
        return None
    if (problem := explanation_violation(explanation, facts)) is not None:
        logger.info("selection explanation rejected: %s", problem)
        return None
    return explanation


def _explanation_prompt(facts: dict) -> list[dict[str, str]]:
    system = (
        "You explain a purchasing decision that has already been made by deterministic rules. You cannot change it.\n"
        "- In two to four sentences, say which supplier(s) were chosen, the quantities, and why, using only the "
        "facts given.\n"
        "- Use only numbers that appear in the facts. A supplier whose price_kind is NOT_REGISTERED has no known "
        "price: never give it a price, never call it free or zero cost, and never claim it is cheaper or saves "
        "money.\n"
        "- If cost_ranking_available is false, make no cost comparison at all.\n"
        "- Price is never negotiated.\n"
        'Answer with one JSON object only: {"text": "<the explanation>"}.'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(facts)}]


def explanation_violation(explanation: str, facts: dict) -> str | None:
    """Why `explanation` can't be stored for the decision in `facts`, or None when it may. Pure."""
    if not explanation or len(explanation) > MAX_EXPLANATION_LENGTH:
        return "empty or too long"
    if extra := _decimals(explanation) - _decimals(json.dumps(facts)):
        return f"states the number(s) {sorted(extra)}, which are not in the decision"
    unpriced = [o["supplier_name"] for o in facts.get("options", []) if o.get("price_kind") == "NOT_REGISTERED"]
    if unpriced and _ZERO_PRICE.search(explanation):
        return "treats Not Registered as zero or free"
    if facts.get("cost_ranking_available") is not True and _COST_COMPARISON.search(explanation):
        return "claims a cost comparison the decision can't support"
    if _PRICE_NEGOTIATION.search(explanation):
        return "talks about negotiating price"
    names = [o["supplier_name"] for o in facts.get("options", [])]
    about_unpriced = False  # the sentence names a Not Registered supplier, or refers back to one ("it", "its")
    for sentence in re.split(r"(?<=[.;!?])\s+|\n", explanation):
        named = [name for name in names if name.lower() in sentence.lower()]
        if named:
            about_unpriced = any(name in unpriced for name in named)
        elif not _PRONOUN.search(sentence):
            about_unpriced = False
        if about_unpriced and (_COST_COMPARISON.search(sentence) or re.search(
                r"[₹$€£]|\b(inr|rs|rupees?|per unit|unit price|each|costs?\s+[\d₹]|would cost)\b", sentence,
                re.IGNORECASE) or (_PRICE_WORD.search(sentence) and (_DECIMAL.search(sentence)
                                                                      or _NOTHING.search(sentence)))):
            return "gives a price or a cost comparison for a Not Registered supplier"
    return None


def _decimals(text: str) -> set[Decimal]:
    """Every number in `text`, compared by value (315,000 = 315000.00; 2026-11-20 gives 2026, 11 and 20)."""
    return {Decimal(n) for n in _DECIMAL.findall(_THOUSANDS.sub("", text))}


def selection_facts(shortage: Decimal, required_date: date, today: date, decision: dict, options: list[dict],
                    reasoning_summary: str) -> dict:
    """What the explanation may use: the decision and the options as audited, without identifiers (their digits
    would otherwise count as facts)."""
    def plain(record: dict) -> dict:
        return {k: v for k, v in record.items() if not k.endswith("_id") and k != "id"}

    return {
        "shortage_quantity": format(shortage.normalize(), "f"),
        "required_date": required_date.isoformat(),
        "selection_date": today.isoformat(),
        "outcome": decision["outcome"],
        "cost_ranking_available": decision["cost_ranking_available"],
        "legs": [plain(leg) for leg in decision["legs"]],
        "total_cost": decision["total_cost"],
        "constrained_quantity": decision["constrained_quantity"],
        "best_priced_single": plain(decision["best_priced_single"]) if decision["best_priced_single"] else None,
        "options": [plain(option) for option in options],
        "reasoning_summary": reasoning_summary,
    }
