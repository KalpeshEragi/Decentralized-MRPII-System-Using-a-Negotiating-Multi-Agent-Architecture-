"""The LLM through the Purchasing API on the test database, with fake LLMs (no Ollama): natural-language supplier
replies (N1, N4), invented terms falling back to the parser, LLM-worded messages and their guardrails, and the
selection explanation kept apart from the deterministic rationale.

Fixed clock: 2026-11-02 in Asia/Kolkata, the fixture's selection date.
"""

import json
import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from app.llm.client import LLMError
from app.purchasing_agent import api, messages
from app.supplier_service.seed import ITEM_IDS


class ScriptedLLM:
    """Answers each kind of call (reading a reply, wording a message, explaining the selection) from its own script,
    told apart by the system prompt. A kind without a script fails like an unavailable model."""

    def __init__(self, extract: list[dict] | None = None, write: Callable[[str], str] | None = None,
                 explain: str | None = None):
        self.extract, self.write, self.explain = list(extract or []), write, explain

    def complete(self, prompt: list[dict[str, str]]) -> str:
        system, user = prompt[0]["content"], prompt[-1]["content"]
        if "extract its terms" in system and self.extract:
            return json.dumps(self.extract.pop(0))
        if "reword" in system and self.write:
            return json.dumps({"text": self.write(user)})
        if "explain a purchasing decision" in system and self.explain:
            return json.dumps({"text": self.explain})
        raise LLMError("no script for this call")


def submit_a1(client) -> dict:
    """A1: DSP-100, 500 by 2026-11-20 → a single Leg with Alpha Displays (Gamma Screens: Not Registered)."""
    response = client.post("/purchasing/procurement-requests", json={
        "request_ref": "REQ-A1", "item_id": str(ITEM_IDS["DSP-100"]), "shortage_quantity": 500,
        "required_date": "2026-11-20", "priority": 1, "requested_by": "test"})
    assert response.status_code == 201
    return response.json()


def reply(client, leg_id: str, text: str):
    return client.post(f"/purchasing/test-channel/conversations/{leg_id}/messages",
                       json={"message_id": str(uuid.uuid4()), "text": text})


def request_of(client, request: dict) -> dict:
    return client.get(f"/purchasing/procurement-requests/{request['id']}").json()


def use(client, llm: ScriptedLLM) -> None:
    client.app.dependency_overrides[api.get_llm_client] = lambda: llm


def audit_of(client, request: dict, decision_type: str) -> list[dict]:
    audit = client.get(f"/purchasing/procurement-requests/{request['id']}/audit").json()
    return [a for a in audit if a["decision_type"] == decision_type]


# -- reading natural-language replies -------------------------------------------------------------------------------


def test_n1_a_natural_acceptance_agrees_the_leg(client):
    use(client, ScriptedLLM(extract=[{"action": "ACCEPT", "quantity": 500, "delivery_date": "2026-11-12"}]))
    request = submit_a1(client)
    [leg] = request["legs"]

    assert reply(client, leg["id"], "ok, 500 by 12 Nov works").status_code == 201

    after = request_of(client, request)
    assert after["status"] == "AGREEMENT_PROPOSED"
    [leg] = after["legs"]
    # Stating an earlier date than offered is a counter on those terms: the full quantity on time is agreed.
    assert (leg["status"], leg["agreed_quantity"], leg["agreed_delivery_date"]) == ("AGREED", "500", "2026-11-12")
    _, supplier, confirmation = leg["negotiation"]["messages"]
    assert (supplier["message_type"], supplier["interpretation_source"]) == ("COUNTER_OFFER", "LLM")
    assert supplier["terms"] == {"quantity": "500", "delivery_date": "2026-11-12"}
    assert "Understood: 500 units by 2026-11-12" in confirmation["text"]
    [validation] = audit_of(client, request, "RESPONSE_VALIDATION")
    assert validation["context"]["interpretation"]["source"] == "LLM"
    assert validation["decision"]["outcome"] == "AGREED"


def test_n4_a_natural_late_counter_is_countered_with_the_required_date(client):
    use(client, ScriptedLLM(extract=[{"action": "COUNTER", "quantity": 500, "delivery_date": "2026-11-25"}]))
    request = submit_a1(client)
    [leg] = request["legs"]

    reply(client, leg["id"], "500 but delivery 25 Nov")

    after = request_of(client, request)
    assert after["status"] == "NEGOTIATING" and after["required_date"] == "2026-11-20"
    [leg] = after["legs"]
    _, supplier, our_counter = leg["negotiation"]["messages"]
    assert supplier["interpretation_source"] == "LLM"
    assert our_counter["message_type"] == "COUNTER_OFFER"
    assert our_counter["terms"] == {"quantity": "500", "delivery_date": "2026-11-20"}
    assert our_counter["text"].startswith("Understood: 500 units by 2026-11-25.")


