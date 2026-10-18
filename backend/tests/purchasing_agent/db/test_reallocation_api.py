"""Flexible Legs on the test database (§7.4): a supplier's counter quantity caps it, and the procurement is reallocated
among the already-selected suppliers only. Fixture scenarios N2 (E1), N3 (B1), N9 (A1), plus F1 for a collapse to a
single supplier and for a split kept without re-checking the saving threshold.

Fixed clock: 2026-11-02 in Asia/Kolkata, the fixture's selection date.
"""

import uuid

from app.supplier_service.seed import ITEM_IDS


def submit(client, ref: str, sku: str, quantity: int, required_date: str) -> dict:
    response = client.post("/purchasing/procurement-requests", json={
        "request_ref": ref, "item_id": str(ITEM_IDS[sku]), "shortage_quantity": quantity,
        "required_date": required_date, "priority": 1, "requested_by": "test"})
    assert response.status_code == 201
    return response.json()


def submit_e1(client) -> dict:
    """E1: SPK-500, 1000 by 2026-11-12 → Sonic Audio 500 + EchoTech 300 + Wave Acoustics 200 = 314,000."""
    return submit(client, "REQ-E1", "SPK-500", 1000, "2026-11-12")


def submit_f1(client) -> dict:
    """F1: CHP-600, 500 by 2026-11-20 → Cost-Saving Split ConnectRite 400 + PlugCo 100 = 45,000."""
    return submit(client, "REQ-F1", "CHP-600", 500, "2026-11-20")


def legs_by_supplier(request: dict) -> dict[str, dict]:
    return {leg["supplier"]["name"]: leg for leg in request["legs"]}


def reply(client, leg: dict, text: str):
    response = client.post(f"/purchasing/test-channel/conversations/{leg['id']}/messages",
                           json={"message_id": str(uuid.uuid4()), "text": text})
    assert response.status_code == 201
    return response


def request_of(client, request: dict) -> dict:
    return client.get(f"/purchasing/procurement-requests/{request['id']}").json()


def audits(client, request: dict, decision_type: str) -> list[dict]:
    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    return [a for a in audit if a["decision_type"] == decision_type]


def test_n2_a_counter_quantity_caps_the_supplier_and_the_rest_is_reallocated(client):
    request = submit_e1(client)
    legs = legs_by_supplier(request)

    reply(client, legs["EchoTech"], "COUNTER 250 2026-11-07")  # "we can only do 250"

    after = request_of(client, request)
    assert after["status"] == "NEGOTIATING"
    now = legs_by_supplier(after)
    assert {name: (leg["status"], leg["allocated_quantity"], leg["quantity_cap"]) for name, leg in now.items()} == {
        "Sonic Audio": ("PENDING", "500", None),
        "EchoTech": ("AGREED", "250", "250"),  # its own counter fits the new allocation: agreed on its terms
        "Wave Acoustics": ("PENDING", "250", None),
    }
    assert (now["EchoTech"]["agreed_quantity"], now["EchoTech"]["agreed_delivery_date"]) == ("250", "2026-11-07")

    # Wave's Leg gets a revised offer of 250, which counts as a new round for Wave.
    wave = now["Wave Acoustics"]["negotiation"]
    assert (wave["status"], wave["round_count"]) == ("OPEN", 2)
    revised = wave["messages"][-1]
    assert (revised["sender_type"], revised["message_type"], revised["round_number"]) == ("AGENT", "COUNTER_OFFER", 2)
    assert revised["terms"] == {"quantity": "250", "delivery_date": "2026-11-12"}
    assert now["Sonic Audio"]["negotiation"]["round_count"] == 1  # unchanged: not reopened

    [reallocation] = audits(client, request, "REALLOCATION")
    assert reallocation["context"]["quantity_cap"] == "250"
    assert reallocation["context"]["allocation_before"] == {
        "Sonic Audio": "500", "EchoTech": "300", "Wave Acoustics": "200"}
    assert reallocation["context"]["total_cost_before"] == "314000.00"
    decision = reallocation["decision"]
    assert (decision["outcome"], decision["total_cost"], decision["dropped_suppliers"]) == (
        "NECESSARY_SPLIT", "315000.00", [])
    assert {leg["supplier_name"]: leg["quantity"] for leg in decision["legs"]} == {
        "Sonic Audio": "500", "EchoTech": "250", "Wave Acoustics": "250"}
    [validation] = audits(client, request, "RESPONSE_VALIDATION")
    assert validation["decision"]["outcome"] == "AGREED"

    reply(client, now["Sonic Audio"], "ACCEPT")
    reply(client, now["Wave Acoustics"], "ACCEPT")
    proposed = request_of(client, request)
    assert proposed["status"] == "AGREEMENT_PROPOSED"
    assert {name: leg["agreed_quantity"] for name, leg in legs_by_supplier(proposed).items()} == {
        "Sonic Audio": "500", "EchoTech": "250", "Wave Acoustics": "250"}


