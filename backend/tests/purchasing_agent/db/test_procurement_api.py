"""The Purchasing API on the test database: a Procurement Request becomes one Leg and one supplier offer.

Fixed clock: 2026-11-02 in Asia/Kolkata, the fixture's selection date.
"""

import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.supplier_service.seed import ITEM_IDS, SUPPLIER_IDS

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # the `client` fixture's clock


def submit(client, ref="REQ-A1", item="DSP-100", quantity=500, required_date="2026-11-20"):
    return client.post("/purchasing/procurement-requests", json={
        "request_ref": ref, "item_id": str(ITEM_IDS[item]), "shortage_quantity": quantity,
        "required_date": required_date, "priority": 1, "requested_by": "test"})


def test_a1_a_request_selects_alpha_and_sends_it_a_template_offer_without_price(client):

    response = submit(client)
    assert response.status_code == 201
    created = response.json()
    assert created == client.get(f"/purchasing/procurement-requests/{created['id']}").json()  # read back: the same

    assert (created["status"], created["split_type"], created["cost_ranking_available"]) == ("NEGOTIATING", "SINGLE", True)
    assert created["item"]["sku"] == "DSP-100" and created["required_date"] == "2026-11-20"

    [leg] = created["legs"]
    assert leg["supplier"] == {"id": str(SUPPLIER_IDS["Alpha Displays"]), "name": "Alpha Displays"}
    assert (leg["status"], leg["allocated_quantity"], leg["unit_price_at_selection"]) == ("PENDING", "500", "1200.00")
    assert leg["purchasing_contract_id"] is not None

    session = leg["negotiation"]
    assert (session["status"], session["round_count"], session["max_rounds"]) == ("OPEN", 1, 3)
    assert datetime.fromisoformat(session["response_deadline"]) == NOW + timedelta(hours=24)
    assert {(p["participant_type"], p["participant_ref"], p["role"]) for p in session["participants"]} == {
        ("AGENT", "PURCHASING", "INITIATOR"), ("SUPPLIER", str(SUPPLIER_IDS["Alpha Displays"]), "RESPONDENT")}

    [offer] = session["messages"]
    assert (offer["message_type"], offer["sender_type"], offer["round_number"]) == ("OFFER", "AGENT", 1)
    assert offer["terms"] == {"quantity": "500", "delivery_date": "2026-11-20"}  # never a price
    assert "500" in offer["text"] and "2026-11-20" in offer["text"] and "ACCEPT" in offer["text"]
    assert "1200" not in offer["text"] and "price" not in offer["text"].lower()

    # The selection audit lists every option with its reason, and why the winner won.
    selection = created["selection"]
    reasons = {o["supplier_name"]: o["reason"] for o in selection["options"]}
    assert reasons == {"Alpha Displays": "selected", "Beta Optics": "higher_cost", "Gamma Screens": "not_registered",
                       "Dormant Displays": "inactive_supplier"}
    alpha = next(o for o in selection["options"] if o["supplier_name"] == "Alpha Displays")
    assert (alpha["total_cost"], alpha["arrival"]) == ("600000.00", "2026-11-12")
    assert "Alpha Displays" in selection["reasoning_summary"]


def test_n11_the_same_request_ref_returns_the_existing_request_and_creates_no_new_leg(client):
    first = submit(client, ref="REQ-N11").json()

    again = submit(client, ref="REQ-N11", quantity=500.0)  # a retry with the same data (500.0 is 500 units)
    assert again.status_code == 200
    assert again.json() == first
    assert len(again.json()["legs"]) == 1


def test_reusing_a_request_ref_with_different_data_is_a_conflict(client):
    first = submit(client, ref="REQ-DUP").json()

    for changed in ({"quantity": 600}, {"required_date": "2026-11-19"}, {"item": "BAT-200"}):
        response = submit(client, ref="REQ-DUP", **changed)
        assert response.status_code == 409 and response.json()["code"] == "CONFLICT", changed
    other_priority = client.post("/purchasing/procurement-requests", json={
        "request_ref": "REQ-DUP", "item_id": str(ITEM_IDS["DSP-100"]), "shortage_quantity": 500,
        "required_date": "2026-11-20", "priority": 2, "requested_by": "test"})
    assert other_priority.status_code == 409

    # The original request is unchanged.
    assert client.get(f"/purchasing/procurement-requests/{first['id']}").json() == first


