"""Phase 4 through the API on the X1 baseline (needs TEST_DATABASE_URL): human approval -> COMMIT, rejection -> replan,
at most 2 planning attempts -> human intervention (C8, D8). Uses the `api` fixture (A2A in-process, no LLM).

Baseline: shortages Display 500 and Battery 600; Purchasing offers Display 500 by 2026-10-15, Battery 600 by 2026-10-13.
"""

import uuid

from sqlalchemy import func, select

from app.data import x1_fixture as x1
from app.models import inventory
from app.services import negotiation_service


def start(api, order_id) -> dict:
    response = api.post(f"/agents/planning/orders/{order_id}")
    assert response.status_code == 200, response.text
    return response.json()


def negotiation_of(attempt: dict, component: str) -> str:
    return next(n["negotiation_id"] for n in attempt["negotiations"] if n["item_id"] == x1.COMPONENT_IDS[component])


def respond(api, negotiation_id, kind, round_number=1):
    response = api.post(f"/supplier-interface/negotiations/{negotiation_id}/responses",
                        json={"round_number": round_number, "response_type": kind})
    assert response.status_code == 200, response.text
    return response.json()


def attempts(api, order_id) -> list[dict]:
    return api.get(f"/plans/{order_id}/attempts").json()


def test_agreement_then_approval_commits(api, db, order_id):
    attempt = start(api, order_id)["attempt"]
    assert (attempt["attempt_number"], attempt["approval_status"]) == (1, "PENDING_NEGOTIATION")
    early = api.post(f"/plans/{order_id}/attempts/1/approve")
    assert early.status_code == 409 and early.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

    for component in ("Display", "Battery"):
        assert respond(api, negotiation_of(attempt, component), "ACCEPT")["status"] == "AGREEMENT_PROPOSED"
    current = attempts(api, order_id)[-1]
    assert (current["approval_status"], current["approvable"]) == ("AWAITING_APPROVAL", True)
    db.expire_all()
    assert negotiation_service.scheduled_receipts(db, set(x1.COMPONENT_IDS.values())) == []  # no automatic COMMIT

    approved = api.post(f"/plans/{order_id}/attempts/1/approve")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["attempt"]["approval_status"] == "APPROVED"
    assert body["plan_status"] == "VALIDATED"  # committed agreements now cover both shortages
    for negotiation in body["attempt"]["negotiations"]:
        view = api.get(f"/negotiations/{negotiation['negotiation_id']}").json()
        assert view["status"] == "COMMITTED" and view["agreement"]["committed"] is True
        assert view["messages"][-1]["message_type"] == "COMMIT" and view["messages"][-1]["sender"] == "APPROVAL_WORKFLOW"
    db.expire_all()
    assert len(negotiation_service.scheduled_receipts(db, set(x1.COMPONENT_IDS.values()))) == 2
    assert db.scalar(select(func.count()).select_from(inventory.InventoryReservation)) == len(body["reservations"]) > 0
    assert api.post(f"/plans/{order_id}/attempts/1/reject").status_code == 409  # decided already
    decisions = [d["decision_type"] for d in api.get("/agents/decisions", params={"order_id": str(order_id)}).json()]
    for expected in ("PLAN_ATTEMPT_STARTED", "PLAN_APPROVED", "STOCK_RESERVED"):
        assert expected in decisions


def test_plan_with_failed_shortage_cannot_be_approved_and_reject_replans(api, order_id):
    attempt = start(api, order_id)["attempt"]
    respond(api, negotiation_of(attempt, "Display"), "REJECT")
    battery = negotiation_of(attempt, "Battery")
    respond(api, battery, "ACCEPT")

    refused = api.post(f"/plans/{order_id}/attempts/1/approve")
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"

    rejected = api.post(f"/plans/{order_id}/attempts/1/reject", json={"reason": "Display not secured"})
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["rejected"]["approval_status"] == "REJECTED"
    assert body["rejected"]["decision_reason"] == "Display not secured"
    assert api.get(f"/negotiations/{battery}").json()["status"] == "ABORTED"  # uncommitted agreement closed

    second = body["next_attempt"]["attempt"]
    assert (second["attempt_number"], second["approval_status"], second["attempts_remaining"]) == (
        2, "PENDING_NEGOTIATION", 0)
    old_ids = {n["negotiation_id"] for n in attempt["negotiations"]}
    new_ids = {n["negotiation_id"] for n in second["negotiations"]}
    assert len(new_ids) == 2 and not new_ids & old_ids  # both shortages negotiated again
    assert all(n["session_status"] == "NEGOTIATING" for n in second["negotiations"])


def test_rejecting_the_last_attempt_requires_human_intervention(api, db, order_id):
    first = start(api, order_id)["attempt"]
    for component in ("Display", "Battery"):
        respond(api, negotiation_of(first, component), "REJECT")
    second = api.post(f"/plans/{order_id}/attempts/1/reject").json()["next_attempt"]["attempt"]
    for component in ("Display", "Battery"):
        respond(api, negotiation_of(second, component), "REJECT")

    final = api.post(f"/plans/{order_id}/attempts/2/reject", json={"reason": "no supplier"})
    assert final.status_code == 200, final.text
    body = final.json()
    assert body["rejected"]["approval_status"] == "HUMAN_INTERVENTION_REQUIRED" and body["next_attempt"] is None
    assert [a["approval_status"] for a in attempts(api, order_id)] == ["REJECTED", "HUMAN_INTERVENTION_REQUIRED"]
    db.expire_all()
    sessions = negotiation_service.sessions_for_order(db, uuid.UUID(str(order_id)))
    assert len(sessions) == 4  # no third attempt
    assert api.post(f"/plans/{order_id}/attempts/2/reject").status_code == 409
    assert api.post(f"/plans/{order_id}/attempts/3/reject").status_code == 409


def test_handing_the_order_again_does_not_replan(api, order_id):
    first = start(api, order_id)["attempt"]
    again = start(api, order_id)["attempt"]
    assert again["attempt_number"] == 1
    assert {n["negotiation_id"] for n in again["negotiations"]} == {n["negotiation_id"] for n in first["negotiations"]}


def test_commit_and_abort_only_through_the_approval_routes(api, order_id):
    attempt = start(api, order_id)["attempt"]
    negotiation_id = negotiation_of(attempt, "Display")
    respond(api, negotiation_id, "ACCEPT")
    session = api.get(f"/negotiations/{negotiation_id}").json()
    for kind in ("COMMIT", "ABORT"):
        envelope = {
            "message_id": str(uuid.uuid4()), "negotiation_id": negotiation_id, "sequence_number": len(session["messages"]) + 1,
            "sender": {"agent_id": "approval-workflow", "agent_type": "APPROVAL_WORKFLOW"},
            "receiver": {"agent_id": session["participants"]["INVENTORY"], "agent_type": "INVENTORY"},
            "message_type": kind, "timestamp": "2026-10-01T00:00:00Z",
        }
        refused = api.post(f"/negotiations/{negotiation_id}/messages", json=envelope)
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"
    assert api.get(f"/negotiations/{negotiation_id}").json()["status"] == "AGREEMENT_PROPOSED"
