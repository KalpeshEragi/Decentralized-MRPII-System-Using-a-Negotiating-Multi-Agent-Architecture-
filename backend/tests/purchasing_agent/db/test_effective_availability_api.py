"""Effective availability on the test database (§6.3): a supplier's available quantity less what other requests' Legs
hold with it. Fixture scenario E2, holds released when a Leg fails or is aborted, holds in reallocation, and two
simultaneous requests that can't both claim the same quantity.

Fixed clock: 2026-11-02 in Asia/Kolkata, the fixture's selection date.
"""

import threading
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent import api
from app.supplier_service.seed import ITEM_IDS


def post_request(client, ref: str, quantity: int, required_date: str = "2026-11-12"):
    return client.post("/purchasing/procurement-requests", json={
        "request_ref": ref, "item_id": str(ITEM_IDS["SPK-500"]), "shortage_quantity": quantity,
        "required_date": required_date, "priority": 1, "requested_by": "test"})


def submit(client, ref: str, quantity: int) -> dict:
    response = post_request(client, ref, quantity)
    assert response.status_code == 201
    return response.json()


def legs(request: dict) -> dict[str, str]:
    """Each selected supplier's allocated quantity."""
    return {leg["supplier"]["name"]: leg["allocated_quantity"] for leg in request["legs"]}


def reply(client, leg: dict, text: str):
    response = client.post(f"/purchasing/test-channel/conversations/{leg['id']}/messages",
                           json={"message_id": str(uuid.uuid4()), "text": text})
    assert response.status_code == 201


def request_of(client, request: dict) -> dict:
    return client.get(f"/purchasing/procurement-requests/{request['id']}").json()


def selection_audit(client, request: dict) -> dict:
    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    return next(a for a in audit if a["decision_type"] == "SUPPLIER_SELECTION")


def test_e2_a_supplier_held_by_a_pending_leg_is_not_offered_again(client):
    e2a = submit(client, "REQ-E2a", 400)
    assert (e2a["split_type"], legs(e2a)) == ("SINGLE", {"Sonic Audio": "400"})
    assert e2a["selection"]["decision"]["total_cost"] == "120000.00"

    e2b = submit(client, "REQ-E2b", 300)  # E2a's Leg is still PENDING

    assert (e2b["split_type"], legs(e2b)) == ("SINGLE", {"EchoTech": "300"})
    assert e2b["selection"]["decision"]["total_cost"] == "96000.00"  # without the hold: Sonic 300 = 90,000
    sonic = next(o for o in e2b["selection"]["options"] if o["supplier_name"] == "Sonic Audio")
    assert (sonic["available_qty"], sonic["reason"]) == ("100", "cannot_cover_alone")
    assert selection_audit(client, e2b)["context"]["availability"]["Sonic Audio"] == {
        "available_qty": "500", "held_quantity": "400"}


def test_a_failed_leg_releases_its_hold(client):
    e2a = submit(client, "REQ-E2a", 400)
    reply(client, e2a["legs"][0], "REJECT")
    assert request_of(client, e2a)["legs"][0]["status"] == "FAILED"

    e2b = submit(client, "REQ-E2b", 300)

    assert legs(e2b) == {"Sonic Audio": "300"}
    assert e2b["selection"]["decision"]["total_cost"] == "90000.00"


def test_agreed_and_committed_legs_keep_their_hold(client):
    e2a = submit(client, "REQ-E2a", 400)
    reply(client, e2a["legs"][0], "ACCEPT")
    assert legs(submit(client, "REQ-E2b", 300)) == {"EchoTech": "300"}  # Sonic AGREED 400

    approved = client.post(f"/purchasing/procurement-requests/{e2a['id']}/approve", json={"decided_by": "approver"})
    assert approved.status_code == 200 and request_of(client, e2a)["legs"][0]["status"] == "COMMITTED"

    # Sonic still holds 400 (COMMITTED) and EchoTech 300 (E2b, PENDING): only Wave Acoustics covers.
    assert legs(submit(client, "REQ-E2c", 300)) == {"Wave Acoustics": "300"}


def test_a_rejected_approval_releases_the_holds(client):
    e2a = submit(client, "REQ-E2a", 400)
    reply(client, e2a["legs"][0], "ACCEPT")
    rejected = client.post(f"/purchasing/procurement-requests/{e2a['id']}/reject", json={"decided_by": "approver"})
    assert rejected.status_code == 200

    assert legs(submit(client, "REQ-E2b", 300)) == {"Sonic Audio": "300"}


