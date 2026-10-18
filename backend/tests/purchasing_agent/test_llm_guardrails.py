"""The LLM's three jobs behind their guardrails: reading supplier replies, wording Purchasing's messages and explaining
the selection. Plain code: no database, no Ollama (fake LLMs only). The API seam is in db/test_llm_api.py."""

import json
import uuid
from datetime import date
from decimal import Decimal

from app.llm.client import FakeLLMClient
from app.purchasing_agent import messages
from app.purchasing_agent.interpretation import (FALLBACK_PARSER, LLM, Interpretation, OfferedTerms, SupplierReply,
                                                 interpret)
from app.purchasing_agent.writer import MessageWriter, explain_selection

OFFER = OfferedTerms(Decimal(500), date(2026, 11, 20), today=date(2026, 11, 2))
BROKEN = FakeLLMClient([])  # every call raises LLMError, as when Ollama is down


def extracted(action, quantity=None, delivery_date=None) -> FakeLLMClient:
    return FakeLLMClient([json.dumps({"action": action, "quantity": quantity, "delivery_date": delivery_date})])


# -- term extraction ------------------------------------------------------------------------------------------------


def test_n1_natural_acceptance_with_an_earlier_date_is_read_as_those_terms():
    result = interpret("ok, 500 by 12 Nov works", extracted("ACCEPT", 500, "2026-11-12"), OFFER)
    assert result == Interpretation(SupplierReply("COUNTER", Decimal(500), date(2026, 11, 12)), LLM)


def test_a_plain_acceptance_is_an_accept():
    result = interpret("sure, that works for us", extracted("ACCEPT"), OFFER)
    assert (result.reply, result.source) == (SupplierReply("ACCEPT"), LLM)


def test_an_acceptance_restating_the_offer_is_an_accept():
    result = interpret("yes 500 by 20 Nov is fine", extracted("ACCEPT", 500, "2026-11-20"), OFFER)
    assert result.reply == SupplierReply("ACCEPT")


def test_n4_natural_counter_with_a_late_date():
    result = interpret("500 but delivery 25 Nov", extracted("COUNTER", 500, "2026-11-25"), OFFER)
    assert (result.reply, result.source) == (SupplierReply("COUNTER", Decimal(500), date(2026, 11, 25)), LLM)


def test_a_counter_stating_only_a_quantity_keeps_the_date_unstated():
    result = interpret("we can only do 1,000", extracted("COUNTER", "1000"), OFFER)
    assert result.reply == SupplierReply("COUNTER", Decimal(1000), None)


def test_a_natural_rejection():
    assert interpret("no, we can't", extracted("REJECT"), OFFER).reply == SupplierReply("REJECT")


def test_unclear_from_the_llm_is_unclear():
    result = interpret("hmm let me see", extracted("UNCLEAR"), OFFER)
    assert (result.reply, result.source) == (None, LLM)


def test_a_counter_without_any_term_is_unclear():
    assert interpret("we'd like to change it", extracted("COUNTER"), OFFER).reply is None


def test_an_invented_quantity_falls_back_to_the_parser():
    result = interpret("we can deliver by 18 Nov", extracted("COUNTER", 500, "2026-11-18"), OFFER)
    assert (result.reply, result.source) == (None, FALLBACK_PARSER)  # 500 isn't in the reply; no strict format


def test_an_invented_date_falls_back_to_the_parser():
    result = interpret("we can only do 250", extracted("COUNTER", 250, "2026-11-20"), OFFER)
    assert (result.reply, result.source) == (None, FALLBACK_PARSER)


def test_a_date_with_a_guessed_year_or_month_falls_back_to_the_parser():
    for text, wrong in [("500 by 12 Nov", "2027-11-12"),  # the year isn't written: must be the next 12 Nov
                        ("500 by 12 Nov 2026", "2027-11-12"),  # another year than written
                        ("we may do 500 by the 12th", "2026-05-12")]:  # "may" is not a month here
        result = interpret(text, extracted("COUNTER", 500, wrong), OFFER)
        assert (result.reply, result.source) == (None, FALLBACK_PARSER), text


def test_invalid_llm_output_falls_back_to_the_parser():
    for raw in ("not json", '{"action": "MAYBE"}', '{"action": "COUNTER", "quantity": -5}',
                '{"action": "COUNTER", "quantity": 2.5}', '{"action": "COUNTER", "delivery_date": "12 Nov"}'):
        result = interpret("COUNTER 450 2026-11-12", FakeLLMClient([raw]), OFFER)
        assert (result.reply, result.source) == (
            SupplierReply("COUNTER", Decimal(450), date(2026, 11, 12)), FALLBACK_PARSER), raw


