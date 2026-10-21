"""All-or-nothing split negotiation on the test database: each Leg is negotiated in its own chat; the agreement is
proposed only when every Leg agreed, and one failed Leg fails the whole procurement. Fixture scenarios B1 and N3
(BAT-200, 800 by 2026-11-12 → Volt Power 400 + Cell Works 400). N8 and split approval receipts: test_approval_api.py.

Fixed clock: 2026-11-02 in Asia/Kolkata, the fixture's selection date.
"""

import uuid

from app.supplier_service.seed import ITEM_IDS


def submit_b1(client) -> dict:
    response = client.post("/purchasing/procurement-requests", json={
        "request_ref": "REQ-B1", "item_id": str(ITEM_IDS["BAT-200"]), "shortage_quantity": 800,
        "required_date": "2026-11-12", "priority": 1, "requested_by": "test"})
    assert response.status_code == 201
    return response.json()


def legs_by_supplier(request: dict) -> dict[str, dict]:
    return {leg["supplier"]["name"]: leg for leg in request["legs"]}


def reply(client, leg: dict, text: str):
    return client.post(f"/purchasing/test-channel/conversations/{leg['id']}/messages",
                       json={"message_id": str(uuid.uuid4()), "text": text})


def request_of(client, request: dict) -> dict:
    return client.get(f"/purchasing/procurement-requests/{request['id']}").json()


def receipts(client) -> list[dict]:
    return client.get("/purchasing/scheduled-receipts").json()


def test_b1_the_split_is_proposed_only_when_both_legs_agreed(client):
    request = submit_b1(client)
    legs = legs_by_supplier(request)

    assert reply(client, legs["Volt Power"], "ACCEPT").status_code == 201
    halfway = request_of(client, request)
    assert halfway["status"] == "NEGOTIATING"  # one Leg agreed is not an agreement
    assert {name: leg["status"] for name, leg in legs_by_supplier(halfway).items()} == {
        "Volt Power": "AGREED", "Cell Works": "PENDING"}

    assert reply(client, legs["Cell Works"], "COUNTER 400 2026-11-11").status_code == 201
    proposed = request_of(client, request)
    assert proposed["status"] == "AGREEMENT_PROPOSED"
    assert {name: (leg["status"], leg["agreed_quantity"], leg["agreed_delivery_date"], leg["negotiation"]["status"])
            for name, leg in legs_by_supplier(proposed).items()} == {
        "Volt Power": ("AGREED", "400", "2026-11-12", "AGREED"),
        "Cell Works": ("AGREED", "400", "2026-11-11", "AGREED")}
    assert proposed["constrained_quantity"] is None


def test_b1_one_leg_rejecting_fails_the_whole_procurement_and_aborts_the_agreed_leg(client):
    request = submit_b1(client)
    legs = legs_by_supplier(request)
    reply(client, legs["Volt Power"], "ACCEPT")  # Volt agreed first

    assert reply(client, legs["Cell Works"], "REJECT").status_code == 201

    failed = request_of(client, request)
    assert failed["status"] == "FAILED" and "supplier_rejected" in failed["status_reason"]
    # What the selected suppliers could still supply: Volt 400; Cell refused, so nothing from it.
    assert failed["constrained_quantity"] == "400"
    after = legs_by_supplier(failed)
    assert {name: (leg["status"], leg["status_reason"]) for name, leg in after.items()} == {
        "Volt Power": ("ABORTED", "split_failed"), "Cell Works": ("FAILED", "supplier_rejected")}

    volt = after["Volt Power"]["negotiation"]
    assert (volt["status"], volt["status_reason"]) == ("CANCELLED", "split_failed")  # even though it had agreed
    cancel = volt["messages"][-1]
    assert (cancel["sender_type"], cancel["message_type"]) == ("AGENT", "CANCEL")
    cell = after["Cell Works"]["negotiation"]
    assert (cell["status"], cell["status_reason"]) == ("REJECTED", "supplier_rejected")

    # Re-sourcing finds no replacement: Ion Supply arrives 11-14, after the required 11-12; no new Leg is opened.
    assert len(failed["legs"]) == 2
    # Nothing is committed or counted as a scheduled receipt; approval is refused.
    approve = client.post(f"/purchasing/procurement-requests/{request['id']}/approve", json={"decided_by": "approver"})
    assert approve.status_code == 409 and approve.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert receipts(client) == []

    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    rejection = [a for a in audit if a["decision_type"] == "RESPONSE_VALIDATION"][-1]
    assert rejection["decision"]["reason"] == "supplier_rejected"
    assert (rejection["decision"]["request_status"], rejection["decision"]["constrained_quantity"]) == ("FAILED", "400")
    assert rejection["decision"]["aborted_legs"] == [after["Volt Power"]["id"]]


def test_b1_a_leg_still_pending_is_aborted_and_its_negotiation_closed(client):
    request = submit_b1(client)
    legs = legs_by_supplier(request)

    reply(client, legs["Volt Power"], "REJECT")

    failed = request_of(client, request)
    assert (failed["status"], failed["constrained_quantity"]) == ("FAILED", "500")  # Cell Works has 500 available
    cell = legs_by_supplier(failed)["Cell Works"]
    assert (cell["status"], cell["status_reason"]) == ("ABORTED", "split_failed")
    assert (cell["negotiation"]["status"], cell["negotiation"]["round_count"]) == ("CANCELLED", 1)
    assert [m["message_type"] for m in cell["negotiation"]["messages"]] == ["OFFER", "CANCEL"]

    # Cell's reply now arrives too late: refused, and nothing changes.
    late = reply(client, cell, "ACCEPT")
    assert late.status_code == 409 and late.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert request_of(client, request) == failed


def test_b1_a_leg_failing_on_the_round_limit_fails_the_procurement_too(client):
    request = submit_b1(client)
    legs = legs_by_supplier(request)
    reply(client, legs["Volt Power"], "ACCEPT")

    for _ in range(3):  # a late date each round: countered with the required date, then the round limit
        assert reply(client, legs["Cell Works"], "COUNTER 400 2026-11-15").status_code == 201

    failed = request_of(client, request)
    assert failed["status"] == "FAILED" and "round_limit_exceeded" in failed["status_reason"]
    assert failed["constrained_quantity"] == "400"  # Cell's only offers were late: nothing from it
    assert {name: (leg["status"], leg["status_reason"]) for name, leg in legs_by_supplier(failed).items()} == {
        "Volt Power": ("ABORTED", "split_failed"), "Cell Works": ("FAILED", "round_limit_exceeded")}
    assert legs_by_supplier(failed)["Volt Power"]["negotiation"]["status"] == "CANCELLED"
    assert receipts(client) == []


def test_n3_the_failed_supplier_counts_its_last_on_time_offer_in_the_constrained_quantity(client):
    request = submit_b1(client)
    legs = legs_by_supplier(request)

    for _ in range(3):  # "max 300" each round: countered back with 400 until the round limit
        reply(client, legs["Cell Works"], "COUNTER 300 2026-11-12")

    failed = request_of(client, request)
    assert failed["status"] == "FAILED" and "round_limit_exceeded" in failed["status_reason"]
    assert failed["constrained_quantity"] == "700"  # Volt 400 + Cell's last on-time offer 300
    volt = legs_by_supplier(failed)["Volt Power"]
    assert (volt["status"], volt["status_reason"], volt["negotiation"]["status"]) == (
        "ABORTED", "split_failed", "CANCELLED")
    assert receipts(client) == []
