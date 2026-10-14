"""Checkpoint 1 chat logic, tested with the fake model (no Ollama needed)."""

import pytest

from app.core.errors import AppError, ErrorCode
from app.llm.client import FakeLLMClient
from app.sales_agent import chat
from app.sales_agent.prompts import SALES_AGENT_SYSTEM_PROMPT


@pytest.fixture(autouse=True)
def empty_conversations():
    chat.reset_all_conversations()
    yield
    chat.reset_all_conversations()


class BrokenLLMClient:
    """A model that is down."""

    def complete(self, messages):
        raise chat.LLMError("Ollama is not running")


def test_first_message_sends_the_rules_then_the_customer_message():
    model = FakeLLMClient(["Hello! Which product do you need?"])

    reply = chat.chat("+100", "Hi", model)

    assert reply == "Hello! Which product do you need?"
    assert model.calls[0] == [
        {"role": "system", "content": SALES_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": "Hi"},
    ]


def test_conversation_is_remembered_and_sent_to_the_model_next_time():
    model = FakeLLMClient(["Which product?", "And the delivery date?"])

    chat.chat("+100", "I need phones", model)
    chat.chat("+100", "SmartPhone X1, 500", model)

    second_call = model.calls[1]
    assert [m["role"] for m in second_call] == ["system", "user", "assistant", "user"]
    assert second_call[1]["content"] == "I need phones"
    assert second_call[2]["content"] == "Which product?"
    assert second_call[3]["content"] == "SmartPhone X1, 500"


def test_different_phone_numbers_have_separate_conversations():
    model = FakeLLMClient(["reply one", "reply two"])

    chat.chat("+100", "message from first customer", model)
    chat.chat("+200", "message from second customer", model)

    assert len(chat.get_history("+100")) == 2
    assert chat.get_history("+200")[0]["content"] == "message from second customer"
    assert len(model.calls[1]) == 2  # only the rules and the new message: nothing from the other customer


def test_model_failure_raises_a_clear_error_and_keeps_the_history_unchanged():
    chat.chat("+100", "Hi", FakeLLMClient(["Hello!"]))

    with pytest.raises(AppError) as error:
        chat.chat("+100", "I need phones", BrokenLLMClient())

    assert error.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert [m["content"] for m in chat.get_history("+100")] == ["Hi", "Hello!"]


def test_empty_model_answer_is_treated_as_a_failure():
    with pytest.raises(AppError) as error:
        chat.chat("+100", "Hi", FakeLLMClient(["   "]))

    assert error.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert chat.get_history("+100") == []


def test_only_the_latest_messages_are_sent_to_the_model():
    model = FakeLLMClient(["ok"])
    extra_old_messages = 5
    for number in range(chat.MAX_HISTORY_MESSAGES + extra_old_messages):
        chat._conversations.setdefault("+100", []).append({"role": "user", "content": f"old message {number}"})

    chat.chat("+100", "newest message", model)

    sent_to_model = model.calls[0]
    assert sent_to_model[0]["role"] == "system"  # the rules are always first
    assert len(sent_to_model) == 1 + chat.MAX_HISTORY_MESSAGES + 1
    assert sent_to_model[1]["content"] == f"old message {extra_old_messages}"  # the 5 oldest were left out
    assert sent_to_model[-1]["content"] == "newest message"


def test_reset_clears_only_that_conversation():
    model = FakeLLMClient(["ok"])
    chat.chat("+100", "Hi", model)
    chat.chat("+200", "Hi", model)

    chat.reset_conversation("+100")

    assert chat.get_history("+100") == []
    assert len(chat.get_history("+200")) == 2
