"""HTTP flow against the test database: order -> plan -> shortages -> negotiation -> supplier response, plus A2A delivery."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import a2a
from app.core.database import get_db
from app.data import x1_fixture as x1
from app.main import app
from app.services import negotiation_service
from app.schemas.negotiation import AgentType


@pytest.fixture
def client(db, engine, monkeypatch):
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(a2a, "new_session", factory)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_plan_and_shortages_over_http(client, db, order_id):
    plan = client.post("/plans", json={"order_id": str(order_id)})
    assert plan.status_code == 201
    body = plan.json()
    assert body["status"] == "SHORTAGE"
    assert body["mps"][0]["planned_quantity"] == 1000 and body["mps"][0]["planned_start"] == "2026-10-26"
    assert client.get(f"/plans/{order_id}").json() == body
    shortages = client.get(f"/plans/{order_id}/shortages").json()
    assert len(shortages) == 2
    display = next(s for s in shortages if s["shortage"]["item_id"] == x1.COMPONENT_IDS["Display"])
    assert {(s["supplier"], s["usable"]) for s in display["suppliers"]} == {
        ("Alpha Displays", True), ("Beta Optics", True), ("Gamma Screens", False)}


def test_create_order_errors_use_c5(client):
    body = {"order_number": "SO-0001", "customer_id": "6f1c0e2a-0000-4000-8000-000000000200",
            "order_date": "2026-10-01", "due_date": "2026-10-31", "priority": 1,
            "lines": [{"item_id": x1.PRODUCT_ID, "quantity": 10}]}
    assert client.post("/orders", json=body).json()["error"]["code"] == "NOT_FOUND"  # unknown customer
    assert client.get("/plans/6f1c0e2a-0000-4000-8000-000000000999").json()["error"]["code"] == "NOT_FOUND"


def test_new_order_can_be_created_and_planned(client, db):
    from app.data.seed_data import CUSTOMER_ID

    body = {"order_number": "SO-0002", "customer_id": str(CUSTOMER_ID), "order_date": "2026-10-01",
            "due_date": "2026-10-31", "priority": 2, "lines": [{"item_id": x1.PRODUCT_ID, "quantity": 100}]}
    created = client.post("/orders", json=body)
    assert created.status_code == 201
    assert client.post("/orders", json=body).json()["error"]["code"] == "CONFLICT"
    plan = client.post("/plans", json={"order_id": created.json()["id"]}).json()
    assert plan["status"] == "VALIDATED"  # 100 units: every component covered


def test_supplier_response_flow_and_a2a_delivery(client, db, order_id):
    client.post("/plans", json={"order_id": str(order_id)})
    session = client.post("/negotiations", json={"order_id": str(order_id), "item_id": x1.COMPONENT_IDS["Display"]}).json()
    negotiation_id = session["id"]
    ids = negotiation_service._agent_ids(db)

    def envelope(seq, sender, receiver, kind, terms=None):
        return {
            "message_id": f"6f1c0e2a-0000-4000-8000-0000000010{seq:02d}", "negotiation_id": negotiation_id,
            "sender": {"agent_id": ids[sender], "agent_type": sender.value},
            "receiver": {"agent_id": ids[receiver], "agent_type": receiver.value},
            "message_type": kind, "sequence_number": seq, "timestamp": "2026-10-01T00:00:00Z",
            "payload": {"terms": terms} if terms else {},
        }

    request = envelope(1, AgentType.INVENTORY, AgentType.PURCHASING, "REQUEST", {"quantity": 500, "required_date": "2026-10-26"})
    assert client.post(f"/negotiations/{negotiation_id}/messages", json=request).json()["status"] == "NEGOTIATING"

    def send_message(path, data):  # A2A transport: the same envelope as one data part of a JSON-RPC SendMessage
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
               "params": {"message": {"messageId": "spike", "role": "ROLE_USER", "parts": [{"data": data}]}}}
        response = client.post(path, json=rpc, headers={"A2A-Version": "1.0"})
        return response.json()["result"]["message"]["parts"][0]["data"]

    offer = envelope(2, AgentType.PURCHASING, AgentType.SUPPLIER_INTERFACE, "OFFER", {"quantity": 500, "delivery_date": "2026-10-15"})
    ack = send_message("/a2a/supplier-interface", offer)
    assert ack["accepted"] is True and ack["round_number"] == 1 and ack["session_status"] == "NEGOTIATING"
    duplicate = send_message("/a2a/supplier-interface", offer)
    assert duplicate["accepted"] is False

    stale = client.post(f"/negotiations/{negotiation_id}/supplier-responses", json={"round_number": 2, "response_type": "ACCEPT"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    ok = client.post(f"/negotiations/{negotiation_id}/supplier-responses", json={"round_number": 1, "response_type": "ACCEPT"})
    assert ok.status_code == 200 and ok.json()["awaiting_supplier"] is False
    assert client.get(f"/negotiations/{negotiation_id}").json()["round_number"] == 1
