"""No lock is held while the LLM runs (§9 "Locks and LLM calls", confirmed 2026-10-18, code review), on the test
database. A slow fake LLM holds one call open while other requests and replies go ahead: they are not blocked by it,
and a result that went stale while the LLM ran is never applied.

Fixed clock: 2026-11-02 in Asia/Kolkata, the fixture's selection date. SPK-500: Sonic Audio 500 (300/unit, arrives
11-06), EchoTech 300 (320/unit, 11-07), Wave Acoustics 300 (340/unit, 11-08).
"""

import json
import threading
import uuid

from fastapi.testclient import TestClient

from app.llm.client import LLMError
from app.purchasing_agent import api, messages
from app.supplier_service.seed import ITEM_IDS

WAIT = 30  # seconds; a call that is blocked by a lock would still be waiting


class SlowLLM:
    """The first call of the kind `slow` ("extract", "write" or "explain", told apart by the system prompt) waits
    until `release` is set; `entered` tells the test it is waiting. Wording calls answer `write(body)` when given;
    every other call fails like an unavailable model (fallback parser, template, no explanation)."""

    def __init__(self, slow: str, write=None):
        self.slow, self.write = slow, write
        self.entered, self.release = threading.Event(), threading.Event()
        self._lock = threading.Lock()
        self._held = False

    def complete(self, prompt: list[dict[str, str]]) -> str:
        system = prompt[0]["content"]
        kind = ("extract" if "extract its terms" in system else "write" if "reword" in system
                else "explain" if "explain a purchasing decision" in system else "other")
        with self._lock:
            hold = kind == self.slow and not self._held
            self._held = self._held or hold
        if hold:
            self.entered.set()
            assert self.release.wait(WAIT), "the slow LLM call was never released"
        if kind == "write" and self.write:
            return json.dumps({"text": self.write(prompt[-1]["content"])})
        raise LLMError("no script for this call")


def use(client, llm) -> None:
    client.app.dependency_overrides[api.get_llm_client] = lambda: llm


def in_background(client, call) -> tuple[threading.Thread, dict]:
    """Run `call(own_client)` in a thread with its own client; its response lands in the returned dict."""
    result = {}

    def run():
        result["response"] = call(TestClient(client.app))

    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


def post_request(client, ref: str, quantity: int, required_date: str = "2026-11-12"):
    return client.post("/purchasing/procurement-requests", json={
        "request_ref": ref, "item_id": str(ITEM_IDS["SPK-500"]), "shortage_quantity": quantity,
        "required_date": required_date, "priority": 1, "requested_by": "test"})


def reply(client, leg_id: str, text: str):
    return client.post(f"/purchasing/test-channel/conversations/{leg_id}/messages",
                       json={"message_id": str(uuid.uuid4()), "text": text})


def legs(request: dict) -> dict[str, str]:
    return {leg["supplier"]["name"]: leg["allocated_quantity"] for leg in request["legs"]}


def leg_of(request: dict, supplier: str) -> dict:
    return next(leg for leg in request["legs"] if leg["supplier"]["name"] == supplier)


def request_of(client, request_id: str) -> dict:
    return client.get(f"/purchasing/procurement-requests/{request_id}").json()


def conversation_of(client, request_ref: str) -> dict:
    return next(c for c in client.get("/purchasing/test-channel/conversations").json()
                if c["request_ref"] == request_ref)


def finish(thread: threading.Thread, llm: SlowLLM) -> None:
    llm.release.set()
    thread.join(WAIT)
    assert not thread.is_alive()


def test_a_request_waiting_for_the_llm_does_not_block_a_competing_request(client):
    llm = SlowLLM("write", write=lambda body: f"Good morning! {body}")
    use(client, llm)
    x_thread, x = in_background(client, lambda own: post_request(own, "REQ-X", 400))
    assert llm.entered.wait(WAIT)  # REQ-X has chosen Sonic Audio 400 of 500 and is waiting for the offer's wording

    y_thread, y = in_background(client, lambda own: post_request(own, "REQ-Y", 400))
    y_thread.join(WAIT)
    blocked = y_thread.is_alive()
    finish(x_thread, llm)
    finish(y_thread, llm)

    assert not blocked, "REQ-Y waited for REQ-X's LLM call"
    assert (x["response"].status_code, y["response"].status_code) == (201, 201)
    # REQ-X's hold was committed before its LLM call, so REQ-Y never sees Sonic's 500 as free.
    assert legs(x["response"].json()) == {"Sonic Audio": "400"}
    assert legs(y["response"].json()) == {"Sonic Audio": "100", "EchoTech": "300"}
    # The wording was still valid when the LLM answered, so it was applied.
    [offer] = leg_of(request_of(client, x["response"].json()["id"]), "Sonic Audio")["negotiation"]["messages"]
    assert offer["text"].startswith("Good morning! Hello Sonic Audio")