def test_a_counter_with_only_a_quantity_is_never_given_an_invented_date(client):
    use(client, ScriptedLLM(extract=[{"action": "COUNTER", "quantity": 450, "delivery_date": None}]))
    request = submit_a1(client)
    [leg] = request["legs"]

    reply(client, leg["id"], "we can only do 450")

    legs = {leg["supplier"]["name"]: leg for leg in request_of(client, request)["legs"]}
    alpha = legs["Alpha Displays"]
    _, supplier, cancel = alpha["negotiation"]["messages"]
    assert supplier["terms"] == {"quantity": "450", "delivery_date": None}
    # 450 caps Alpha and can't cover 500 alone: re-sourced to Beta Optics 500 (as N9), Alpha dropped, cap remembered.
    assert (alpha["status"], alpha["status_reason"], alpha["quantity_cap"]) == ("ABORTED", "no_longer_needed", "450")
    assert cancel["message_type"] == "CANCEL"
    assert cancel["text"].startswith("Understood: 450 units, with no delivery date given.")
    assert legs["Beta Optics"]["allocated_quantity"] == "500"


def test_n2_a_natural_quantity_counter_is_reallocated_and_must_be_explicitly_accepted(client):
    use(client, ScriptedLLM(extract=[
        {"action": "COUNTER", "quantity": 250, "delivery_date": None},  # EchoTech: "we can only do 250"
        {"action": "ACCEPT", "quantity": None, "delivery_date": None},  # Sonic Audio
        {"action": "ACCEPT", "quantity": None, "delivery_date": None},  # Wave Acoustics
        {"action": "ACCEPT", "quantity": 250, "delivery_date": "2026-11-12"},  # EchoTech accepts the final terms
    ]))
    # E1: SPK-500, 1000 by 2026-11-12 → Sonic Audio 500 + EchoTech 300 + Wave Acoustics 200.
    request = client.post("/purchasing/procurement-requests", json={
        "request_ref": "REQ-E1", "item_id": str(ITEM_IDS["SPK-500"]), "shortage_quantity": 1000,
        "required_date": "2026-11-12", "priority": 1, "requested_by": "test"}).json()
    legs = {leg["supplier"]["name"]: leg for leg in request["legs"]}

    reply(client, legs["EchoTech"]["id"], "we can only do 250")

    now = {leg["supplier"]["name"]: leg for leg in request_of(client, request)["legs"]}
    assert {name: (leg["status"], leg["allocated_quantity"]) for name, leg in now.items()} == {
        "Sonic Audio": ("PENDING", "500"), "EchoTech": ("PENDING", "250"), "Wave Acoustics": ("PENDING", "250")}
    echo = now["EchoTech"]["negotiation"]
    supplier, revised = echo["messages"][-2:]
    assert (supplier["interpretation_source"], supplier["terms"]) == ("LLM", {"quantity": "250", "delivery_date": None})
    # No date was stated, so none is assumed: EchoTech gets a revised offer of 250 by the required date (round 2).
    assert (revised["message_type"], revised["terms"], echo["round_count"]) == (
        "COUNTER_OFFER", {"quantity": "250", "delivery_date": "2026-11-12"}, 2)
    wave = now["Wave Acoustics"]["negotiation"]
    assert (wave["messages"][-1]["terms"]["quantity"], wave["round_count"]) == ("250", 2)  # Wave's revised offer

    reply(client, now["Sonic Audio"]["id"], "yes, confirmed")
    reply(client, now["Wave Acoustics"]["id"], "fine, we accept")
    assert request_of(client, request)["status"] == "NEGOTIATING"  # EchoTech hasn't accepted the final terms yet

    reply(client, now["EchoTech"]["id"], "ok, 250 by 12 Nov is fine")
    proposed = request_of(client, request)
    assert proposed["status"] == "AGREEMENT_PROPOSED"
    assert {leg["supplier"]["name"]: (leg["agreed_quantity"], leg["agreed_delivery_date"])
            for leg in proposed["legs"]} == {
        "Sonic Audio": ("500", "2026-11-12"), "EchoTech": ("250", "2026-11-12"),
        "Wave Acoustics": ("250", "2026-11-12")}