def test_unknown_items_and_invalid_input_are_refused_in_the_standard_error_format(client):

    unknown = client.post("/purchasing/procurement-requests", json={
        "request_ref": "REQ-X", "item_id": "00000000-0000-0000-0000-000000000000", "shortage_quantity": 10,
        "required_date": "2026-11-20", "priority": 1, "requested_by": "test"})
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "VALIDATION_ERROR"
    assert unknown.json()["errors"] == [{"field": "item_id", "issue": "unknown item"}]

    for bad in ({"shortage_quantity": 0}, {"shortage_quantity": -5}, {"shortage_quantity": 10.5},
                {"shortage_quantity": True}, {"required_date": None}, {"request_ref": "  "}):
        body = {"request_ref": "REQ-X", "item_id": str(ITEM_IDS["DSP-100"]), "shortage_quantity": 10,
                "required_date": "2026-11-20", "priority": 1, "requested_by": "test"} | bad
        response = client.post("/purchasing/procurement-requests", json=body)
        assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR", bad

    # Nothing was saved for the refused requests: the reference is still free.
    assert submit(client, ref="REQ-X").status_code == 201
    assert client.get("/purchasing/procurement-requests/00000000-0000-0000-0000-000000000000").status_code == 404


def test_a4_without_a_feasible_supplier_the_request_fails_with_a_constrained_quantity_and_opens_no_negotiation(client):

    failed = submit(client, ref="REQ-A4", quantity=300, required_date="2026-11-05").json()

    assert (failed["status"], failed["split_type"], failed["legs"]) == ("FAILED", None, [])
    assert (failed["constrained_quantity"], failed["selection"]["decision"]["constrained_quantity"]) == ("0", "0")
    assert failed["status_reason"]


def test_b1_a_necessary_split_opens_one_leg_session_and_offer_per_supplier(client):
    created = submit(client, ref="REQ-B1", item="BAT-200", quantity=800, required_date="2026-11-12").json()

    assert (created["status"], created["split_type"], created["cost_ranking_available"]) == (
        "NEGOTIATING", "NECESSARY_SPLIT", True)
    legs = {leg["supplier"]["name"]: leg for leg in created["legs"]}
    assert {name: (leg["status"], leg["allocated_quantity"], leg["unit_price_at_selection"])
            for name, leg in legs.items()} == {
        "Volt Power": ("PENDING", "400", "800.00"), "Cell Works": ("PENDING", "400", "900.00")}

    for name, leg in legs.items():
        session = leg["negotiation"]
        assert session["status"] == "OPEN"
        assert ("SUPPLIER", str(SUPPLIER_IDS[name])) in {
            (p["participant_type"], p["participant_ref"]) for p in session["participants"]}
        [offer] = session["messages"]
        assert offer["terms"] == {"quantity": "400", "delivery_date": "2026-11-12"}
    assert len({leg["negotiation"]["session_id"] for leg in legs.values()}) == 2  # one Engine session per Leg

    selection = created["selection"]
    assert selection["decision"]["outcome"] == "NECESSARY_SPLIT"
    assert selection["decision"]["total_cost"] == "680000.00"
    [combination] = selection["combinations"]
    assert (combination["supplier_names"], combination["reason"], combination["total_cost"]) == (
        ["Cell Works", "Volt Power"], "selected", "680000.00")
    assert {leg["supplier_name"]: leg["quantity"] for leg in combination["legs"]} == {
        "Cell Works": "400", "Volt Power": "400"}
    volt = next(m for m in combination["members"] if m["supplier_name"] == "Volt Power")
    assert {k: volt[k] for k in ("price_kind", "unit_price", "available_qty", "min_order_qty", "arrival")} == {
        "price_kind": "PRICED", "unit_price": "800.00", "available_qty": "400", "min_order_qty": "100",
        "arrival": "2026-11-09"}
    assert combination["reason_detail"] is None
    assert {o["supplier_name"]: o["reason"] for o in selection["options"]} == {
        "Volt Power": "selected", "Cell Works": "selected", "Ion Supply": "arrives_too_late"}
    assert "Necessary Split" in selection["reasoning_summary"]


def test_a3_an_unpriced_fallback_leg_has_no_contract_and_no_price(client):
    created = submit(client, ref="REQ-A3", quantity=300, required_date="2026-11-07").json()

    assert (created["status"], created["split_type"], created["cost_ranking_available"]) == ("NEGOTIATING", "SINGLE", False)
    [leg] = created["legs"]
    assert leg["supplier"]["name"] == "Gamma Screens"
    assert (leg["purchasing_contract_id"], leg["unit_price_at_selection"]) == (None, None)  # Not Registered, never zero
    gamma = next(o for o in created["selection"]["options"] if o["supplier_name"] == "Gamma Screens")
    assert (gamma["price_kind"], gamma["unit_price"], gamma["total_cost"]) == ("NOT_REGISTERED", None, None)
    assert created["selection"]["decision"]["cost_ranking_available"] is False
    assert "cost ranking unavailable" in created["selection"]["reasoning_summary"]


def test_the_same_request_ref_submitted_at_the_same_time_creates_one_request(client):
    start = threading.Barrier(2)
    responses = []

    def send():
        own_client = TestClient(client.app)
        start.wait()
        responses.append(submit(own_client, ref="REQ-DUP"))

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    assert sorted(r.status_code for r in responses) == [200, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    conversations = [c for c in client.get("/purchasing/test-channel/conversations").json()
                     if c["request_ref"] == "REQ-DUP"]
    assert len(conversations) == 1  # one request, one Leg, one offer