def test_n9_an_unavailable_llm_falls_back_to_the_parser():
    result = interpret("COUNTER 450 2026-11-12", BROKEN, OFFER)
    assert (result.reply, result.source) == (SupplierReply("COUNTER", Decimal(450), date(2026, 11, 12)),
                                             FALLBACK_PARSER)


def test_without_an_offer_the_reply_is_only_parsed():
    llm = extracted("ACCEPT")
    assert interpret("accept", llm, None).source == FALLBACK_PARSER and llm.calls == []


# -- message writer -------------------------------------------------------------------------------------------------

ALPHA, BETA = uuid.uuid4(), uuid.uuid4()
NAMES = {ALPHA: "Alpha Displays", BETA: "Beta Optics"}
TERMS = messages.offer_terms(Decimal(500), date(2026, 11, 20))
TEMPLATE = messages.offer_text("Alpha Displays", "Display Panel", "DSP-100", Decimal(500), date(2026, 11, 20))


def written(text: str) -> FakeLLMClient:
    return FakeLLMClient([json.dumps({"text": text})])


def test_good_wording_is_used_and_keeps_the_reply_format():
    text = "Hi Alpha Displays, could you deliver 500 units of Display Panel (DSP-100) by 2026-11-20?"
    result = MessageWriter(written(text), NAMES).write(ALPHA, TEMPLATE, TERMS)
    assert result == f"{text} {messages.REPLY_FORMAT}"


def test_wording_that_breaks_a_guardrail_is_replaced_by_the_template():
    for text in [
        "Could you deliver 500 units by 2026-11-20 at Rs 1200 per unit?",  # mentions price
        "Could you deliver 500 units by 2026-11-20? We can discuss the price.",  # negotiates price
        "Could you deliver 450 units by 2026-11-20?",  # changes the quantity
        "Could you deliver 500 units by 2026-11-25?",  # changes the date
        "Could you deliver 500 units by 2026-11-20, or 50 more by 2026-11-20?",  # adds a quantity
        "Could you deliver 500 units by 2026-11-20, or 100 more?",  # a quantity from the SKU's digits
        "Could you deliver 500 units by 2026-11-20, or 20 more?",  # a quantity from the date's digits
        "Could you deliver 500 units by 2026-11-20 or early December?",  # adds a date
        "Could you deliver 500 units by 2026-11-20? Beta Optics already agreed.",  # names another supplier
        "Could you deliver 500 units by 2026-11-20? Delivery is free of charge.",  # treats price as zero
        "",  # empty
    ]:
        assert MessageWriter(written(text), NAMES).write(ALPHA, TEMPLATE, TERMS) == TEMPLATE, text


def test_an_unavailable_or_invalid_llm_gives_the_template():
    assert MessageWriter(BROKEN, NAMES).write(ALPHA, TEMPLATE, TERMS) == TEMPLATE
    assert MessageWriter(FakeLLMClient(["no json"]), NAMES).write(ALPHA, TEMPLATE, TERMS) == TEMPLATE


def test_the_echo_is_kept_as_written_and_never_reworded():
    echo = messages.understood_text("COUNTER", Decimal(500), date(2026, 11, 25))
    counter = messages.counter_text(echo, Decimal(500), date(2026, 11, 20), date(2026, 11, 20))
    text = "We really need all 500 units by 2026-11-20, which can't move. Can you do 500 units by 2026-11-20?"
    llm = written(text)
    result = MessageWriter(llm, NAMES).write(ALPHA, counter, TERMS, prefix=echo)
    assert result == f"{echo} {text} {messages.REPLY_FORMAT}"
    assert "Understood" not in llm.calls[0][-1]["content"]  # the LLM never sees the echo, only the body


# -- selection explanation ------------------------------------------------------------------------------------------

FACTS = {  # A1, shaped as `writer.selection_facts` builds it
    "shortage_quantity": "500", "required_date": "2026-11-20", "selection_date": "2026-11-02", "outcome": "SINGLE",
    "cost_ranking_available": True,
    "legs": [{"supplier_name": "Alpha Displays", "quantity": "500", "unit_price": "1200.00", "cost": "600000.00",
              "arrival": "2026-11-12"}],
    "total_cost": "600000.00", "constrained_quantity": None, "best_priced_single": None,
    "options": [
        {"supplier_name": "Alpha Displays", "price_kind": "PRICED", "unit_price": "1200.00", "total_cost": "600000.00"},
        {"supplier_name": "Beta Optics", "price_kind": "PRICED", "unit_price": "1250.00", "total_cost": "625000.00"},
        {"supplier_name": "Gamma Screens", "price_kind": "NOT_REGISTERED", "unit_price": None, "total_cost": None},
    ],
    "reasoning_summary": "SINGLE: Alpha Displays is the best priced single supplier.",
}


def test_a_supported_explanation_is_kept():
    text = ("Alpha Displays was chosen: it is the cheapest priced supplier, 500 units for ₹600,000, arriving by "
            "2026-11-12. Gamma Screens has no registered price, so it was not ranked on cost.")
    assert explain_selection(written(text), FACTS) == text


