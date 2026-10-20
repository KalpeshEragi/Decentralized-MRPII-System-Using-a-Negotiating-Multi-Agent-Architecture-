"""Approval on the test database: a human approves or rejects a proposed Procurement Agreement, and committed Legs
appear as scheduled receipts. Fixture scenarios N1 (to a receipt) and N8 (approval rejected).

Fixed clock: 2026-11-02 in Asia/Kolkata, the fixture's selection date.
"""

import json
import uuid

from sqlalchemy import update

from app.llm.client import FakeLLMClient
from app.purchasing_agent import api
from app.purchasing_agent.models import PurchaseRequisition
from app.supplier_service.seed import ITEM_IDS, SUPPLIER_IDS


def submit(client, ref: str, sku: str, quantity: int) -> dict:
    response = client.post("/purchasing/procurement-requests", json={
        "request_ref": ref, "item_id": str(ITEM_IDS[sku]), "shortage_quantity": quantity,
        "required_date": "2026-11-20", "priority": 1, "requested_by": "test"})
    assert response.status_code == 201
    return response.json()


def reply(client, leg_id: str, text: str):
    response = client.post(f"/purchasing/test-channel/conversations/{leg_id}/messages",
                           json={"message_id": str(uuid.uuid4()), "text": text})
    assert response.status_code == 201


def approve(client, request: dict):
    return client.post(f"/purchasing/procurement-requests/{request['id']}/approve", json={"decided_by": "approver"})


def reject(client, request: dict):
    return client.post(f"/purchasing/procurement-requests/{request['id']}/reject", json={"decided_by": "approver"})


def receipts(client) -> list[dict]:
    response = client.get("/purchasing/scheduled-receipts")
    assert response.status_code == 200
    return response.json()


def proposed_a1(client) -> dict:
    """N1: Alpha agrees to 500 by 12 Nov (A1: DSP-100, 500 by 2026-11-20)."""
    request = submit(client, "REQ-N1", "DSP-100", 500)
    [leg] = request["legs"]
    reply(client, leg["id"], "COUNTER 500 2026-11-12")
    return request


def proposed_b2(client) -> dict:
    """B2: BAT-200, 800 by 2026-11-20 → Volt 400 + Cell 400; both accept."""
    request = submit(client, "REQ-B2", "BAT-200", 800)
    for leg in request["legs"]:
        reply(client, leg["id"], "ACCEPT")
    return request


def test_n1_approval_commits_the_agreement_and_adds_one_scheduled_receipt(client):
    request = proposed_a1(client)
    assert receipts(client) == []  # agreed but not committed: no receipt yet

    response = approve(client, request)

    assert response.status_code == 200
    approved = response.json()
    assert approved["status"] == "COMMITTED" and approved["decided_at"] is not None
    [leg] = approved["legs"]
    assert (leg["status"], leg["negotiation"]["status"]) == ("COMMITTED", "AGREED")

    [receipt] = receipts(client)
    assert receipt["leg_id"] == leg["id"] and receipt["request_ref"] == "REQ-N1"
    assert receipt["supplier"] == {"id": str(SUPPLIER_IDS["Alpha Displays"]), "name": "Alpha Displays"}
    assert receipt["item"] == {"id": str(ITEM_IDS["DSP-100"]), "sku": "DSP-100", "name": "Display Panel"}
    assert (receipt["quantity"], receipt["delivery_date"]) == ("500", "2026-11-12")

    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    [decision] = [a for a in audit if a["decision_type"] == "APPROVAL"]
    assert decision["decision"]["outcome"] == "APPROVED"
    assert decision["context"]["decided_by"] == "approver"
    assert decision["context"]["legs"] == [{"leg_id": leg["id"], "supplier_id": leg["supplier"]["id"],
                                            "quantity": "500", "delivery_date": "2026-11-12"}]


def test_approval_of_a_split_commits_every_leg_with_one_receipt_each(client):
    request = proposed_b2(client)

    approved = approve(client, request).json()

    assert approved["status"] == "COMMITTED"
    assert [leg["status"] for leg in approved["legs"]] == ["COMMITTED", "COMMITTED"]
    assert sorted((r["supplier"]["name"], r["quantity"]) for r in receipts(client)) == [
        ("Cell Works", "400"), ("Volt Power", "400")]


def test_n8_rejection_aborts_every_leg_and_adds_no_receipt(client):
    request = proposed_b2(client)

    response = reject(client, request)

    assert response.status_code == 200
    rejected = response.json()
    assert rejected["status"] == "APPROVAL_REJECTED" and rejected["decided_at"] is not None
    assert [(leg["status"], leg["status_reason"]) for leg in rejected["legs"]] == [
        ("ABORTED", "approval_rejected"), ("ABORTED", "approval_rejected")]
    for leg in rejected["legs"]:  # each supplier is told and its Engine session cancelled
        session = leg["negotiation"]
        assert (session["status"], session["status_reason"]) == ("CANCELLED", "approval_rejected")
        assert (session["messages"][-1]["sender_type"], session["messages"][-1]["message_type"]) == ("AGENT", "CANCEL")
    assert receipts(client) == []

    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    [decision] = [a for a in audit if a["decision_type"] == "APPROVAL"]
    assert decision["decision"]["outcome"] == "REJECTED"