def test_n2_an_agreed_leg_whose_quantity_changes_is_explicitly_reopened(client):
    request = submit_e1(client)
    legs = legs_by_supplier(request)
    reply(client, legs["Wave Acoustics"], "ACCEPT")  # Wave agreed to 200 first

    reply(client, legs["EchoTech"], "COUNTER 250 2026-11-07")

    wave = legs_by_supplier(request_of(client, request))["Wave Acoustics"]
    assert (wave["status"], wave["allocated_quantity"], wave["agreed_quantity"]) == ("PENDING", "250", None)
    session = wave["negotiation"]
    assert (session["status"], session["status_reason"], session["round_count"]) == ("OPEN", None, 2)  # AGREED → OPEN
    assert session["messages"][-1]["terms"] == {"quantity": "250", "delivery_date": "2026-11-12"}

    reply(client, wave, "ACCEPT")
    reply(client, legs["Sonic Audio"], "ACCEPT")
    assert request_of(client, request)["status"] == "AGREEMENT_PROPOSED"


def test_a_leg_that_must_be_revised_without_rounds_left_fails_the_procurement(client):
    request = submit_e1(client)
    legs = legs_by_supplier(request)
    for _ in range(2):  # a late date twice: Wave's third offer is pending, no rounds left
        reply(client, legs["Wave Acoustics"], "COUNTER 200 2026-11-20")

    reply(client, legs["EchoTech"], "COUNTER 250 2026-11-07")  # Wave would need a revised offer of 250

    failed = request_of(client, request)
    assert failed["status"] == "FAILED" and "round_limit_exceeded" in failed["status_reason"]
    # Sonic 500 + EchoTech capped at 250; Wave's offers were all late.
    assert failed["constrained_quantity"] == "750"
    assert {name: (leg["status"], leg["status_reason"]) for name, leg in legs_by_supplier(failed).items()} == {
        "Sonic Audio": ("ABORTED", "split_failed"),
        "EchoTech": ("ABORTED", "split_failed"),
        "Wave Acoustics": ("FAILED", "round_limit_exceeded"),
    }
    wave = legs_by_supplier(failed)["Wave Acoustics"]["negotiation"]
    assert (wave["status"], wave["status_reason"], wave["round_count"]) == ("REJECTED", "round_limit_exceeded", 3)
    [validation] = audits(client, request, "RESPONSE_VALIDATION")[-1:]
    assert (validation["decision"]["outcome"], validation["decision"]["reason"]) == ("ABORTED", "split_failed")


def test_n3_no_allocation_fits_so_the_capping_supplier_is_countered_back_until_the_round_limit(client):
    request = submit(client, "REQ-B1", "BAT-200", 800, "2026-11-12")
    legs = legs_by_supplier(request)
    reply(client, legs["Volt Power"], "ACCEPT")

    reply(client, legs["Cell Works"], "COUNTER 300 2026-11-12")  # "max 300": Volt 400 + Cell 300 = 700 < 800

    cell = legs_by_supplier(request_of(client, request))["Cell Works"]
    assert (cell["status"], cell["quantity_cap"], cell["allocated_quantity"]) == ("PENDING", "300", "400")
    counter_back = cell["negotiation"]["messages"][-1]
    assert (counter_back["message_type"], counter_back["terms"]) == (
        "COUNTER_OFFER", {"quantity": "400", "delivery_date": "2026-11-12"})
    [reallocation] = audits(client, request, "REALLOCATION")
    assert (reallocation["decision"]["outcome"], reallocation["decision"]["constrained_quantity"]) == ("FAILED", "700")
    assert reallocation["decision"]["trigger_leg_outcome"] == "COUNTER_OFFER"

    for _ in range(2):  # rounds 2 and 3
        reply(client, cell, "COUNTER 300 2026-11-12")

    failed = request_of(client, request)
    assert (failed["status"], failed["constrained_quantity"]) == ("FAILED", "700")
    assert {name: (leg["status"], leg["status_reason"]) for name, leg in legs_by_supplier(failed).items()} == {
        "Volt Power": ("ABORTED", "split_failed"), "Cell Works": ("FAILED", "round_limit_exceeded")}
    assert client.get("/purchasing/scheduled-receipts").json() == []


