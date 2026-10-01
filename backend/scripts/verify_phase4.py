"""Phase 4 manual check against a running API: human approval -> COMMIT, rejection -> replan, 2-attempt limit.

From backend/ (the seed step RESETS DATABASE_URL to the X1 baseline):
    python -m app.data.seed_data
    uvicorn app.main:app                                   # in another terminal
    python scripts/verify_phase4.py http://localhost:8000 approve|replan|exhaust

    approve  supplier ACCEPTs both shortages -> AWAITING_APPROVAL -> approve -> APPROVED, sessions COMMITTED,
             plan VALIDATED, stock reserved
    replan   Display REJECT, Battery ACCEPT -> approve refused (422) -> reject -> Battery ABORTED, attempt 2 with two new
             negotiations -> both ACCEPT -> approve -> APPROVED
    exhaust  every supplier answer REJECT in attempts 1 and 2 -> reject twice -> HUMAN_INTERVENTION_REQUIRED
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.data import x1_fixture as x1  # noqa: E402

TIMEOUT = 600
NAMES = {item_id: name for name, item_id in x1.COMPONENT_IDS.items()}


def call(method: str, url: str, body: dict | None = None) -> dict:
    response = httpx.request(method, url, json=body, timeout=TIMEOUT)
    print(f"{method} {url.split('8000')[-1]} -> HTTP {response.status_code}")
    return response.json()


def show_attempt(attempt: dict) -> None:
    print(f"  attempt {attempt['attempt_number']}: {attempt['approval_status']}, approvable={attempt['approvable']}, "
          f"remaining={attempt['attempts_remaining']}")
    for n in attempt["negotiations"]:
        print(f"    {NAMES.get(n['item_id'], n['item_id'])}: {n['session_status']} outcome={n['outcome']}")


def answer_all(base: str, attempt: dict, kind: str, skip: set[str] = frozenset()) -> None:
    for n in attempt["negotiations"]:
        if NAMES.get(n["item_id"]) not in skip:
            session = call("POST", f"{base}/supplier-interface/negotiations/{n['negotiation_id']}/responses",
                           {"round_number": 1, "response_type": kind})
            print(f"    {NAMES.get(n['item_id'])} {kind} -> {session.get('status')}")


def current(base: str, order: str) -> dict:
    return call("GET", f"{base}/plans/{order}/attempts")[-1]


def main(base: str, path: str) -> None:
    order = x1.ORDER_ID
    show_attempt(call("POST", f"{base}/agents/planning/orders/{order}")["attempt"])

    if path == "approve":
        answer_all(base, current(base, order), "ACCEPT")
        show_attempt(current(base, order))
        result = call("POST", f"{base}/plans/{order}/attempts/1/approve")
        show_attempt(result["attempt"])
        print(f"  plan after COMMIT: {result['plan_status']}, reservations: {len(result['reservations'])}")
    elif path == "replan":
        attempt = current(base, order)
        display = next(n for n in attempt["negotiations"] if NAMES.get(n["item_id"]) == "Display")
        call("POST", f"{base}/supplier-interface/negotiations/{display['negotiation_id']}/responses",
             {"round_number": 1, "response_type": "REJECT"})
        answer_all(base, attempt, "ACCEPT", skip={"Display"})
        print("  approve refused:", call("POST", f"{base}/plans/{order}/attempts/1/approve").get("error", {}).get("code"))
        result = call("POST", f"{base}/plans/{order}/attempts/1/reject", {"reason": "Display not secured"})
        show_attempt(result["rejected"])
        show_attempt(result["next_attempt"]["attempt"])
        answer_all(base, current(base, order), "ACCEPT")
        result = call("POST", f"{base}/plans/{order}/attempts/2/approve")
        show_attempt(result["attempt"])
        print(f"  plan after COMMIT: {result['plan_status']}")
    elif path == "exhaust":
        answer_all(base, current(base, order), "REJECT")
        result = call("POST", f"{base}/plans/{order}/attempts/1/reject", {"reason": "no agreement"})
        show_attempt(result["next_attempt"]["attempt"])
        answer_all(base, current(base, order), "REJECT")
        result = call("POST", f"{base}/plans/{order}/attempts/2/reject", {"reason": "still no agreement"})
        show_attempt(result["rejected"])
        print("  next attempt:", result["next_attempt"])
        print("  third reject:", call("POST", f"{base}/plans/{order}/attempts/2/reject").get("error", {}).get("code"))
    else:
        raise SystemExit(f"unknown path {path}")

    decisions = call("GET", f"{base}/agents/decisions?order_id={order}")
    wanted = {"PLAN_ATTEMPT_STARTED", "PLAN_APPROVED", "PLAN_REJECTED", "HUMAN_INTERVENTION_REQUIRED",
              "AGREEMENT_COMMITTED", "AGREEMENT_ABORTED", "STOCK_RESERVED"}
    print(json.dumps([f"{d['agent']}: {d['decision_type']}" for d in decisions if d["decision_type"] in wanted], indent=1))


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/"), sys.argv[2] if len(sys.argv) > 2 else "approve")
