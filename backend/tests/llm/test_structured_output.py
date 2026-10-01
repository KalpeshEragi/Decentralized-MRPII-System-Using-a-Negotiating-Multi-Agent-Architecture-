"""LLM structured-output parsing and validation, with the fake model."""

import pytest

from app.llm.client import FakeLLMClient
from app.llm.reasoning import NegotiationProposal, StructuredOutputError, parse_structured, propose

GOOD = '{"action": "COUNTER_OFFER", "terms": {"quantity": 400, "delivery_date": "2026-10-20"}, "rationale": "x"}'


def test_parses_plain_fenced_and_think_wrapped_json():
    for raw in (GOOD, f"```json\n{GOOD}\n```", f"<think>hmm</think>\n{GOOD}"):
        assert parse_structured(raw, NegotiationProposal).terms.quantity == 400


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"action": "ACCEPT"}',  # missing rationale
        '{"action": "COUNTER_OFFER", "rationale": "x"}',  # counter without terms
        '{"action": "BUY", "rationale": "x"}',  # unknown action
        '{"action": "ACCEPT", "rationale": "x", "price": 5}',  # price/unknown field
    ],
)
def test_invalid_output_raises(raw):
    with pytest.raises(StructuredOutputError):
        parse_structured(raw, NegotiationProposal)


def test_propose_retries_once_then_succeeds_or_raises():
    assert propose(FakeLLMClient(["nope", GOOD]), [], NegotiationProposal).action == "COUNTER_OFFER"
    with pytest.raises(StructuredOutputError):
        propose(FakeLLMClient(["nope", "still nope"]), [], NegotiationProposal)