def test_accepting_the_counter_back_lifts_the_cap(client):
    request = submit(client, "REQ-B1", "BAT-200", 800, "2026-11-12")
    legs = legs_by_supplier(request)
    reply(client, legs["Volt Power"], "ACCEPT")
    reply(client, legs["Cell Works"], "COUNTER 300 2026-11-12")

    reply(client, legs["Cell Works"], "ACCEPT")  # the counter-back of 400

    proposed = request_of(client, request)
    assert proposed["status"] == "AGREEMENT_PROPOSED"
    cell = legs_by_supplier(proposed)["Cell Works"]
    assert (cell["status"], cell["agreed_quantity"], cell["quantity_cap"]) == ("AGREED", "400", "400")


def test_n9_a_fallback_parsed_counter_below_the_shortage_is_countered_back_with_the_full_quantity(client):
    request = submit(client, "REQ-A1", "DSP-100", 500, "2026-11-20")
    [leg] = request["legs"]

    reply(client, leg, "COUNTER 450 2026-11-12")

    [leg] = request_of(client, request)["legs"]
    assert (leg["status"], leg["quantity_cap"], leg["negotiation"]["round_count"]) == ("PENDING", "450", 2)
    *_, counter, counter_back = leg["negotiation"]["messages"]
    assert (counter["message_type"], counter["interpretation_source"]) == ("COUNTER_OFFER", "FALLBACK_PARSER")
    assert (counter_back["message_type"], counter_back["terms"]) == (
        "COUNTER_OFFER", {"quantity": "500", "delivery_date": "2026-11-20"})
    assert "Understood: 450 units by 2026-11-12" in counter_back["text"]


def test_a_split_collapses_to_a_single_supplier_and_the_unneeded_leg_is_dropped(client):
    request = submit_f1(client)
    legs = legs_by_supplier(request)

    reply(client, legs["ConnectRite"], "COUNTER 50 2026-11-07")  # below its MOQ of 100: unusable

    after = request_of(client, request)
    assert (after["status"], after["split_type"]) == ("NEGOTIATING", "SINGLE")
    now = legs_by_supplier(after)
    connect = now["ConnectRite"]
    assert (connect["status"], connect["status_reason"]) == ("ABORTED", "no_longer_needed")
    assert (connect["negotiation"]["status"], connect["negotiation"]["status_reason"]) == (
        "CANCELLED", "no_longer_needed")
    assert connect["negotiation"]["messages"][-1]["message_type"] == "CANCEL"
    plug = now["PlugCo"]
    assert (plug["status"], plug["allocated_quantity"], plug["negotiation"]["round_count"]) == ("PENDING", "500", 2)
    [reallocation] = audits(client, request, "REALLOCATION")
    assert (reallocation["decision"]["outcome"], reallocation["decision"]["dropped_suppliers"]) == (
        "SINGLE", ["ConnectRite"])

    # The dropped Leg is no longer part of the agreement: PlugCo alone proposes and commits it.
    reply(client, plug, "ACCEPT")
    assert request_of(client, request)["status"] == "AGREEMENT_PROPOSED"
    approve = client.post(f"/purchasing/procurement-requests/{request['id']}/approve", json={"decided_by": "approver"})
    assert approve.status_code == 200
    committed = legs_by_supplier(request_of(client, request))
    assert (committed["PlugCo"]["status"], committed["ConnectRite"]["status"]) == ("COMMITTED", "ABORTED")
    assert [(r["supplier"]["name"], r["quantity"]) for r in client.get("/purchasing/scheduled-receipts").json()] == [
        ("PlugCo", "500")]


def test_a_reallocated_split_is_kept_without_re_checking_the_saving_threshold_and_its_saving_is_audited(client):
    request = submit_f1(client)
    legs = legs_by_supplier(request)

    reply(client, legs["ConnectRite"], "COUNTER 300 2026-11-07")

    after = request_of(client, request)
    assert after["split_type"] == "COST_SAVING_SPLIT"
    now = legs_by_supplier(after)
    assert {name: (leg["status"], leg["allocated_quantity"]) for name, leg in now.items()} == {
        "ConnectRite": ("AGREED", "300"), "PlugCo": ("PENDING", "200")}
    [reallocation] = audits(client, request, "REALLOCATION")
    decision = reallocation["decision"]
    # 46,250 against PlugCo 500 = 50,000 from the original selection: 7.5%, below the 10% threshold, still kept.
    assert (decision["total_cost"], decision["saving_percent"]) == ("46250.00", "7.50")
    assert decision["reference_single"] == {"supplier_name": "PlugCo", "total_cost": "50000.00"}