def test_an_explanation_with_unsupported_claims_is_rejected():
    unpriced_only = FACTS | {"cost_ranking_available": False}
    for facts, text in [
        (FACTS, "Alpha Displays was chosen at ₹1,150 per unit."),  # a price that isn't in the decision
        (FACTS, "Alpha Displays saves ₹50,000 against Beta Optics."),  # 50000 isn't in the decision
        (FACTS, "Gamma Screens would have been free but is slower."),  # Not Registered as zero
        (FACTS, "Gamma Screens costs ₹1200 per unit, like Alpha Displays."),  # a price for a Not Registered supplier
        (FACTS, "Gamma Screens would cost 625,000 for the order."),  # a price for a Not Registered supplier
        (FACTS, "Alpha Displays is cheaper than Gamma Screens."),  # a cost claim about a Not Registered supplier
        (FACTS, "Alpha Displays was chosen; a discount may be negotiated later."),  # price negotiation
        (unpriced_only, "Gamma Screens was chosen as the cheapest option."),  # no cost ranking to support it
    ]:
        assert explain_selection(written(text), facts) is None, text


def test_an_unavailable_llm_gives_no_explanation():
    assert explain_selection(BROKEN, FACTS) is None


# -- code review 2026-10-18 (ticket 11): the reviewer's probe cases -------------------------------------------------


def test_a_number_in_a_date_is_never_read_as_the_quantity():
    result = interpret("deliver by 12 Nov", extracted("COUNTER", 12, "2026-11-12"), OFFER)
    assert result.reply != SupplierReply("COUNTER", Decimal(12), date(2026, 11, 12))
    assert result.source == FALLBACK_PARSER


def test_a_reference_number_is_never_read_as_a_counter_quantity():
    result = interpret("Re order 300: yes we accept", extracted("ACCEPT", 300), OFFER)
    assert result.reply is None or result.reply.action != "COUNTER"


def test_a_four_digit_quantity_does_not_force_a_year_on_the_date():
    result = interpret("We can do 2500 by 15 Nov", extracted("COUNTER", 2500, "2026-11-15"), OFFER)
    assert result == Interpretation(SupplierReply("COUNTER", Decimal(2500), date(2026, 11, 15)), LLM)


def test_a_written_year_must_still_match():
    result = interpret("500 by 12 Nov 2027", extracted("COUNTER", 500, "2026-11-12"), OFFER)
    assert result.source == FALLBACK_PARSER


def test_wording_with_numbers_or_dates_in_other_forms_is_replaced_by_the_template():
    for text in [
        "Could you deliver 500 units by 2026-11-20, or two hundred more?",  # a quantity in words
        "Could you deliver five hundred units by 2026-11-20?",
        "Could you deliver 500 units by Friday?",  # a date in another form
        "Could you deliver 500 units by the end of next month?",
        "Could you deliver 500 units by 2026-11-20, or tomorrow?",
        "Could you deliver 500 units by 2026-11-20? There is no fee.",  # money words
        "Could you deliver 500 units by 2026-11-20 for the agreed amount?",
        "Could you deliver 500 units by 2026-11-20 for the same sum?",
        "Could you deliver 500 units by 2026-11-20? The total amount stays the same.",
        "Could you deliver 500 units by 2026-11-20? That is about 6 lakh.",
        "Could you deliver 500 units by 2026-11-20? Please send the bill.",
        "Could you deliver 500 units by 2026-11-20 at the usual rate?",
        "Could you deliver 500 units by 2026-11-20 at the same cost?",
        "Could you deliver 500 units by 2026-11-20 for ₹ as before?",
        "Could you deliver 500 units by 2026-11-20, and 500 more units later?",  # an allowed number, new meaning
    ]:
        assert MessageWriter(written(text), NAMES).write(ALPHA, TEMPLATE, TERMS) == TEMPLATE, text


def test_an_explanation_pricing_a_not_registered_supplier_is_rejected():
    for text in [
        "Gamma Screens' price is 1200, the same as Alpha Displays.",
        "Alpha Displays was chosen. Gamma Screens was not ranked; it would be 1200 a unit.",
        "Gamma Screens was not ranked. Its price is zero.",
        "Gamma Screens has a price of zero.",
    ]:
        assert explain_selection(written(text), FACTS) is None, text


def test_an_explanation_claiming_value_without_a_cost_ranking_is_rejected():
    for facts in (FACTS | {"cost_ranking_available": False}, FACTS | {"cost_ranking_available": None}):
        for text in ["Gamma Screens was chosen as the better-value option.",
                     "Gamma Screens offers the best value.", "Gamma Screens is more economical."]:
            assert explain_selection(written(text), facts) is None, text