def test_terms_the_llm_invented_fall_back_to_the_parser(client):
    use(client, ScriptedLLM(extract=[{"action": "COUNTER", "quantity": 500, "delivery_date": "2026-11-18"}]))
    request = submit_a1(client)
    [leg] = request["legs"]

    reply(client, leg["id"], "we will see what we can do soon")  # no quantity or date written

    [leg] = request_of(client, request)["legs"]
    _, supplier, clarification = leg["negotiation"]["messages"]
    assert (supplier["message_type"], supplier["interpretation_source"]) == ("UNCLEAR", "FALLBACK_PARSER")
    assert clarification["message_type"] == "CLARIFICATION_REQUEST" and leg["status"] == "PENDING"


# -- message wording ------------------------------------------------------------------------------------------------


def test_the_offer_is_worded_by_the_llm_with_the_same_terms(client):
    use(client, ScriptedLLM(write=lambda body: f"Good morning! {body}"))
    [leg] = submit_a1(client)["legs"]

    [offer] = leg["negotiation"]["messages"]
    assert offer["text"].startswith("Good morning! Hello Alpha Displays")
    assert offer["text"].endswith(messages.REPLY_FORMAT)
    assert offer["terms"] == {"quantity": "500", "delivery_date": "2026-11-20"}


def test_an_offer_wording_that_mentions_price_is_replaced_by_the_template(client):
    use(client, ScriptedLLM(write=lambda body: f"{body} Our budget is Rs 1200 per unit."))
    [leg] = submit_a1(client)["legs"]

    [offer] = leg["negotiation"]["messages"]
    assert "1200" not in offer["text"] and "Hello Alpha Displays, this is Purchasing." in offer["text"]


def test_a_counter_offer_wording_keeps_the_echo_and_the_reply_format(client):
    use(client, ScriptedLLM(extract=[{"action": "COUNTER", "quantity": 500, "delivery_date": "2026-11-25"}],
                            write=lambda body: f"Thanks for your reply. {body}"))
    request = submit_a1(client)
    [leg] = request["legs"]

    reply(client, leg["id"], "500 but delivery 25 Nov")

    [leg] = request_of(client, request)["legs"]
    our_counter = leg["negotiation"]["messages"][-1]
    assert our_counter["text"].startswith("Understood: 500 units by 2026-11-25. Thanks for your reply.")
    assert our_counter["text"].endswith(messages.REPLY_FORMAT)


# -- selection explanation ------------------------------------------------------------------------------------------


def test_the_selection_explanation_is_stored_apart_from_the_deterministic_rationale(client):
    text = "Alpha Displays covers all 500 units by 2026-11-20 at the lowest total cost."
    use(client, ScriptedLLM(explain=text))
    request = submit_a1(client)

    [selection] = audit_of(client, request, "SUPPLIER_SELECTION")
    assert selection["llm_explanation"] == text
    assert selection["reasoning_summary"] and text not in selection["reasoning_summary"]


def test_an_explanation_with_an_unsupported_price_is_not_stored(client):
    use(client, ScriptedLLM(explain="Gamma Screens is free, but Alpha Displays was chosen."))
    request = submit_a1(client)

    [selection] = audit_of(client, request, "SUPPLIER_SELECTION")
    assert selection["llm_explanation"] is None and selection["reasoning_summary"]


def test_without_the_llm_everything_still_works_from_templates(client):
    request = submit_a1(client)  # the default test client has no working LLM
    [leg] = request["legs"]
    [offer] = leg["negotiation"]["messages"]
    assert offer["text"] == messages.offer_text("Alpha Displays", "Display Panel", "DSP-100", Decimal(500),
                                                 date(2026, 11, 20))
    [selection] = audit_of(client, request, "SUPPLIER_SELECTION")
    assert selection["llm_explanation"] is None


def test_a_natural_acceptance_with_a_past_date_is_never_agreed(client):
    use(client, ScriptedLLM(extract=[{"action": "ACCEPT", "quantity": 500, "delivery_date": "2026-11-01"}]))
    request = submit_a1(client)
    [leg] = request["legs"]

    reply(client, leg["id"], "ok, 500 by 1 Nov 2026")

    [leg] = request_of(client, request)["legs"]
    assert leg["status"] == "PENDING"
    assert leg["negotiation"]["messages"][-1]["terms"] == {"quantity": "500", "delivery_date": "2026-11-20"}
