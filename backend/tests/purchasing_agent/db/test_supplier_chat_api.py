"""The supplier chat on the test database: a tester replies as the supplier of one Leg, in the strict reply format
read by the fallback parser (no LLM yet). Fixture scenarios N1, N4, N6 (re-sourced, ADR-003), N10 and the round limit.

Fixed clock: 2026-11-02 in Asia/Kolkata, the fixture's selection date.
"""

import uuid

from app.supplier_service.seed import ITEM_IDS, SUPPLIER_IDS


def submit_a1(client, ref="REQ-A1") -> dict:
    """A1: DSP-100, 500 by 2026-11-20 → a single Leg with Alpha Displays."""
    response = client.post("/purchasing/procurement-requests", json={
        "request_ref": ref, "item_id": str(ITEM_IDS["DSP-100"]), "shortage_quantity": 500,
        "required_date": "2026-11-20", "priority": 1, "requested_by": "test"})
    assert response.status_code == 201
    return response.json()


def reply(client, leg_id: str, text: str, message_id: str | None = None):
    return client.post(f"/purchasing/test-channel/conversations/{leg_id}/messages",
                       json={"message_id": message_id or str(uuid.uuid4()), "text": text})


def request_of(client, request: dict) -> dict:
    return client.get(f"/purchasing/procurement-requests/{request['id']}").json()


def test_the_conversation_list_shows_each_leg_with_its_terms_and_rounds_but_never_a_price(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    response = client.get("/purchasing/test-channel/conversations")
    assert response.status_code == 200
    [conversation] = response.json()
    assert conversation["leg_id"] == leg["id"] and conversation["request_ref"] == "REQ-A1"
    assert conversation["supplier"] == {"id": str(SUPPLIER_IDS["Alpha Displays"]), "name": "Alpha Displays"}
    assert conversation["item"] == {"sku": "DSP-100", "name": "Display Panel"}
    assert (conversation["quantity"], conversation["required_date"]) == ("500", "2026-11-20")
    assert (conversation["round_count"], conversation["max_rounds"]) == (1, 3)
    assert (conversation["leg_status"], conversation["negotiation_status"]) == ("PENDING", "OPEN")
    assert "1200" not in str(conversation) and "price" not in str(conversation).lower()

    messages = client.get(f"/purchasing/test-channel/conversations/{leg['id']}/messages")
    assert messages.status_code == 200
    [offer] = messages.json()["messages"]
    assert (offer["sender_type"], offer["message_type"]) == ("AGENT", "OFFER")
    assert "1200" not in str(messages.json()) and "price" not in str(messages.json()).lower()


def test_the_test_channel_page_is_served(client):
    page = client.get("/purchasing/test-channel")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]


