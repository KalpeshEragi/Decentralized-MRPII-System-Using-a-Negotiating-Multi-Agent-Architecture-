"""A2A transport spike client. Start the API first (`uvicorn app.main:app` from backend/), then:

    python scripts/a2a_spike_client.py http://localhost:8000 <negotiation_id>

It sends the C4 REQUEST (Inventory -> Purchasing) and OFFER (Purchasing -> supplier interface) for an existing session
(create one with POST /negotiations) as A2A `SendMessage` calls, one data part each, and prints the acknowledgements.
Then it sends the same OFFER again (refused as a duplicate) and a malformed envelope (refused as invalid).
"""

import sys
import uuid

import httpx

HEADERS = {"A2A-Version": "1.0"}


def send(base: str, path: str, envelope: dict) -> dict:
    rpc = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"data": envelope}]}},
    }
    response = httpx.post(base + path, json=rpc, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()["result"]["message"]["parts"][0]["data"]


def main(base: str, negotiation_id: str) -> None:
    session = httpx.get(f"{base}/negotiations/{negotiation_id}", timeout=30).json()
    ids = session["participants"]
    print("session:", session["id"], session["status"])

    def envelope(seq, sender, receiver, kind, terms):
        return {
            "message_id": str(uuid.uuid4()), "negotiation_id": negotiation_id, "sequence_number": seq,
            "sender": {"agent_id": ids[sender], "agent_type": sender},
            "receiver": {"agent_id": ids[receiver], "agent_type": receiver},
            "message_type": kind, "timestamp": "2026-10-01T00:00:00Z", "payload": {"terms": terms},
        }

    request = envelope(1, "INVENTORY", "PURCHASING", "REQUEST", {"quantity": 500, "required_date": "2026-10-26"})
    print("REQUEST ->", send(base, "/a2a/purchasing", request))
    offer = envelope(2, "PURCHASING", "SUPPLIER_INTERFACE", "OFFER", {"quantity": 500, "delivery_date": "2026-10-15"})
    print("OFFER ->", send(base, "/a2a/supplier-interface", offer))
    print("OFFER again ->", send(base, "/a2a/supplier-interface", offer))
    print("malformed ->", send(base, "/a2a/inventory", {"not": "an envelope"}))


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/"), sys.argv[2])
