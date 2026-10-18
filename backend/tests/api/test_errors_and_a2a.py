"""No-database API checks: C5 error format, A2A agent cards and refusals that happen before any database access."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)
A2A_HEADERS = {"A2A-Version": "1.0"}


def send_message(path: str, data: dict) -> dict:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {"message": {"messageId": "spike-1", "role": "ROLE_USER", "parts": [{"data": data}]}},
    }
    response = client.post(path, json=body, headers=A2A_HEADERS)
    assert response.status_code == 200
    return response.json()["result"]["message"]["parts"][0]["data"]


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_validation_error_uses_c5_format():
    body = client.post("/orders", json={"order_number": "X"}).json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(body["error"]["details"], list) and body["error"]["details"]


def test_unknown_route_uses_c5_format():
    body = client.get("/nope").json()
    assert body["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("path", ["/a2a/inventory", "/a2a/purchasing"])
def test_agent_cards_are_served(path):
    card = client.get(f"{path}/.well-known/agent-card.json")
    assert card.status_code == 200
    assert card.json()["supportedInterfaces"][0]["url"].endswith(path)


def test_a2a_refuses_a_malformed_envelope_without_touching_the_database():
    ack = send_message("/a2a/inventory", {"not": "an envelope"})
    assert ack["accepted"] is False
    assert ack["error"]["code"] == "VALIDATION_ERROR"


def test_a2a_endpoint_refuses_a_message_for_another_receiver():
    envelope = {
        "message_id": "6f1c0e2a-0000-4000-8000-000000000001",
        "negotiation_id": "6f1c0e2a-0000-4000-8000-000000000002",
        "sender": {"agent_id": "a", "agent_type": "INVENTORY"},
        "receiver": {"agent_id": "b", "agent_type": "PURCHASING"},
        "message_type": "REQUEST",
        "sequence_number": 1,
        "timestamp": "2026-10-01T00:00:00Z",
        "payload": {"terms": {"quantity": 500, "required_date": "2026-10-26"}},
    }
    ack = send_message("/a2a/inventory", envelope)  # addressed to PURCHASING, sent to the Inventory endpoint
    assert ack["accepted"] is False and "INVENTORY" in ack["error"]["message"]


def test_a2a_refuses_commit_until_the_approval_workflow_exists():
    envelope = {
        "message_id": "6f1c0e2a-0000-4000-8000-000000000003",
        "negotiation_id": "6f1c0e2a-0000-4000-8000-000000000002",
        "sender": {"agent_id": "approval-workflow", "agent_type": "APPROVAL_WORKFLOW"},
        "receiver": {"agent_id": "a", "agent_type": "INVENTORY"},
        "message_type": "COMMIT",
        "sequence_number": 9,
        "timestamp": "2026-10-01T00:00:00Z",
    }
    ack = send_message("/a2a/inventory", envelope)
    assert ack["accepted"] is False and ack["error"]["code"] == "BUSINESS_RULE_VIOLATION"
