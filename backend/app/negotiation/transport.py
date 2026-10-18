"""A2A transport for negotiation messages (NG-1): a JSON-RPC `SendMessage` of the official A2A protocol whose message
carries the envelope as one data part; the endpoint answers with one data part (the acknowledgement). Same wire format
as the retired 25% client. The endpoints live in this same app at `A2A_BASE_URL`; tests replace
the HTTP client with a FastAPI TestClient through `set_http_client`."""

import uuid

import httpx

from app.core.config import get_settings

HEADERS = {"A2A-Version": "1.0"}
TIMEOUT = 30.0  # the endpoint only stores and acknowledges; no agent work happens inside the request

_http_client: httpx.Client | None = None


def path_for(agent: str) -> str:
    return f"/a2a/{agent.lower()}"


def set_http_client(client: httpx.Client | None) -> None:
    global _http_client
    _http_client = client


def send(receiver: str, envelope: dict) -> dict:
    """Deliver one envelope to `receiver`'s endpoint and return its acknowledgement. Raises httpx errors on failure."""
    rpc = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"data": envelope}]}},
    }
    client = _http_client or httpx.Client(base_url=get_settings().a2a_base_url, timeout=TIMEOUT)
    try:
        response = client.post(path_for(receiver), json=rpc, headers=HEADERS)
        response.raise_for_status()
        body = response.json()
        if "error" in body:  # JSON-RPC error: the endpoint failed (not a protocol refusal) -> retried by the outbox
            raise RuntimeError(f"A2A endpoint {path_for(receiver)} failed: {body['error']}")
        return body["result"]["message"]["parts"][0]["data"]
    finally:
        if client is not _http_client:
            client.close()