def test_reallocation_counts_other_requests_holds(client):
    submit(client, "REQ-E2a", 400)  # holds Sonic Audio 400 of 500
    split = submit(client, "REQ-R", 600)
    assert (split["split_type"], legs(split)) == (
        "NECESSARY_SPLIT", {"Sonic Audio": "100", "EchoTech": "300", "Wave Acoustics": "200"})

    wave = next(leg for leg in split["legs"] if leg["supplier"]["name"] == "Wave Acoustics")
    reply(client, wave, "COUNTER 150 2026-11-08")

    # Sonic 100 (not 500: E2a holds 400) + EchoTech 300 + Wave 150 = 550 < 600: no allocation fits, so Purchasing
    # counters Wave back with its 200.
    after = request_of(client, split)
    assert legs(after) == {"Sonic Audio": "100", "EchoTech": "300", "Wave Acoustics": "200"}
    wave = next(leg for leg in after["legs"] if leg["supplier"]["name"] == "Wave Acoustics")
    last = wave["negotiation"]["messages"][-1]
    assert (last["message_type"], last["terms"]) == ("COUNTER_OFFER", {"quantity": "200", "delivery_date": "2026-11-12"})
    audit = client.get(f"/purchasing/procurement-requests/{split['id']}/audit").json()
    [reallocation] = [a for a in audit if a["decision_type"] == "REALLOCATION"]
    assert reallocation["decision"]["outcome"] == "FAILED"
    sonic = next(o for o in reallocation["context"]["selected_suppliers"] if o["supplier_name"] == "Sonic Audio")
    assert sonic["available_qty"] == "100"


def test_two_simultaneous_requests_cannot_both_claim_the_same_quantity(client, monkeypatch):
    # Opening a Leg's Engine session is made slow, so both requests are in flight together: without the lock, both
    # would read no holds and both pick Sonic Audio 400 of its 500.
    open_session = negotiation_engine.open_session

    def slow_open_session(*args, **kwargs):
        time.sleep(0.5)
        return open_session(*args, **kwargs)

    monkeypatch.setattr(negotiation_engine, "open_session", slow_open_session)
    start = threading.Barrier(2)
    responses = {}

    def send(ref: str):
        own_client = TestClient(client.app)
        start.wait()
        responses[ref] = post_request(own_client, ref, 400)

    threads = [threading.Thread(target=send, args=(ref,)) for ref in ("REQ-X", "REQ-Y")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    assert [responses[ref].status_code for ref in ("REQ-X", "REQ-Y")] == [201, 201]
    selections = sorted((r.json()["split_type"], legs(r.json())) for r in responses.values())
    assert selections == [("NECESSARY_SPLIT", {"Sonic Audio": "100", "EchoTech": "300"}),
                          ("SINGLE", {"Sonic Audio": "400"})]


# Stale holds (confirmed 2026-10-18, code review): before availability is calculated, other requests' Legs past their
# response deadline are timed out, releasing their holds. The clock starts at 2026-11-02 10:00 Asia/Kolkata.

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def at(client, moment: datetime) -> None:
    client.app.dependency_overrides[api.get_clock] = lambda: lambda: moment


def audit_types(client, request: dict) -> list[str]:
    return [a["decision_type"] for a in client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()]


def test_a_selection_first_times_out_an_overdue_leg_holding_the_supplier(client):
    e2a = submit(client, "REQ-E2a", 400)  # Sonic Audio 400 of 500, due by 2026-11-03 10:00
    at(client, NOW + timedelta(hours=25))

    e2b = submit(client, "REQ-E2b", 300)  # nothing reads E2a first

    assert legs(e2b) == {"Sonic Audio": "300"}  # the hold was released: Sonic 300 = 90,000
    after = request_of(client, e2a)
    assert (after["status"], after["legs"][0]["status"], after["legs"][0]["status_reason"]) == (
        "FAILED", "FAILED", "timeout")
    assert "RESPONSE_DEADLINE" in audit_types(client, e2a)


def test_a_reallocation_first_times_out_an_overdue_leg_holding_a_supplier(client):
    e2a = submit(client, "REQ-E2a", 400)  # holds Sonic Audio 400 of 500, due by 2026-11-03 10:00
    at(client, NOW + timedelta(hours=20))
    split = submit(client, "REQ-R", 600)  # Sonic 100 + EchoTech 300 + Wave 200, due by 2026-11-03 06:00 + 24h
    assert legs(split) == {"Sonic Audio": "100", "EchoTech": "300", "Wave Acoustics": "200"}
    wave = next(leg for leg in split["legs"] if leg["supplier"]["name"] == "Wave Acoustics")
    at(client, NOW + timedelta(hours=25))  # E2a is overdue; REQ-R is not

    reply(client, wave, "COUNTER 150 2026-11-08")

    # Sonic's 500 are free again: Sonic 500 + EchoTech 100 = 182,000 beats every allocation with Wave.
    after = request_of(client, split)
    assert {leg["supplier"]["name"]: (leg["status"], leg["allocated_quantity"]) for leg in after["legs"]} == {
        "Sonic Audio": ("PENDING", "500"), "EchoTech": ("PENDING", "100"), "Wave Acoustics": ("ABORTED", "200")}
    assert request_of(client, e2a)["legs"][0]["status_reason"] == "timeout"