def test_an_offer_answered_while_the_llm_words_it_keeps_its_template(client):
    llm = SlowLLM("write", write=lambda body: f"Good morning! {body}")
    use(client, llm)
    x_thread, x = in_background(client, lambda own: post_request(own, "REQ-X", 400))
    assert llm.entered.wait(WAIT)
    conversation = conversation_of(client, "REQ-X")  # the template offer is already committed

    accepted = reply(client, conversation["leg_id"], "ACCEPT")  # not blocked by the LLM call
    finish(x_thread, llm)

    assert accepted.status_code == 201 and x["response"].status_code == 201
    after = request_of(client, x["response"].json()["id"])
    leg = leg_of(after, "Sonic Audio")
    assert (after["status"], leg["status"]) == ("AGREEMENT_PROPOSED", "AGREED")
    offer = leg["negotiation"]["messages"][0]
    assert offer["text"].startswith("Hello Sonic Audio, this is Purchasing.")  # the stale wording was discarded


def test_a_reply_waiting_for_the_llm_does_not_block_another_reply_and_is_not_applied_twice(client):
    request = post_request(client, "REQ-X", 400).json()  # Sonic Audio 400
    leg_id = leg_of(request, "Sonic Audio")["id"]
    llm = SlowLLM("extract")
    use(client, llm)
    first_thread, first = in_background(client, lambda own: reply(own, leg_id, "REJECT"))
    assert llm.entered.wait(WAIT)  # the first reply is being read by the LLM

    second_thread, second = in_background(client, lambda own: reply(own, leg_id, "ACCEPT"))
    second_thread.join(WAIT)
    blocked = second_thread.is_alive()
    finish(first_thread, llm)
    finish(second_thread, llm)

    assert not blocked, "the second reply waited for the first reply's LLM call"
    assert second["response"].status_code == 201
    assert first["response"].status_code == 409  # the Leg was AGREED meanwhile: the stale reading is not applied
    leg = leg_of(request_of(client, request["id"]), "Sonic Audio")
    assert leg["status"] == "AGREED"
    assert [m["message_type"] for m in leg["negotiation"]["messages"]] == ["OFFER", "ACCEPT", "CONFIRMATION"]


def test_a_reply_to_an_offer_revised_while_the_llm_read_it_is_refused(client):
    # E1: SPK-500, 1000 → Sonic Audio 500 + EchoTech 300 + Wave Acoustics 200.
    request = post_request(client, "REQ-E1", 1000).json()
    llm = SlowLLM("extract")
    use(client, llm)
    wave_thread, wave = in_background(client, lambda own: reply(own, leg_of(request, "Wave Acoustics")["id"],
                                                                "ACCEPT"))
    assert llm.entered.wait(WAIT)  # Wave's acceptance of 200 is being read

    # N2: EchoTech caps itself at 250, so Wave's offer is revised to 250.
    assert reply(client, leg_of(request, "EchoTech")["id"], "COUNTER 250 2026-11-07").status_code == 201
    finish(wave_thread, llm)

    assert wave["response"].status_code == 409  # it accepted 200, an offer that no longer stands
    wave_leg = leg_of(request_of(client, request["id"]), "Wave Acoustics")
    assert (wave_leg["status"], wave_leg["allocated_quantity"]) == ("PENDING", "250")
    last = wave_leg["negotiation"]["messages"][-1]
    assert (last["message_type"], last["terms"]) == ("COUNTER_OFFER", {"quantity": "250", "delivery_date": "2026-11-12"})
    assert "ACCEPT" not in [m["message_type"] for m in wave_leg["negotiation"]["messages"]]


def test_a_reallocation_waiting_for_the_llm_sees_the_holds_of_a_selection_made_meanwhile(client):
    # REQ-R: SPK-500, 600 → Sonic Audio 500 + EchoTech 100.
    r = post_request(client, "REQ-R", 600).json()
    assert legs(r) == {"Sonic Audio": "500", "EchoTech": "100"}
    llm = SlowLLM("extract")
    use(client, llm)
    sonic_thread, sonic = in_background(client, lambda own: reply(own, leg_of(r, "Sonic Audio")["id"],
                                                                  "COUNTER 300 2026-11-06"))
    assert llm.entered.wait(WAIT)  # Sonic's cap of 300 is being read

    # Meanwhile REQ-Y takes EchoTech's free 200 (Sonic is fully held; Wave arrives too late for 11-07).
    y = post_request(client, "REQ-Y", 200, required_date="2026-11-07")
    finish(sonic_thread, llm)

    assert y.status_code == 201 and legs(y.json()) == {"EchoTech": "200"}
    assert sonic["response"].status_code == 201
    # Without REQ-Y: Sonic 300 + EchoTech 300. With its hold, EchoTech has only 100 left: 300 + 100 < 600, so no
    # allocation fits and Sonic is countered back with its 500. EchoTech is never booked beyond its 300.
    after = request_of(client, r["id"])
    assert legs(after) == {"Sonic Audio": "500", "EchoTech": "100"}
    last = leg_of(after, "Sonic Audio")["negotiation"]["messages"][-1]
    assert (last["message_type"], last["terms"]) == ("COUNTER_OFFER", {"quantity": "500", "delivery_date": "2026-11-12"})
    assert messages.REPLY_FORMAT in last["text"]
