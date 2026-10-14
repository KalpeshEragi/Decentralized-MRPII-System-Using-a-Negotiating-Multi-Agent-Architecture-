"""Checkpoint 1 test-channel door, tested with the fake model (no Ollama needed)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import install_error_handlers
from app.llm.client import FakeLLMClient
from app.sales_agent import api, chat


class BrokenLLMClient:
    def complete(self, messages):
        raise chat.LLMError("Ollama is not running")


def make_client(model) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)  # the same error format as the real backend
    app.include_router(api.router)
    app.dependency_overrides[api.get_llm_client] = lambda: model
    return TestClient(app)


@pytest.fixture(autouse=True)
def empty_conversations():
    chat.reset_all_conversations()
    yield
    chat.reset_all_conversations()


def test_chat_returns_the_reply_and_the_history_shows_both_messages():
    client = make_client(FakeLLMClient(["Hello! Which product do you need?"]))

    response = client.post("/sales-test/chat", json={"phone": "+100", "message": "Hi"})

    assert response.status_code == 200
    assert response.json() == {"reply": "Hello! Which product do you need?"}
    history = client.get("/sales-test/history/+100").json()["messages"]
    assert history == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello! Which product do you need?"},
    ]


def test_spaces_around_the_message_are_removed():
    model = FakeLLMClient(["ok"])
    client = make_client(model)

    client.post("/sales-test/chat", json={"phone": " +100 ", "message": "  Hi  "})

    assert model.calls[0][-1]["content"] == "Hi"
    assert chat.get_history("+100")[0]["content"] == "Hi"


@pytest.mark.parametrize(
    "body",
    [
        {"phone": "+100", "message": ""},
        {"phone": "+100", "message": "     "},
        {"phone": "", "message": "Hi"},
        {"message": "Hi"},
        {"phone": "+100"},
        {"phone": "+100", "message": "x" * 2001},
    ],
)
def test_wrong_requests_are_refused_and_the_model_is_not_called(body):
    model = FakeLLMClient(["should not be used"])
    client = make_client(model)

    response = client.post("/sales-test/chat", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert model.calls == []


def test_model_down_gives_a_clear_503_and_saves_nothing():
    client = make_client(BrokenLLMClient())

    response = client.post("/sales-test/chat", json={"phone": "+100", "message": "Hi"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert client.get("/sales-test/history/+100").json() == {"messages": []}


def test_clear_history_removes_the_conversation():
    client = make_client(FakeLLMClient(["ok"]))
    client.post("/sales-test/chat", json={"phone": "+100", "message": "Hi"})

    response = client.delete("/sales-test/history/+100")

    assert response.json() == {"status": "cleared"}
    assert client.get("/sales-test/history/+100").json() == {"messages": []}


def test_history_of_an_unknown_phone_is_empty():
    client = make_client(FakeLLMClient(["ok"]))

    assert client.get("/sales-test/history/+999").json() == {"messages": []}


def test_the_chat_page_is_served():
    client = make_client(FakeLLMClient(["ok"]))

    response = client.get("/sales-test")

    assert response.status_code == 200
    assert "Sales Agent test channel" in response.text
