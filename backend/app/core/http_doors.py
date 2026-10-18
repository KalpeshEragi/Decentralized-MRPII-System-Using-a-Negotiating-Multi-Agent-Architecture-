"""HTTP calls between agents' machine doors in this same app (PB-2), e.g. Planning -> Sales door 3 and
Sales -> Planning door 1. Callers retry through their outboxes; tests swap the client with `set_http_client`."""

import httpx

from app.core.config import get_settings

TIMEOUT = 30.0
_http_client: httpx.Client | None = None


def set_http_client(client: httpx.Client | None) -> None:
    global _http_client
    _http_client = client


def post(path: str, body: dict, headers: dict | None = None) -> httpx.Response:
    """POST and return the response; raises on network errors and on 5xx (so the caller's outbox retries)."""
    client = _http_client or httpx.Client(base_url=get_settings().a2a_base_url, timeout=TIMEOUT)
    try:
        response = client.post(path, json=body, headers=headers or {})
        if response.status_code >= 500:
            raise RuntimeError(f"{path} answered {response.status_code}")
        return response
    finally:
        if client is not _http_client:
            client.close()
