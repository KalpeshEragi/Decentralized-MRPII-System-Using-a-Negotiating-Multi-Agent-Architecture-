"""No-database API checks: the RFC 9457 error format with correlation id, the A2A agent cards, and A2A refusals that
happen before any database access."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.negotiation.a2a_endpoints import LIVE_AGENTS
from app.negotiation.transport import path_for

client = TestClient(app, raise_server_exceptions=False)


def send_message(path: str, data: dict) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
            "params": {"message": {"messageId": "m-1", "role": "ROLE_USER", "parts": [{"data": data}]}}}
    response = client.post(path, json=body, headers={"A2A-Version": "1.0"})
    assert response.status_code == 200
    return response.json()["result"]["message"]["parts"][0]["data"]


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_validation_error_uses_problem_details():
    response = client.post("/sales/test-channel/messages", json={"phone": "+100"}, headers={"X-Correlation-Id": "c-1"})
    body = response.json()
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["X-Correlation-Id"] == "c-1"
    assert set(body) == {"type", "title", "status", "detail", "instance", "code", "errors", "correlation_id"}
    assert body["type"] == "urn:mrpii:problem:validation-error" and body["status"] == 422
    assert body["code"] == "VALIDATION_ERROR" and body["instance"] == "/sales/test-channel/messages"
    assert body["correlation_id"] == "c-1" and body["errors"]


def test_unknown_route_uses_problem_details():
    body = client.get("/nope").json()
    assert body["code"] == "NOT_FOUND" and body["status"] == 404


@pytest.mark.parametrize("agent", LIVE_AGENTS)
def test_agent_cards_are_served(agent):
    card = client.get(f"{path_for(agent)}/.well-known/agent-card.json")
    assert card.status_code == 200
    assert card.json()["supportedInterfaces"][0]["url"].endswith(path_for(agent))


def test_a2a_refuses_a_malformed_message_and_one_for_another_agent():
    assert send_message(path_for("HR"), {"not": "an envelope"})["error"]["code"] == "VALIDATION_ERROR"
    envelope = {"message_id": "m-2", "session_id": "6f1c0e2a-0000-4000-8000-000000000002", "case_id": "C",
                "sender": "PLANNING", "receiver": "WAREHOUSE", "message_type": "ABORT",
                "sent_at": "2026-11-02T00:00:00Z"}
    ack = send_message(path_for("HR"), envelope)  # addressed to Warehouse, sent to HR's endpoint
    assert ack["accepted"] is False and "HR" in ack["error"]["message"]


def test_a2a_refuses_price_in_terms():
    envelope = {"message_id": "m-3", "session_id": "6f1c0e2a-0000-4000-8000-000000000003", "case_id": "C",
                "sender": "PLANNING", "receiver": "HR", "message_type": "REQUEST", "sent_at": "2026-11-02T00:00:00Z",
                "terms": {"resource_type": "WORKFORCE", "resource_ref": "ASSEMBLY", "quantity": 8,
                          "extra": {"unit_price": 5}}}
    ack = send_message(path_for("HR"), envelope)
    assert ack["accepted"] is False and ack["error"]["code"] == "VALIDATION_ERROR"
