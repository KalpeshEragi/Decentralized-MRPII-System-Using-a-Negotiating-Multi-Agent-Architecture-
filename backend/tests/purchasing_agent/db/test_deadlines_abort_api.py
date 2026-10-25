"""Response deadlines, clarifications and manual abort on the test database. Fixture scenarios N5 and N7 (A1: DSP-100,
500 by 2026-11-20 → Alpha Displays; re-sourced to Beta Optics, ADR-003) and B1 (BAT-200, 800 by 2026-11-12 → Volt
Power 400 + Cell Works 400).

The clock starts at 2026-11-02 10:00 Asia/Kolkata, the fixture's selection date, and is moved forward with `at`.
The working response deadline is 24h; the clarification limit is 2 per pending offer.
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


def submit_a1(client, ref="REQ-A1") -> dict:
    return submit(client, ref, "DSP-100", 500, "2026-11-20")


def submit_b1(client, ref="REQ-B1") -> dict:
    return submit(client, ref, "BAT-200", 800, "2026-11-12")


def legs_by_supplier(request: dict) -> dict[str, dict]:
    return {leg["supplier"]["name"]: leg for leg in request["legs"]}


def reply(client, leg: dict, text: str):
    return client.post(f"/purchasing/test-channel/conversations/{leg['id']}/messages",
                       json={"message_id": str(uuid.uuid4()), "text": text})


def request_of(client, request: dict) -> dict:
    return client.get(f"/purchasing/procurement-requests/{request['id']}").json()


def audit_of(client, request: dict, decision_type: str) -> list[dict]:
    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    return [a for a in audit if a["decision_type"] == decision_type]


def abort(client, request: dict, reason="the negotiation is stuck"):
    return client.post(f"/purchasing/procurement-requests/{request['id']}/abort",
                       json={"aborted_by": "tester", "reason": reason})


# -- N7: response deadline -------------------------------------------------------------------------------------------


def test_n7_a_silent_supplier_times_out_when_the_request_is_next_read(client):
    request = submit_a1(client)
    [leg] = request["legs"]
    deadline = datetime.fromisoformat(leg["negotiation"]["response_deadline"])
    assert deadline == NOW + timedelta(hours=24)

    at(client, NOW + timedelta(hours=24))  # at the deadline, not past it
    assert request_of(client, request)["status"] == "NEGOTIATING"

    at(client, NOW + timedelta(hours=24, minutes=1))
    after = request_of(client, request)
    # A read only records the timeout (ADR-003): no new Leg, no offer.
    assert (after["status"], after["status_reason"], after["constrained_quantity"], after["re_sourcing_needed"]) == (
        "NEGOTIATING", None, None, True)
    [leg] = after["legs"]
    assert (leg["status"], leg["status_reason"]) == ("FAILED", "timeout")
    session = leg["negotiation"]
    assert (session["status"], session["status_reason"]) == ("TIMED_OUT", "timeout")
    assert session["messages"][-1]["message_type"] == "CONFIRMATION"
    assert "in time" in session["messages"][-1]["text"]

    [timeout] = audit_of(client, request, "RESPONSE_DEADLINE")
    assert timeout["context"]["leg_id"] == leg["id"]
    assert datetime.fromisoformat(timeout["context"]["response_deadline"]) == deadline
    assert timeout["decision"] == {
        "outcome": "FAILED", "reason": "timeout", "request_status": "NEGOTIATING", "re_sourcing_needed": True}
    assert len(request_of(client, request)["legs"]) == 1  # reading again changes nothing

    # Re-sourcing picks Beta Optics 500; a second call changes nothing.
    first = client.post(f"/purchasing/procurement-requests/{request['id']}/re-source")
    assert first.status_code == 200
    re_sourced = first.json()
    assert (re_sourced["status"], re_sourced["split_type"], re_sourced["re_sourcing_needed"]) == (
        "NEGOTIATING", "SINGLE", False)
    beta = legs_by_supplier(re_sourced)["Beta Optics"]
    assert (beta["status"], beta["allocated_quantity"]) == ("PENDING", "500")
    [re_sourcing] = audit_of(client, request, "RE_SOURCING")
    assert re_sourcing["context"]["trigger"] == "timeout"
    second = client.post(f"/purchasing/procurement-requests/{request['id']}/re-source")
    assert second.status_code == 200 and second.json()["legs"] == request_of(client, request)["legs"]
    assert len(second.json()["legs"]) == 2 and len(audit_of(client, request, "RE_SOURCING")) == 1
    assert len(beta["negotiation"]["messages"]) == len(
        legs_by_supplier(second.json())["Beta Optics"]["negotiation"]["messages"])  # no second offer


def test_re_sourcing_an_unknown_request_is_not_found(client):
    assert client.post(f"/purchasing/procurement-requests/{uuid.uuid4()}/re-source").status_code == 404


def test_a_reply_after_the_deadline_is_refused_but_still_re_sources_its_request(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    at(client, NOW + timedelta(hours=25))
    late = reply(client, leg, "ACCEPT")
    assert late.status_code == 409

    after = request_of(client, request)
    alpha = legs_by_supplier(after)["Alpha Displays"]
    assert (alpha["status"], alpha["status_reason"]) == ("FAILED", "timeout")
    assert "ACCEPT" not in [m["message_type"] for m in alpha["negotiation"]["messages"]]  # the late reply is not stored
    # The reply was the next write for the request: re-sourcing ran first.
    assert legs_by_supplier(after)["Beta Optics"]["status"] == "PENDING"


def test_each_new_offer_moves_the_deadline(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    at(client, NOW + timedelta(hours=20))
    reply(client, leg, "COUNTER 500 2026-11-25")  # Purchasing counters: a new pending offer

    at(client, NOW + timedelta(hours=30))  # past the first deadline, before the new one
    after = request_of(client, request)
    assert after["status"] == "NEGOTIATING"
    [leg] = after["legs"]
    assert datetime.fromisoformat(leg["negotiation"]["response_deadline"]) == NOW + timedelta(hours=44)

    at(client, NOW + timedelta(hours=45))
    [leg] = request_of(client, request)["legs"]
    assert (leg["status"], leg["status_reason"]) == ("FAILED", "timeout")


def test_a_timed_out_leg_that_cannot_be_re_sourced_fails_the_split_and_aborts_the_agreed_leg(client):
    request = submit_b1(client)
    legs = legs_by_supplier(request)
    at(client, NOW + timedelta(hours=1))
    reply(client, legs["Volt Power"], "ACCEPT")

    at(client, NOW + timedelta(hours=25))  # Cell Works never replied
    recorded = request_of(client, request)
    assert (recorded["status"], recorded["re_sourcing_needed"]) == ("NEGOTIATING", True)
    assert legs_by_supplier(recorded)["Volt Power"]["status"] == "AGREED"  # untouched until re-sourcing runs

    # Volt alone can't cover 800 and Ion Supply arrives 11-14, after the required 11-12.
    after = client.post(f"/purchasing/procurement-requests/{request['id']}/re-source").json()
    assert (after["status"], after["constrained_quantity"]) == ("FAILED", "400")  # Volt's agreed 400 by the date
    assert after["status_reason"] == "a Leg failed: timeout; no feasible allocation remains"
    legs = legs_by_supplier(after)
    assert (legs["Cell Works"]["status"], legs["Cell Works"]["status_reason"]) == ("FAILED", "timeout")
    assert legs["Cell Works"]["negotiation"]["status"] == "TIMED_OUT"
    assert (legs["Volt Power"]["status"], legs["Volt Power"]["status_reason"]) == ("ABORTED", "split_failed")
    assert legs["Volt Power"]["negotiation"]["status"] == "CANCELLED"
    assert legs["Volt Power"]["negotiation"]["messages"][-1]["message_type"] == "CANCEL"


def test_reading_the_conversation_list_or_one_conversation_also_checks_the_deadline(client):
    [first] = submit_a1(client)["legs"]
    [second] = submit_a1(client, ref="REQ-A1-B")["legs"]
    at(client, NOW + timedelta(hours=25))

    conversation = client.get(f"/purchasing/test-channel/conversations/{first['id']}/messages").json()
    assert (conversation["leg_status"], conversation["negotiation_status"]) == ("FAILED", "TIMED_OUT")

    listed = {c["leg_id"]: c for c in client.get("/purchasing/test-channel/conversations").json()}
    assert (listed[second["id"]]["leg_status"], listed[second["id"]]["negotiation_status"]) == ("FAILED", "TIMED_OUT")


# -- N5: clarifications ----------------------------------------------------------------------------------------------


def test_n5_two_clarifications_then_an_unclear_reply_fails_the_leg_and_the_request_is_re_sourced(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    for _ in range(2):
        assert reply(client, leg, "hmm let me see").status_code == 201
    [current] = request_of(client, request)["legs"]
    assert (current["status"], current["negotiation"]["round_count"]) == ("PENDING", 1)  # no round used
    assert [m["message_type"] for m in current["negotiation"]["messages"]] == [
        "OFFER", "UNCLEAR", "CLARIFICATION_REQUEST", "UNCLEAR", "CLARIFICATION_REQUEST"]

    reply(client, leg, "hmm let me see")

    after = request_of(client, request)
    assert (after["status"], after["split_type"]) == ("NEGOTIATING", "SINGLE")
    legs = legs_by_supplier(after)
    leg = legs["Alpha Displays"]
    assert (leg["status"], leg["status_reason"]) == ("FAILED", "unclear_response")
    beta = legs["Beta Optics"]  # re-sourced without Alpha: Beta Optics 500 = 625,000
    assert (beta["status"], beta["allocated_quantity"]) == ("PENDING", "500")
    assert beta["negotiation"]["messages"][0]["terms"] == {"quantity": "500", "delivery_date": "2026-11-20"}
    session = leg["negotiation"]
    assert (session["status"], session["status_reason"], session["round_count"]) == (
        "REJECTED", "unclear_response", 1)
    closing = session["messages"][-1]
    assert closing["message_type"] == "CONFIRMATION" and closing["text"].startswith("We still could not read")
    validations = audit_of(client, request, "RESPONSE_VALIDATION")
    assert [(v["decision"]["outcome"], v["context"]["clarifications_since_offer"]) for v in validations] == [
        ("CLARIFICATION_REQUEST", 0), ("CLARIFICATION_REQUEST", 1), ("FAILED", 2)]
    assert validations[-1]["decision"]["reason"] == "unclear_response"


def test_clarifications_are_counted_per_pending_offer_and_never_change_the_round_limit(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    reply(client, leg, "hmm")
    reply(client, leg, "hmm")
    reply(client, leg, "COUNTER 500 2026-11-25")  # Purchasing counters: a new pending offer, round 2
    reply(client, leg, "hmm")
    reply(client, leg, "hmm")  # two more clarifications on the new offer

    [current] = request_of(client, request)["legs"]
    assert (current["status"], current["negotiation"]["round_count"], current["negotiation"]["max_rounds"]) == (
        "PENDING", 2, 3)

    reply(client, leg, "COUNTER 500 2026-11-25")  # round 3
    reply(client, leg, "COUNTER 500 2026-11-25")  # completes round 3: the round limit is still 3
    leg = legs_by_supplier(request_of(client, request))["Alpha Displays"]
    assert (leg["status"], leg["status_reason"]) == ("FAILED", "round_limit_exceeded")


def test_a_clarification_request_moves_the_deadline(client):
    request = submit_a1(client)
    [leg] = request["legs"]

    at(client, NOW + timedelta(hours=20))
    reply(client, leg, "hmm")

    [leg] = request_of(client, request)["legs"]
    assert datetime.fromisoformat(leg["negotiation"]["response_deadline"]) == NOW + timedelta(hours=44)


# -- manual abort ----------------------------------------------------------------------------------------------------


def test_aborting_a_negotiation_fails_the_request_and_aborts_every_open_leg(client):
    request = submit_b1(client)
    reply(client, legs_by_supplier(request)["Volt Power"], "ACCEPT")  # one Leg AGREED, one PENDING

    response = abort(client, request)
    assert response.status_code == 200
    after = response.json()
    assert (after["status"], after["status_reason"]) == ("FAILED", "aborted by tester: the negotiation is stuck")
    assert after["constrained_quantity"] is None
    for leg in after["legs"]:
        assert (leg["status"], leg["status_reason"]) == ("ABORTED", "manually_aborted")
        assert (leg["negotiation"]["status"], leg["negotiation"]["status_reason"]) == ("CANCELLED", "manually_aborted")
        assert leg["negotiation"]["messages"][-1]["message_type"] == "CANCEL"

    [record] = audit_of(client, request, "MANUAL_ABORT")
    assert (record["context"]["aborted_by"], record["context"]["reason"]) == ("tester", "the negotiation is stuck")
    assert sorted(record["decision"]["aborted_legs"]) == sorted(leg["id"] for leg in after["legs"])

    # The holds are released: the same shortage gets the same suppliers again.
    again = legs_by_supplier(submit_b1(client, ref="REQ-B1-AGAIN"))
    assert {name: leg["allocated_quantity"] for name, leg in again.items()} == {"Volt Power": "400", "Cell Works": "400"}

    # Further replies and a second abort are refused.
    assert reply(client, legs_by_supplier(request)["Cell Works"], "ACCEPT").status_code == 409
    second = abort(client, request)
    assert second.status_code == 409 and second.json()["code"] == "INVALID_STATE_TRANSITION"


def test_a_proposed_agreement_cannot_be_aborted_but_can_be_rejected(client):
    request = submit_a1(client)
    reply(client, request["legs"][0], "ACCEPT")
    assert request_of(client, request)["status"] == "AGREEMENT_PROPOSED"

    refused = abort(client, request)
    assert refused.status_code == 409 and refused.json()["code"] == "INVALID_STATE_TRANSITION"
    after = request_of(client, request)
    assert (after["status"], after["legs"][0]["status"]) == ("AGREEMENT_PROPOSED", "AGREED")  # nothing changed
    reject = client.post(f"/purchasing/procurement-requests/{request['id']}/reject", json={"decided_by": "approver"})
    assert reject.status_code == 200


def test_a_committed_request_cannot_be_aborted(client):
    request = submit_a1(client)
    reply(client, request["legs"][0], "ACCEPT")
    client.post(f"/purchasing/procurement-requests/{request['id']}/approve", json={"decided_by": "approver"})

    refused = abort(client, request)
    assert refused.status_code == 409 and refused.json()["code"] == "INVALID_STATE_TRANSITION"
    after = request_of(client, request)
    assert after["status"] == "COMMITTED" and after["legs"][0]["status"] == "COMMITTED"


def test_aborting_after_a_recorded_timeout_aborts_the_request_without_re_sourcing(client):
    request = submit_a1(client)
    at(client, NOW + timedelta(hours=25))

    response = abort(client, request)  # the timeout is recorded first; the request is still NEGOTIATING
    assert response.status_code == 200
    after = response.json()
    assert (after["status"], after["status_reason"]) == ("FAILED", "aborted by tester: the negotiation is stuck")
    [leg] = after["legs"]  # no replacement supplier: abort is final
    assert (leg["status"], leg["status_reason"]) == ("FAILED", "timeout")
    assert audit_of(client, request, "RE_SOURCING") == []


def test_aborting_an_unknown_request_or_without_a_reason_is_refused(client):
    assert abort(client, {"id": str(uuid.uuid4())}).status_code == 404
    request = submit_a1(client)
    missing = client.post(f"/purchasing/procurement-requests/{request['id']}/abort", json={"aborted_by": "tester"})
    assert missing.status_code == 422
    assert abort(client, request, reason="   ").status_code == 422
    assert request_of(client, request)["status"] == "NEGOTIATING"


# -- causation ids (code review 2026-10-18, ticket 11) ---------------------------------------------------------------


def test_a_reply_to_a_clarification_points_at_the_clarification(client):
    request = submit_a1(client)
    [leg] = request["legs"]
    reply(client, leg, "hmm")

    reply(client, leg, "ACCEPT")

    [leg] = request_of(client, request)["legs"]
    offer, unclear, clarification, accept, _ = leg["negotiation"]["messages"]
    assert unclear["causation_id"] == offer["message_id"]
    assert (clarification["message_type"], accept["message_type"]) == ("CLARIFICATION_REQUEST", "ACCEPT")
    assert accept["causation_id"] == clarification["message_id"]


def test_an_abort_cancel_points_at_the_message_it_cancels(client):
    request = submit_b1(client)
    reply(client, legs_by_supplier(request)["Volt Power"], "ACCEPT")  # Volt AGREED, Cell PENDING

    after = legs_by_supplier(abort(client, request).json())

    for name in ("Volt Power", "Cell Works"):
        *_, cancelled, cancel = after[name]["negotiation"]["messages"]
        assert cancel["message_type"] == "CANCEL" and cancel["causation_id"] == cancelled["message_id"], name