def test_n1_accepting_the_offer_agrees_the_leg_and_proposes_the_agreement(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    response = reply(client, leg["id"], "ACCEPT")
    assert response.status_code == 201 and response.json()["status"] == "received"

    after = request_of(client, request)
    assert after["status"] == "AGREEMENT_PROPOSED"
    [leg] = after["legs"]
    assert (leg["status"], leg["agreed_quantity"], leg["agreed_delivery_date"]) == ("AGREED", "500", "2026-11-20")
    session = leg["negotiation"]
    assert (session["status"], session["round_count"]) == ("AGREED", 1)  # the Engine status stays separate

    _, accept, confirmation = session["messages"]
    assert (accept["sender_type"], accept["message_type"], accept["interpretation_source"]) == (
        "SUPPLIER", "ACCEPT", "FALLBACK_PARSER")
    assert accept["terms"] is None and accept["round_number"] == 1
    assert (confirmation["sender_type"], confirmation["message_type"]) == ("AGENT", "CONFIRMATION")
    assert "Understood" in confirmation["text"] and "500" in confirmation["text"]  # the echo

    # The validation is audited.
    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    [validation] = [a for a in audit if a["decision_type"] == "RESPONSE_VALIDATION"]
    assert validation["context"]["interpretation"] == {
        "action": "ACCEPT", "quantity": None, "delivery_date": None, "source": "FALLBACK_PARSER"}
    assert validation["decision"]["outcome"] == "AGREED"
    assert validation["decision"]["terms"] == {"quantity": "500", "delivery_date": "2026-11-20"}


def test_n4_a_late_delivery_date_is_countered_with_the_required_date(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    assert reply(client, leg["id"], "COUNTER 500 2026-11-25").status_code == 201

    after = request_of(client, request)
    assert after["status"] == "NEGOTIATING" and after["required_date"] == "2026-11-20"  # the deadline never changes
    [leg] = after["legs"]
    assert leg["status"] == "PENDING"
    session = leg["negotiation"]
    assert (session["status"], session["round_count"]) == ("OPEN", 2)  # the counter-offer starts round 2

    _, counter, our_counter = session["messages"]
    assert (counter["message_type"], counter["terms"]) == (
        "COUNTER_OFFER", {"quantity": "500", "delivery_date": "2026-11-25"})
    assert (our_counter["sender_type"], our_counter["message_type"], our_counter["round_number"]) == (
        "AGENT", "COUNTER_OFFER", 2)
    assert our_counter["terms"] == {"quantity": "500", "delivery_date": "2026-11-20"}
    assert "Understood: 500 units by 2026-11-25" in our_counter["text"]
    assert our_counter["causation_id"] == counter["message_id"]
    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    [validation] = [a for a in audit if a["decision_type"] == "RESPONSE_VALIDATION"]
    assert validation["context"]["interpretation"]["delivery_date"] == "2026-11-25"
    assert validation["decision"] == {"outcome": "COUNTER_OFFER", "reason": None,
                                      "terms": {"quantity": "500", "delivery_date": "2026-11-20"}}

    # The supplier then accepts the counter-offer: agreed on the required date.
    reply(client, leg["id"], "accept")
    [leg] = request_of(client, request)["legs"]
    assert (leg["status"], leg["agreed_quantity"], leg["agreed_delivery_date"]) == ("AGREED", "500", "2026-11-20")


def test_a_counter_with_the_full_quantity_and_an_earlier_date_is_agreed_on_those_terms(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    reply(client, leg["id"], "COUNTER 500 2026-11-15")

    after = request_of(client, request)
    assert after["status"] == "AGREEMENT_PROPOSED"
    [leg] = after["legs"]
    assert (leg["status"], leg["agreed_quantity"], leg["agreed_delivery_date"]) == ("AGREED", "500", "2026-11-15")
    assert leg["negotiation"]["round_count"] == 1


def test_a_single_supplier_counter_below_the_shortage_with_no_other_supplier_is_countered_back(client):
    # A3: DSP-100, 300 by 2026-11-07 → Gamma Screens alone; Alpha and Beta arrive too late to re-source.
    request = client.post("/purchasing/procurement-requests", json={
        "request_ref": "REQ-A3", "item_id": str(ITEM_IDS["DSP-100"]), "shortage_quantity": 300,
        "required_date": "2026-11-07", "priority": 1, "requested_by": "test"}).json()
    [leg] = request["legs"]

    reply(client, leg["id"], "COUNTER 250 2026-11-06")

    [leg] = request_of(client, request)["legs"]
    assert leg["status"] == "PENDING"
    our_counter = leg["negotiation"]["messages"][-1]
    assert (our_counter["message_type"], our_counter["terms"]) == (
        "COUNTER_OFFER", {"quantity": "300", "delivery_date": "2026-11-07"})
    assert "Understood: 250 units by 2026-11-06" in our_counter["text"]


def legs_by_supplier(request: dict) -> dict[str, dict]:
    return {leg["supplier"]["name"]: leg for leg in request["legs"]}


def test_n6_a_reject_fails_the_leg_and_the_request_is_re_sourced(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    reply(client, leg["id"], "REJECT")

    after = request_of(client, request)
    assert (after["status"], after["split_type"], after["re_sourcing_needed"]) == ("NEGOTIATING", "SINGLE", False)
    legs = legs_by_supplier(after)
    alpha, beta = legs["Alpha Displays"], legs["Beta Optics"]
    assert (alpha["status"], alpha["status_reason"]) == ("FAILED", "supplier_rejected")
    session = alpha["negotiation"]
    assert (session["status"], session["status_reason"]) == ("REJECTED", "supplier_rejected")
    assert session["messages"][-1]["message_type"] == "CONFIRMATION"
    # Beta Optics 500 = 625,000: a new Leg priced at its current contract, with a fresh offer.
    assert (beta["status"], beta["allocated_quantity"], beta["unit_price_at_selection"]) == ("PENDING", "500", "1250.00")
    [offer] = beta["negotiation"]["messages"]
    assert (offer["message_type"], offer["terms"]) == ("OFFER", {"quantity": "500", "delivery_date": "2026-11-20"})
    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    [validation] = [a for a in audit if a["decision_type"] == "RESPONSE_VALIDATION"]
    assert (validation["decision"]["outcome"], validation["decision"]["reason"]) == ("FAILED", "supplier_rejected")
    [re_sourcing] = [a for a in audit if a["decision_type"] == "RE_SOURCING"]
    assert (re_sourcing["context"]["trigger"], re_sourcing["context"]["excluded"]) == (
        "supplier_rejected", {"Alpha Displays": "failed_in_request"})
    assert (re_sourcing["decision"]["outcome"], re_sourcing["decision"]["added_suppliers"]) == (
        "SINGLE", ["Beta Optics"])

    # Alpha's negotiation is over: further replies are refused.
    late = reply(client, alpha["id"], "ACCEPT")
    assert late.status_code == 409 and late.json()["code"] == "INVALID_STATE_TRANSITION"

    reply(client, beta["id"], "ACCEPT")
    assert request_of(client, request)["status"] == "AGREEMENT_PROPOSED"


def test_the_round_limit_fails_the_leg_after_three_rounds_without_agreement(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    for round_number in (1, 2):
        reply(client, leg["id"], "COUNTER 500 2026-11-25")
        [current] = request_of(client, request)["legs"]
        assert (current["status"], current["negotiation"]["round_count"]) == ("PENDING", round_number + 1)

    reply(client, leg["id"], "COUNTER 500 2026-11-25")  # the reply that completes round 3

    after = request_of(client, request)
    assert after["status"] == "NEGOTIATING"  # re-sourced: Beta Optics gets a new Leg
    leg = legs_by_supplier(after)["Alpha Displays"]
    assert (leg["status"], leg["status_reason"]) == ("FAILED", "round_limit_exceeded")
    assert legs_by_supplier(after)["Beta Optics"]["status"] == "PENDING"
    session = leg["negotiation"]
    assert (session["status"], session["status_reason"], session["round_count"]) == (
        "REJECTED", "round_limit_exceeded", 3)
    offers = [m for m in session["messages"] if m["sender_type"] == "AGENT" and m["message_type"] != "CONFIRMATION"]
    assert len(offers) == 3


def test_n10_a_duplicate_message_id_is_ignored(client):
    request = submit_a1(client)
    [leg] = request["legs"]
    message_id = str(uuid.uuid4())

    assert reply(client, leg["id"], "COUNTER 500 2026-11-25", message_id).status_code == 201
    duplicate = reply(client, leg["id"], "COUNTER 500 2026-11-25", message_id)
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"

    [leg] = request_of(client, request)["legs"]
    assert leg["negotiation"]["round_count"] == 2  # no extra round
    assert len(leg["negotiation"]["messages"]) == 3  # offer, the reply once, our counter

    # A duplicate of an ACCEPT that closed the negotiation is still just ignored.
    accept_id = str(uuid.uuid4())
    reply(client, leg["id"], "ACCEPT", accept_id)
    assert reply(client, leg["id"], "ACCEPT", accept_id).json()["status"] == "duplicate"
    assert request_of(client, request)["status"] == "AGREEMENT_PROPOSED"


def test_reusing_a_message_id_on_another_leg_is_a_conflict(client):
    [first] = submit_a1(client)["legs"]
    [second] = submit_a1(client, ref="REQ-A1-B")["legs"]
    message_id = str(uuid.uuid4())
    reply(client, first["id"], "COUNTER 500 2026-11-25", message_id)

    reused = reply(client, second["id"], "ACCEPT", message_id)
    assert reused.status_code == 409 and reused.json()["code"] == "CONFLICT"
    conversation = client.get(f"/purchasing/test-channel/conversations/{second['id']}/messages").json()
    assert [m["message_type"] for m in conversation["messages"]] == ["OFFER"]  # nothing stored on the second Leg


def test_an_unreadable_reply_asks_for_the_reply_format_without_using_a_round(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    reply(client, leg["id"], "hmm let me see")

    [leg] = request_of(client, request)["legs"]
    session = leg["negotiation"]
    assert (leg["status"], session["round_count"]) == ("PENDING", 1)
    _, unclear, clarification = session["messages"]
    assert (unclear["message_type"], unclear["interpretation_source"]) == ("UNCLEAR", "FALLBACK_PARSER")
    assert clarification["message_type"] == "CLARIFICATION_REQUEST" and "ACCEPT" in clarification["text"]


def test_replies_to_unknown_legs_and_empty_replies_are_refused(client):
    assert reply(client, str(uuid.uuid4()), "ACCEPT").status_code == 404
    [leg] = submit_a1(client)["legs"]
    empty = reply(client, leg["id"], "   ")
    assert empty.status_code == 422 and empty.json()["code"] == "VALIDATION_ERROR"


# A delivery date before today (2026-11-02) is never agreed (confirmed 2026-10-18, code review).


def test_a_counter_with_a_past_date_is_countered_with_the_required_date(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    assert reply(client, leg["id"], "COUNTER 500 2026-11-01").status_code == 201

    [leg] = request_of(client, request)["legs"]
    assert leg["status"] == "PENDING" and leg["agreed_delivery_date"] is None
    our_counter = leg["negotiation"]["messages"][-1]
    assert (our_counter["message_type"], our_counter["terms"]) == (
        "COUNTER_OFFER", {"quantity": "500", "delivery_date": "2026-11-20"})


def test_a_past_date_with_no_rounds_left_fails_the_leg(client):
    request = submit_a1(client)
    [leg] = request["legs"]
    for _ in range(3):  # rounds 1-3 each end with a past date
        reply(client, leg["id"], "COUNTER 500 2026-10-30")

    after = request_of(client, request)
    leg = legs_by_supplier(after)["Alpha Displays"]
    assert (after["status"], leg["status"], leg["status_reason"]) == ("NEGOTIATING", "FAILED", "round_limit_exceeded")


def test_a_quantity_counter_with_a_past_date_is_not_agreed_on_reallocation(client):
    # E1: SPK-500, 1000 by 2026-11-12 → Sonic Audio 500 + EchoTech 300 + Wave Acoustics 200.
    request = client.post("/purchasing/procurement-requests", json={
        "request_ref": "REQ-E1", "item_id": str(ITEM_IDS["SPK-500"]), "shortage_quantity": 1000,
        "required_date": "2026-11-12", "priority": 1, "requested_by": "test"}).json()
    echo = next(leg for leg in request["legs"] if leg["supplier"]["name"] == "EchoTech")

    reply(client, echo["id"], "COUNTER 250 2026-11-01")  # 250 is allocated, but the date is past

    echo = next(leg for leg in request_of(client, request)["legs"] if leg["supplier"]["name"] == "EchoTech")
    assert (echo["status"], echo["allocated_quantity"]) == ("PENDING", "250")
    assert echo["negotiation"]["messages"][-1]["terms"] == {"quantity": "250", "delivery_date": "2026-11-12"}
