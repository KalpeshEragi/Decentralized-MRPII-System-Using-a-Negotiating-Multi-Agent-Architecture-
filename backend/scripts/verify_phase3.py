"""Phase 3 manual check against a running API (A2A goes over real HTTP to the same app).

From backend/:
    python -m app.data.seed_data                     # WARNING: resets DATABASE_URL to the X1 baseline
    uvicorn app.main:app                             # in another terminal (Ollama optional)
    python scripts/verify_phase3.py http://localhost:8000 accept|counter|reject|fail

It hands the baseline order SO-0001 to the Planning Agent, then answers the Display negotiation as the supplier:
    accept   round 1 ACCEPT                             -> AGREEMENT_PROPOSED (not committed)
    counter  round 1 COUNTER 500 by 2026-10-30, then ACCEPT -> AGREEMENT_PROPOSED on Purchasing's counter terms
    reject   round 1 REJECT                             -> REJECTED, Planning outcome FAILED
    fail     rounds 1-3 COUNTER 500 by 2026-10-30       -> FAILED after round 3
With Ollama running, Purchasing's terms may differ from the policy values (the LLM proposes within the limits).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.data import x1_fixture as x1  # noqa: E402

TIMEOUT = 600


def show(title: str, value: object) -> None:
    print(f"\n== {title}\n{json.dumps(value, indent=2, default=str)}")


def respond(base: str, negotiation_id: str, round_number: int, kind: str, quantity=None, delivery=None) -> dict:
    body = {"round_number": round_number, "response_type": kind, "quantity": quantity, "delivery_date": delivery}
    response = httpx.post(f"{base}/supplier-interface/negotiations/{negotiation_id}/responses", json=body, timeout=TIMEOUT)
    session = response.json()
    last = session.get("messages", [{}])[-1]
    print(f"supplier round {round_number} {kind} -> HTTP {response.status_code}, status {session.get('status')}, "
          f"last message {last.get('message_type')} {last.get('payload', {}).get('terms')}")
    return session


def main(base: str, path: str) -> None:
    started = httpx.post(f"{base}/agents/planning/orders/{x1.ORDER_ID}", timeout=TIMEOUT).json()
    show("plan status and procurement after order intake", {"plan_status": started["plan_status"],
                                                             "procurement": started["procurement"]})
    display = next(p for p in started["procurement"] if p["item_id"] == x1.COMPONENT_IDS["Display"])
    negotiation_id = display["negotiation_id"]
    offer = httpx.get(f"{base}/negotiations/{negotiation_id}", timeout=TIMEOUT).json()["messages"][-1]
    print(f"\nPurchasing round-1 offer: {offer['payload']}")

    if path == "accept":
        respond(base, negotiation_id, 1, "ACCEPT")
    elif path == "counter":
        respond(base, negotiation_id, 1, "COUNTER_OFFER", 500, "2026-10-30")
        respond(base, negotiation_id, 2, "ACCEPT")
    elif path == "reject":
        respond(base, negotiation_id, 1, "REJECT")
    elif path == "fail":
        for round_number in (1, 2, 3):
            respond(base, negotiation_id, round_number, "COUNTER_OFFER", 500, "2026-10-30")
        respond(base, negotiation_id, 4, "ACCEPT")  # refused: the session has ended
    else:
        raise SystemExit(f"unknown path {path}")

    session = httpx.get(f"{base}/negotiations/{negotiation_id}", timeout=TIMEOUT).json()
    show("Display session", {k: session[k] for k in ("status", "outcome", "round_number", "agreement", "offers")})
    show("Planning procurement results",
         httpx.get(f"{base}/agents/planning/orders/{x1.ORDER_ID}/procurement-results", timeout=TIMEOUT).json())
    for agent in ("PRODUCTION_PLANNING_AGENT", "INVENTORY_AGENT", "PURCHASING_AGENT"):
        state = httpx.get(f"{base}/agents/{agent}/state", timeout=TIMEOUT).json()
        show(f"{agent} state (goal, task, limits)", {k: state[k] for k in ("current_goal", "current_task", "reserved_limits")})
    decisions = httpx.get(f"{base}/agents/decisions", params={"negotiation_id": negotiation_id}, timeout=TIMEOUT).json()
    show("decision log for the Display negotiation",
         [f"{d['agent']}: {d['decision_type']} - {d['reasoning_summary']}" for d in decisions])


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/"), sys.argv[2] if len(sys.argv) > 2 else "accept")