def test_a_decided_request_cannot_be_decided_again(client):
    approved = proposed_a1(client)
    approve(client, approved)
    rejected = proposed_b2(client)
    reject(client, rejected)

    for stale in (approve(client, approved), reject(client, approved), approve(client, rejected)):
        assert stale.status_code == 409
        error = stale.json()  # RFC 9457 problem details (API-1)
        assert error["code"] == "INVALID_STATE_TRANSITION"
        assert error["errors"][0]["field"] == "status"

    assert request_status(client, approved) == "COMMITTED"
    assert request_status(client, rejected) == "APPROVAL_REJECTED"
    [receipt] = receipts(client)  # still only the one from the first approval
    assert receipt["request_ref"] == "REQ-N1"
    audit = client.get(f"/purchasing/procurement-requests/{approved['id']}/audit").json()
    assert len([a for a in audit if a["decision_type"] == "APPROVAL"]) == 1  # refusals change nothing


def test_a_request_still_negotiating_cannot_be_approved_or_rejected(client):
    request = submit(client, "REQ-B2", "BAT-200", 800)
    reply(client, request["legs"][0]["id"], "ACCEPT")  # only one of the two Legs agreed

    for refused in (approve(client, request), reject(client, request)):
        assert refused.status_code == 409 and refused.json()["code"] == "INVALID_STATE_TRANSITION"

    after = client.get(f"/purchasing/procurement-requests/{request['id']}").json()
    assert after["status"] == "NEGOTIATING"
    assert sorted(leg["status"] for leg in after["legs"]) == ["AGREED", "PENDING"]
    assert receipts(client) == []


def test_approving_an_unknown_request_or_without_an_approver_is_refused(client):
    assert approve(client, {"id": str(uuid.uuid4())}).status_code == 404
    request = proposed_a1(client)
    missing = client.post(f"/purchasing/procurement-requests/{request['id']}/approve", json={})
    assert missing.status_code == 422 and missing.json()["code"] == "VALIDATION_ERROR"


def request_status(client, request: dict) -> str:
    return client.get(f"/purchasing/procurement-requests/{request['id']}").json()["status"]


# -- code review 2026-10-18 (ticket 11) ------------------------------------------------------------------------------


def test_a_rejection_cancel_points_at_the_agreement_it_cancels(client):
    request = proposed_a1(client)  # single Leg

    rejected = reject(client, request).json()

    [leg] = rejected["legs"]
    *_, agreement, cancel = leg["negotiation"]["messages"]
    assert (agreement["message_type"], cancel["message_type"]) == ("CONFIRMATION", "CANCEL")
    assert cancel["causation_id"] == agreement["message_id"]
    assert (leg["status"], leg["status_reason"]) == ("ABORTED", "approval_rejected")


def test_a_proposed_agreement_with_a_leg_no_longer_agreed_is_neither_approved_nor_rejected(client, db):
    request = proposed_b2(client)
    cell = next(leg for leg in request["legs"] if leg["supplier"]["name"] == "Cell Works")
    # Not reachable through the API: an inconsistent Leg set directly, to check approval refuses it.
    db.execute(update(PurchaseRequisition).where(PurchaseRequisition.id == uuid.UUID(cell["id"]))
               .values(status="PENDING"))
    db.commit()

    for refused in (approve(client, request), reject(client, request)):
        assert refused.status_code == 409
        assert refused.json()["errors"] == [{"field": f"legs.{cell['id']}.status", "issue": "is PENDING"}]

    after = client.get(f"/purchasing/procurement-requests/{request['id']}").json()
    assert after["status"] == "AGREEMENT_PROPOSED"
    assert sorted(leg["status"] for leg in after["legs"]) == ["AGREED", "PENDING"]  # nothing committed: all or none
    assert receipts(client) == []


def test_scheduled_receipts_can_be_filtered_by_item(client):
    approve(client, proposed_a1(client))  # DSP-100
    approve(client, proposed_b2(client))  # BAT-200

    response = client.get("/purchasing/scheduled-receipts", params={"item_id": str(ITEM_IDS["BAT-200"])})

    assert response.status_code == 200
    assert sorted(r["supplier"]["name"] for r in response.json()) == ["Cell Works", "Volt Power"]
    assert len(receipts(client)) == 3


def test_n1_in_natural_language_reaches_a_scheduled_receipt(client):
    client.app.dependency_overrides[api.get_llm_client] = lambda: FakeLLMClient(
        [json.dumps({"action": "ACCEPT", "quantity": 500, "delivery_date": "2026-11-12"})])
    request = submit(client, "REQ-N1", "DSP-100", 500)
    reply(client, request["legs"][0]["id"], "ok, 500 by 12 Nov works")

    assert approve(client, request).json()["status"] == "COMMITTED"
    [receipt] = receipts(client)
    assert (receipt["supplier"]["name"], receipt["quantity"], receipt["delivery_date"]) == (
        "Alpha Displays", "500", "2026-11-12")
