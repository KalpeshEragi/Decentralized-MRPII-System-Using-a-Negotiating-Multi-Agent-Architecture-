"""The fixed answer format of the language model, tested with the fake model. No database needed."""

import json

import pytest

from app.llm.client import FakeLLMClient
from app.llm.reasoning import StructuredOutputError
from app.sales_agent.agent import ai_understand_and_reply

MESSAGES = [{"role": "user", "content": "Hi"}]


def answer(**fields) -> str:
    base = {"reply": "Which product do you need?", "next_step": "ask_more", "details": {}, "reason": "nothing known yet"}
    return json.dumps({**base, **fields})


def test_a_valid_answer_is_read_whatever_wrapper_it_comes_in():
    details = {"product": "SmartPhone X1", "quantity": "500", "requested_date": "2026-11-10"}

    for raw in (answer(details=details), f"```json\n{answer(details=details)}\n```", f"<think>hmm</think>{answer(details=details)}"):
        turn = ai_understand_and_reply(FakeLLMClient([raw]), MESSAGES)
        assert turn.next_step == "ask_more"
        assert (turn.details.product, turn.details.quantity, turn.details.requested_date) == (
            "SmartPhone X1", "500", "2026-11-10")

    # Missing details and unknown extra fields are fine; the details are simply unknown.
    sparse = json.dumps({"reply": "Hello!", "next_step": "ask_more", "mood": "cheerful"})
    turn = ai_understand_and_reply(FakeLLMClient([sparse]), MESSAGES)
    assert turn.details.product is None and turn.details.quantity is None and turn.details.requested_date is None


def test_a_broken_answer_is_asked_for_again_once_and_then_refused():
    model = FakeLLMClient(["Sure, I can help!", answer()])
    assert ai_understand_and_reply(model, MESSAGES).reply == "Which product do you need?"
    assert len(model.calls) == 2

    with pytest.raises(StructuredOutputError):  # broken twice in a row
        ai_understand_and_reply(FakeLLMClient(["not json", "still not json"]), MESSAGES)

    # Valid JSON that breaks our rules is refused too: nothing empty or huge reaches a customer, and the next step
    # must be one we know.
    for bad_fields in ({"reply": "   "}, {"reply": "x" * 1001}, {"next_step": "delete_everything"}):
        with pytest.raises(StructuredOutputError):
            ai_understand_and_reply(FakeLLMClient([answer(**bad_fields)]), MESSAGES)
