"""HTTP calls between agents' machine doors in this same app (PB-2), e.g. Planning -> Sales door 3 and
Sales -> Planning door 1. Callers retry through their outboxes; tests swap the client with `set_http_client`."""

import threading

import httpx

from app.core.config import get_settings

TIMEOUT = 30.0
_http_client: httpx.Client | None = None
_shared: httpx.Client | None = None
_shared_lock = threading.Lock()


def shared_client() -> httpx.Client:
    """One HTTP client for every in-app call, reused (httpx clients are thread-safe). Creating a client per call cost
    0.4-0.6 s on Windows (it loads the certificate store) and made every negotiation message wait in the outbox."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = httpx.Client(base_url=get_settings().a2a_base_url, timeout=TIMEOUT)
        return _shared


def set_http_client(client: httpx.Client | None) -> None:
    global _http_client
    _http_client = client


def post(path: str, body: dict, headers: dict | None = None) -> httpx.Response:
    """POST and return the response; raises on network errors and on 5xx (so the caller's outbox retries)."""
    client = _http_client or shared_client()
    response = client.post(path, json=body, headers=headers or {})
    if response.status_code >= 500:
        raise RuntimeError(f"{path} answered {response.status_code}")
    return response
