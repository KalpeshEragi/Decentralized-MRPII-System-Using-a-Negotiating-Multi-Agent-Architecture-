"""The Sales Agent's API doors, tested with a fake model on the test database.

The reply is produced in the background. The test client waits for background work before it returns, so after a POST
the reply is already there to be fetched, just like the test chat page fetches it.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.core.errors import install_error_handlers
from app.llm.client import FakeLLMClient, LLMError
from app.sales_agent import api, manager, models

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
    app.dependency_overrides[api.get_session_factory] = lambda: factory
    return TestClient(app)


def send(client, text="Hi", phone="+100", message_id=None):
    return client.post("/sales/test-channel/messages", json={
        "phone": phone, "message_id": message_id or str(uuid.uuid4()), "text": text})


def test_a_message_gets_a_quick_receipt_then_a_reply_and_a_repeated_delivery_changes_nothing(db, engine):
    model = FakeLLMClient([ANSWER])
    client = make_client(engine, model)

    # Door 1: "received" with the ids. Door 2: the reply is fetched with ?after=<message id> (spaces are removed).
    response = send(client, text="  Hi  ", phone=" +100 ", message_id="wamid-1")
    received = response.json()
    assert response.status_code == 202 and received["status"] == "received"
    replies = client.get(f"/sales/conversations/{received['conversation_id']}/messages",
                         params={"after": received["message_id"]}).json()
    assert [(m["direction"], m["text"]) for m in replies["messages"]] == [("OUT", "Hello! Which product do you need?")]
    assert replies["busy"] is False

    # The channel delivers the same message again: same ids back, flagged as duplicate, and no second reply.
    again = send(client, text="Hi", phone="+100", message_id="wamid-1").json()
    assert again["status"] == "duplicate" and again["message_id"] == received["message_id"]
    page = client.get("/sales/test-channel/history/+100").json()
    assert [(m["role"], m["text"]) for m in page["messages"]] == [
        ("user", "Hi"), ("assistant", "Hello! Which product do you need?")]
    assert len(model.calls) == 1
    assert send(client, phone="+999", message_id="wamid-1").json()["status"] == "received"  # another sender: a new message

    # Bad requests are refused in the standard error format, and nothing is saved for them.
    bad_requests = [
        {"phone": "+100", "message_id": "x", "text": ""}, {"phone": "+100", "message_id": "x", "text": "   "},
        {"phone": "", "message_id": "x", "text": "Hi"}, {"phone": "+100", "text": "Hi"}, {"message_id": "x", "text": "Hi"},
        {"phone": "+100", "message_id": "x", "text": "x" * 2001},
    ]
    for body in bad_requests:
        response = client.post("/sales/test-channel/messages", json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR", body
    assert len(client.get("/sales/test-channel/history/+100").json()["messages"]) == 2

    # A model that is down: the customer still gets an answer (an apology), and the message is kept.
    down = make_client(engine, BrokenModel())
    receipt = send(down, text="Anyone?", phone="+200").json()
    messages = down.get(f"/sales/conversations/{receipt['conversation_id']}/messages").json()["messages"]
    assert [(m["direction"], m["text"]) for m in messages] == [("IN", "Anyone?"), ("OUT", manager.SAFE_APOLOGY)]


def test_the_viewing_doors_show_what_happened_and_unknown_things_are_not_found(db, engine):
    client = make_client(engine, FakeLLMClient([ANSWER]))
    receipt = send(client, phone="+919876543210").json()
    conversation_id = receipt["conversation_id"]

    # Door 4: the conversation, its stage, and its messages. Door 5: the inquiry behind it.
    conversation = client.get(f"/sales/conversations/{conversation_id}").json()
    assert (conversation["channel"], conversation["status"], conversation["busy"]) == ("TEST", "OPEN", False)
    assert conversation["inquiry"]["stage"] == "GATHERING" and len(conversation["messages"]) == 2
    inquiry = client.get(f"/sales/inquiries/{conversation['inquiry']['id']}").json()
    assert inquiry["stage"] == "GATHERING" and inquiry["options"] == [] and inquiry["selected_option_id"] is None

    # Door 6: a customer by id or by phone (written differently). Not found if there is none.
    assert client.get("/sales/customers", params={"phone": "+919876543210"}).status_code == 404
    customer = models.Customer(phone="+919876543210", name="Asha")
    db.add(customer)
    db.commit()
    by_phone = client.get("/sales/customers", params={"phone": "+91 98765-43210"}).json()
    assert by_phone["customer"]["name"] == "Asha" and by_phone["orders"] == []
    assert client.get(f"/sales/customers/{customer.id}").json() == by_phone

    # Unknown ids, and an "after" message from another conversation, are 404 in the standard format.
    unknown = uuid.uuid4()
    for url in (f"/sales/conversations/{unknown}", f"/sales/conversations/{unknown}/messages",
                f"/sales/inquiries/{unknown}", f"/sales/customers/{unknown}",
                f"/sales/conversations/{conversation_id}/messages?after={unknown}"):
        response = client.get(url)
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND", url

    # Door 8 closes every open test conversation (nothing is deleted); the page and clearing work too.
    send(client, phone="+300")
    assert client.post("/sales/test-channel/reset").json() == {"status": "reset", "closed_conversations": 2}
    assert client.get("/sales/test-channel/history/+300").json()["messages"] == []
    assert client.get(f"/sales/conversations/{conversation_id}").json()["status"] == "CLOSED"
    assert client.delete("/sales/test-channel/history/+300").json() == {"status": "cleared"}
    assert "Sales Agent test channel" in client.get("/sales/test-channel").text
