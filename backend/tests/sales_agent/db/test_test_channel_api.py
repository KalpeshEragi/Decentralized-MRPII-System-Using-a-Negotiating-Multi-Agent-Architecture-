"""The temporary test-channel door, tested with a fake model on the test database."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.core.errors import install_error_handlers
from app.llm.client import FakeLLMClient, LLMError
from app.sales_agent import api

ANSWER = json.dumps({"reply": "Hello! Which product do you need?", "next_step": "ask_more", "details": {}, "reason": ""})


class BrokenModel:
    def complete(self, messages):
        raise LLMError("Ollama is not running")


def make_client(engine, model) -> TestClient:
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def session_per_request():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    install_error_handlers(app)  # the same error format as the real backend
    app.include_router(api.router)
    app.dependency_overrides[get_db] = session_per_request
    app.dependency_overrides[api.get_llm_client] = lambda: model
    return TestClient(app)


def test_the_chat_door_works_end_to_end_refuses_bad_requests_and_reports_a_model_that_is_down(db, engine):
    client = make_client(engine, FakeLLMClient([ANSWER]))

    # A message goes in, the reply comes out, and the history shows both (spaces around the text are removed).
    response = client.post("/sales-test/chat", json={"phone": " +100 ", "message": "  Hi  "})
    assert response.status_code == 200 and response.json() == {"reply": "Hello! Which product do you need?"}
    two_messages = {"messages": [
        {"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello! Which product do you need?"}]}
    assert client.get("/sales-test/history/+100").json() == two_messages

    # Bad requests are refused in the project's standard error format, and nothing is saved for them.
    bad_requests = [
        {"phone": "+100", "message": ""}, {"phone": "+100", "message": "     "}, {"phone": "", "message": "Hi"},
        {"message": "Hi"}, {"phone": "+100"}, {"phone": "+100", "message": "x" * 2001},
    ]
    for body in bad_requests:
        response = client.post("/sales-test/chat", json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR", body
    assert client.get("/sales-test/history/+100").json() == two_messages

    # The page is served, and clearing a chat empties it.
    assert "Sales Agent test channel" in client.get("/sales-test").text
    assert client.delete("/sales-test/history/+100").json() == {"status": "cleared"}
    assert client.get("/sales-test/history/+100").json() == {"messages": []}

    # If the language model is down the customer gets a clear 503, and their message is kept for later.
    down = make_client(engine, BrokenModel())
    response = down.post("/sales-test/chat", json={"phone": "+200", "message": "Hi"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert down.get("/sales-test/history/+200").json() == {"messages": [{"role": "user", "content": "Hi"}]}
