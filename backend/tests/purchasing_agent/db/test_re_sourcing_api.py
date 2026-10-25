"""Re-sourcing on the test database (§7.4.1, ADR-003): when the open Legs can no longer cover the shortage, every
eligible supplier of the item is considered, the saving threshold is re-checked, and a dropped supplier may return
with its remembered cap and the rest of its round budget. Fixture scenarios N12 and N13 (B2: BAT-200, 800 by
2026-11-20 → Volt Power 400 + Cell Works 400), and re-sourcing on the next write after a recorded timeout.

The clock starts at 2026-11-02 10:00 Asia/Kolkata, the fixture's selection date, and is moved forward with `at`.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.purchasing_agent import api
from app.supplier_service.seed import ITEM_IDS

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # the client fixture's fixed clock


def at(client, moment: datetime) -> None:
    client.app.dependency_overrides[api.get_clock] = lambda: lambda: moment


def submit(client, ref: str, sku: str, quantity: int, required_date: str) -> dict:
    response = client.post("/purchasing/procurement-requests", json={
        "request_ref": ref, "item_id": str(ITEM_IDS[sku]), "shortage_quantity": quantity,
        "required_date": required_date, "priority": 1, "requested_by": "test"})
    assert response.status_code == 201
    return response.json()


def submit_b2(client) -> dict:
    return submit(client, "REQ-B2", "BAT-200", 800, "2026-11-20")


def reply(client, leg: dict, text: str):
    return client.post(f"/purchasing/test-channel/conversations/{leg['id']}/messages",
                       json={"message_id": str(uuid.uuid4()), "text": text})


def request_of(client, request: dict) -> dict:
    return client.get(f"/purchasing/procurement-requests/{request['id']}").json()


def open_legs(request: dict) -> dict[str, dict]:
    """The PENDING or AGREED Leg of each supplier (a returning supplier also has an old ABORTED one)."""
    return {leg["supplier"]["name"]: leg for leg in request["legs"] if leg["status"] in ("PENDING", "AGREED")}


def legs_of(request: dict, supplier: str) -> list[dict]:
    return [leg for leg in request["legs"] if leg["supplier"]["name"] == supplier]


def audits(client, request: dict, decision_type: str) -> list[dict]:
    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    return [a for a in audit if a["decision_type"] == decision_type]


def test_n12_a_cap_reallocation_cannot_absorb_brings_in_a_new_supplier_at_its_current_price(client):
    request = submit_b2(client)
    cell = open_legs(request)["Cell Works"]

    assert reply(client, cell, "COUNTER 300 2026-11-11").status_code == 201  # "max 300"

    after = request_of(client, request)
    assert (after["status"], after["split_type"]) == ("NEGOTIATING", "COST_SAVING_SPLIT")
    now = open_legs(after)
    assert {name: (leg["status"], leg["allocated_quantity"]) for name, leg in now.items()} == {
        "Volt Power": ("PENDING", "400"), "Ion Supply": ("PENDING", "400")}
    assert now["Volt Power"]["negotiation"]["round_count"] == 1  # unchanged: no revised offer
    ion = now["Ion Supply"]
    assert (ion["unit_price_at_selection"], ion["quantity_cap"], ion["negotiation"]["max_rounds"]) == (
        "1000.00", None, 3)
    [cell] = legs_of(after, "Cell Works")
    assert (cell["status"], cell["status_reason"], cell["quantity_cap"]) == ("ABORTED", "no_longer_needed", "300")

    [reallocation] = audits(client, request, "REALLOCATION")
    assert (reallocation["decision"]["outcome"], reallocation["decision"]["next_step"]) == ("FAILED", "RE_SOURCING")
    [re_sourcing] = audits(client, request, "RE_SOURCING")
    decision = re_sourcing["decision"]
    # Ion 800 = 800,000; Volt 400 + Ion 400 = 720,000 is exactly 10% under it, and beats the equal-cost 3-way split
    # on fewer suppliers.
    assert (decision["outcome"], decision["total_cost"], decision["saving_percent"]) == (
        "COST_SAVING_SPLIT", "720000.00", "10.00")
    assert decision["best_priced_single"] == {"supplier_name": "Ion Supply", "total_cost": "800000.00"}
    assert (decision["dropped_suppliers"], decision["revised_suppliers"], decision["added_suppliers"],
            decision["returning_suppliers"], decision["trigger_leg_outcome"]) == (
        ["Cell Works"], [], ["Ion Supply"], [], "NO_LONGER_NEEDED")
    candidates = {c["supplier_name"]: c for c in re_sourcing["context"]["candidates"]}
    assert (candidates["Volt Power"]["source"], candidates["Volt Power"]["unit_price_at_selection"],
            candidates["Volt Power"]["current_unit_price"]) == ("open_leg", "800.00", "800.00")
    assert (candidates["Ion Supply"]["source"], candidates["Ion Supply"]["current_unit_price"],
            candidates["Ion Supply"]["rounds_left"]) == ("new", "1000.00", 3)


def test_n13_a_dropped_supplier_returns_with_its_remembered_cap_and_the_rest_of_its_round_budget(client):
    request = submit_b2(client)
    reply(client, open_legs(request)["Cell Works"], "COUNTER 300 2026-11-11")  # N12
    ion = open_legs(request_of(client, request))["Ion Supply"]

    assert reply(client, ion, "COUNTER 350 2026-11-14").status_code == 201  # "max 350"

    after = request_of(client, request)
    assert (after["status"], after["split_type"]) == ("NEGOTIATING", "NECESSARY_SPLIT")
    now = open_legs(after)
    assert {name: (leg["status"], leg["allocated_quantity"]) for name, leg in now.items()} == {
        "Volt Power": ("PENDING", "300"), "Ion Supply": ("PENDING", "300"), "Cell Works": ("PENDING", "200")}

    old_cell, new_cell = legs_of(after, "Cell Works")  # oldest first; the old Leg stays for the audit
    assert (old_cell["status"], old_cell["status_reason"]) == ("ABORTED", "no_longer_needed")
    assert new_cell["id"] != old_cell["id"]
    assert new_cell["negotiation"]["session_id"] != old_cell["negotiation"]["session_id"]  # a new Engine session
    # 1 of its 3 rounds was used in the first session: the new one gets the other 2. The cap is remembered, and it
    # must agree again to a fresh offer.
    assert (new_cell["negotiation"]["max_rounds"], new_cell["negotiation"]["round_count"]) == (2, 1)
    assert new_cell["quantity_cap"] == "300"
    [offer] = new_cell["negotiation"]["messages"]
    assert (offer["message_type"], offer["terms"]) == ("OFFER", {"quantity": "200", "delivery_date": "2026-11-20"})

    volt = now["Volt Power"]["negotiation"]  # a revised offer: a new round
    assert (volt["round_count"], volt["messages"][-1]["terms"]) == (
        2, {"quantity": "300", "delivery_date": "2026-11-20"})
    ion = now["Ion Supply"]
    assert ion["quantity_cap"] == "350"
    assert (ion["negotiation"]["round_count"], ion["negotiation"]["messages"][-1]["terms"]) == (
        2, {"quantity": "300", "delivery_date": "2026-11-20"})  # countered with its new quantity

    last = audits(client, request, "RE_SOURCING")[-1]
    assert last["context"]["trigger"] == "quantity_counter"
    assert (last["decision"]["total_cost"], last["decision"]["returning_suppliers"],
            last["decision"]["revised_suppliers"], last["decision"]["trigger_leg_outcome"]) == (
        "720000.00", ["Cell Works"], ["Volt Power"], "COUNTER_OFFER")
    returning = next(c for c in last["context"]["candidates"] if c["supplier_name"] == "Cell Works")
    assert (returning["source"], returning["remembered_cap"], returning["remembered_date"], returning["rounds_left"]) == (
        "returning", "300", "2026-11-11", 2)

    # Everyone agrees: only the open Legs are the agreement.
    for name in ("Volt Power", "Ion Supply", "Cell Works"):
        reply(client, now[name], "ACCEPT")
    assert request_of(client, request)["status"] == "AGREEMENT_PROPOSED"
    approved = client.post(f"/purchasing/procurement-requests/{request['id']}/approve", json={"decided_by": "approver"})
    assert approved.status_code == 200
    receipts = client.get("/purchasing/scheduled-receipts").json()
    assert sorted((r["supplier"]["name"], r["quantity"]) for r in receipts) == [
        ("Cell Works", "200"), ("Ion Supply", "300"), ("Volt Power", "300")]


def test_a_supplier_reply_first_re_sources_its_request_after_a_recorded_timeout(client):
    request = submit_b2(client)
    legs = open_legs(request)
    at(client, NOW + timedelta(hours=20))
    reply(client, legs["Volt Power"], "COUNTER 400 2026-11-25")  # countered with 11-20: a fresh 24h for Volt

    at(client, NOW + timedelta(hours=25))  # Cell Works never replied
    assert request_of(client, request)["re_sourcing_needed"] is True

    accepted = reply(client, legs["Volt Power"], "ACCEPT")  # the next write: re-sourcing runs first

    assert accepted.status_code == 201  # Volt's offer was unchanged by re-sourcing, so its reply stands
    after = request_of(client, request)
    assert (after["status"], after["split_type"], after["re_sourcing_needed"]) == (
        "NEGOTIATING", "COST_SAVING_SPLIT", False)
    now = open_legs(after)
    assert {name: (leg["status"], leg["allocated_quantity"]) for name, leg in now.items()} == {
        "Volt Power": ("AGREED", "400"), "Ion Supply": ("PENDING", "400")}
    [re_sourcing] = audits(client, request, "RE_SOURCING")
    assert re_sourcing["context"]["trigger"] == "timeout"
    assert re_sourcing["context"]["excluded"] == {"Cell Works": "failed_in_request"}


def test_a_reply_whose_offer_re_sourcing_changed_is_refused_as_superseded(client):
    # E1: SPK-500, 1000 by 2026-11-12 → Sonic Audio 500 + EchoTech 300 + Wave Acoustics 200.
    request = submit(client, "REQ-E1", "SPK-500", 1000, "2026-11-12")
    legs = open_legs(request)
    at(client, NOW + timedelta(hours=1))
    reply(client, legs["Sonic Audio"], "ACCEPT")
    at(client, NOW + timedelta(hours=20))
    reply(client, legs["EchoTech"], "COUNTER 300 2026-11-20")  # late: countered, a fresh 24h

    at(client, NOW + timedelta(hours=25))  # Wave Acoustics never replied
    late_accept = reply(client, legs["EchoTech"], "ACCEPT")

    # Sonic 500 + EchoTech 300 < 1000 and no other supplier: the request failed, so EchoTech's offer no longer stands.
    assert late_accept.status_code == 409
    assert late_accept.json()["errors"] == [{"field": "offer", "issue": "superseded"}]
    after = request_of(client, request)
    assert (after["status"], after["constrained_quantity"]) == ("FAILED", "800")
    assert after["status_reason"] == "a Leg failed: timeout; no feasible allocation remains"
    [echo] = legs_of(after, "EchoTech")
    assert (echo["status"], echo["status_reason"]) == ("ABORTED", "split_failed")
    assert "ACCEPT" not in [m["message_type"] for m in echo["negotiation"]["messages"]]  # the reply is not stored
