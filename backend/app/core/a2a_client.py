"""A2A client: sends one C4 envelope to an A2A endpoint of this app and returns its acknowledgement.

Same transport as the Phase 2 spike (`app/api/a2a.py`, `scripts/a2a_spike_client.py`): a JSON-RPC `SendMessage` of the
official A2A protocol whose message carries the envelope as one data part. The endpoint answers with one data part
(`accepted`, `session_status`, `round_number`, `outcome`, or `error`). The client decides nothing.

The endpoints live in this same app at `A2A_BASE_URL`. Tests replace the HTTP client (e.g. with a FastAPI TestClient)
through `set_http_client`; the wire format stays the same.
"""

import uuid

import httpx

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.schemas.negotiation import AgentType, NegotiationMessage

PATHS = {
    AgentType.INVENTORY: "/a2a/inventory",
    AgentType.PURCHASING: "/a2a/purchasing",
}
HEADERS = {"A2A-Version": "1.0"}
TIMEOUT = 300.0  # a delivery returns after the receiving agent has reacted, which may include LLM calls

_http_client: httpx.Client | None = None


def set_http_client(client: httpx.Client | None) -> None:
    global _http_client
    _http_client = client


def send(message: NegotiationMessage) -> dict:
    """Deliver `message` to the endpoint of its receiver type; returns the endpoint's acknowledgement."""
    path = PATHS.get(message.receiver.agent_type)
    if path is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"no A2A endpoint receives {message.receiver.agent_type.value} messages")
    rpc = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"data": message.model_dump(mode="json")}],
            }
        },
    }
    client = _http_client or httpx.Client(base_url=get_settings().a2a_base_url, timeout=TIMEOUT)
    try:
        response = client.post(path, json=rpc, headers=HEADERS)
        response.raise_for_status()
        return response.json()["result"]["message"]["parts"][0]["data"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "an A2A endpoint could not be reached") from exc
    finally:
        if client is not _http_client:
            client.close()
