"""Phase 3 end to end through the API on the X1 baseline (needs TEST_DATABASE_URL):
order -> Planning -> Inventory -> A2A REQUEST -> Purchasing -> supplier interface -> AGREEMENT_PROPOSED / REJECTED /
FAILED -> Inventory -> Planning. A2A calls go through the app's own endpoints in-process (TestClient, same wire
format). Without an LLM (FakeLLMClient with no replies) Purchasing's deterministic policy decides.

Baseline shortages: Display 500 and Battery 600, both required by 2026-10-26. Purchasing's round-1 offers:
Display 500 by 2026-10-15 (Alpha Displays), Battery 600 by 2026-10-13 (Volt Power).
"""

import json
import uuid

import pytest
from sqlalchemy import func, select

from app.agents import base
from app.core.errors import AppError, ErrorCode
from app.data import x1_fixture as x1
from app.llm.client import FakeLLMClient
from app.models import inventory, negotiation as tables, purchasing
from app.services import negotiation_service, requisition_service
from app.services.audit_service import AGENT_INVENTORY, AGENT_PLANNING, AGENT_PURCHASING, agent_uuid

LATE = "2026-10-30"  # after required_by 2026-10-26


def start(api, order_id) -> dict:
    response = api.post(f"/agents/planning/orders/{order_id}")
    assert response.status_code == 200, response.text
    return response.json()


def procurement(body: dict, component: str) -> dict:
    return next(p for p in body["procurement"] if p["item_id"] == x1.COMPONENT_IDS[component])


def respond(api, negotiation_id, round_number, kind, quantity=None, delivery=None):
    body = {"round_number": round_number, "response_type": kind, "quantity": quantity, "delivery_date": delivery}
    return api.post(f"/supplier-interface/negotiations/{negotiation_id}/responses", json=body)


def decision_types(api, **query) -> list[tuple[str, str]]:
    return [(d["agent"], d["decision_type"]) for d in api.get("/agents/decisions", params=query).json()]


def terms_of(message: dict) -> tuple:
    terms = message["payload"]["terms"]
    return terms["quantity"], terms["delivery_date"]


def test_order_starts_inventory_to_purchasing_negotiations_over_a2a(api, db, order_id):
    body = start(api, order_id)
    assert body["plan_status"] == "SHORTAGE" and len(body["procurement"]) == 2
    display, battery = procurement(body, "Display"), procurement(body, "Battery")
    for entry in (display, battery):
        assert (entry["session_status"], entry["round_number"], entry["awaiting_supplier"], entry["outcome"]) == (
            "NEGOTIATING", 1, True, None)

    session = api.get(f"/negotiations/{display['negotiation_id']}").json()
    request, offer = session["messages"]
    assert (request["message_type"], request["sender"], request["receiver"]) == ("REQUEST", "INVENTORY", "PURCHASING")
    assert request["payload"]["terms"] == {"quantity": 500, "required_date": "2026-10-26", "delivery_date": None, "priority": 1}
    assert (offer["message_type"], offer["sender"], offer["receiver"]) == ("OFFER", "PURCHASING", "SUPPLIER_INTERFACE")
    assert terms_of(offer) == (500, "2026-10-15")
    battery_session = api.get(f"/negotiations/{battery['negotiation_id']}").json()
    assert terms_of(battery_session["messages"][1]) == (600, "2026-10-13")

    db.expire_all()
    initiators = set(db.scalars(select(tables.NegotiationSession.initiator_agent_id)))
    assert initiators == {agent_uuid(db, AGENT_INVENTORY)}  # Inventory starts procurement, not Planning
    requisitions = list(db.scalars(select(purchasing.PurchaseRequisition)))
    assert sorted(r.quantity_required for r in requisitions) == [500, 600]
    assert {(r.created_by_agent, r.status) for r in requisitions} == {(agent_uuid(db, AGENT_PURCHASING), "OPEN")}
    assert db.scalar(select(func.count()).select_from(inventory.InventoryReservation)) == 0
    senders = set(db.scalars(select(tables.NegotiationMessage.sender_type)))
    assert senders == {"INVENTORY", "PURCHASING"}

    types = decision_types(api, order_id=str(order_id))
    for expected in [(AGENT_INVENTORY, "AVAILABILITY_ASSESSED"), (AGENT_INVENTORY, "NEGOTIATION_REQUEST"),
                     (AGENT_PURCHASING, "REQUISITION_CREATED"), (AGENT_PURCHASING, "NEGOTIATION_DECISION"),
                     (AGENT_PURCHASING, "LLM_PROPOSAL_REJECTED")]:
        assert expected in types
    assert api.get("/agents/PRODUCTION_PLANNING_AGENT/state").json()["current_task"]["status"] == "WAITING"
    assert api.get("/agents/INVENTORY_AGENT/state").json()["current_task"]["task_type"] == "AWAIT_NEGOTIATION_RESULT"
    purchasing_state = api.get("/agents/PURCHASING_AGENT/state").json()
    assert purchasing_state["current_task"]["status"] == "WAITING"
    assert len(purchasing_state["own_offer_history"]) == 1 and purchasing_state["negotiation_rules"]["max_rounds"] == 3


def test_supplier_accept_gives_agreement_proposed_without_commit(api, db, order_id):
    display = procurement(start(api, order_id), "Display")
    response = respond(api, display["negotiation_id"], 1, "ACCEPT")
    assert response.status_code == 200, response.text
    session = response.json()
    assert (session["status"], session["outcome"], session["round_number"]) == ("AGREEMENT_PROPOSED", "AGREEMENT", 1)
    assert session["agreement"]["agreed_terms"]["quantity"] == 500
    assert session["agreement"]["agreed_terms"]["delivery_date"] == "2026-10-15"
    assert (session["agreement"]["validated"], session["agreement"]["committed"]) == (True, False)
    last = session["messages"][-1]
    assert (last["message_type"], last["sender"], last["receiver"]) == ("AGREEMENT_PROPOSED", "PURCHASING", "INVENTORY")
    assert all(m["message_type"] != "COMMIT" for m in session["messages"])

    db.expire_all()
    assert negotiation_service.scheduled_receipts(db, {x1.COMPONENT_IDS["Display"]}) == []  # not committed
    assert requisition_service.get(db, uuid.UUID(display["negotiation_id"]))["status"] == "AGREEMENT_PROPOSED"
    results = api.get(f"/agents/planning/orders/{order_id}/procurement-results").json()
    assert {r["item_id"]: r["outcome"] for r in results} == {
        x1.COMPONENT_IDS["Display"]: "AGREEMENT", x1.COMPONENT_IDS["Battery"]: None}
    received = decision_types(api, negotiation_id=display["negotiation_id"])
    assert (AGENT_INVENTORY, "NEGOTIATION_RESULT_RECEIVED") in received
    assert (AGENT_PLANNING, "NEGOTIATION_RESULT_RECEIVED") in received
    assert api.get("/agents/PRODUCTION_PLANNING_AGENT/state").json()["current_task"]["status"] == "WAITING"  # Battery open
    inventory_state = api.get("/agents/INVENTORY_AGENT/state").json()
    assert inventory_state["current_task"]["status"] == "DONE"
    assert inventory_state["opponent_offer_history"][0]["message_type"] == "AGREEMENT_PROPOSED"


def test_counter_then_accept(api, order_id):
    display = procurement(start(api, order_id), "Display")
    session = respond(api, display["negotiation_id"], 1, "COUNTER_OFFER", 500, LATE).json()
    assert (session["status"], session["round_number"], session["awaiting_supplier"]) == ("NEGOTIATING", 2, True)
    counter = session["messages"][-1]
    assert (counter["message_type"], counter["sender"]) == ("COUNTER_OFFER", "PURCHASING")
    assert terms_of(counter) == (500, "2026-10-26")  # the supplier's late date pulled back to required_by
    session = respond(api, display["negotiation_id"], 2, "ACCEPT").json()
    assert session["status"] == "AGREEMENT_PROPOSED"
    assert session["agreement"]["agreed_terms"]["delivery_date"] == "2026-10-26"


def test_supplier_reject_is_rejected_and_failed_for_planning(api, db, order_id):
    display = procurement(start(api, order_id), "Display")
    session = respond(api, display["negotiation_id"], 1, "REJECT").json()
    assert (session["status"], session["outcome"]) == ("REJECTED", "FAILED")
    db.expire_all()
    assert requisition_service.get(db, uuid.UUID(display["negotiation_id"]))["status"] == "REJECTED"
    results = api.get(f"/agents/planning/orders/{order_id}/procurement-results").json()
    assert next(r for r in results if r["negotiation_id"] == display["negotiation_id"])["outcome"] == "FAILED"
    assert (AGENT_PLANNING, "NEGOTIATION_RESULT_RECEIVED") in decision_types(api, negotiation_id=display["negotiation_id"])


def test_three_unacceptable_rounds_end_failed(api, db, order_id):
    display = procurement(start(api, order_id), "Display")
    negotiation_id = display["negotiation_id"]
    for round_number in (1, 2, 3):
        session = respond(api, negotiation_id, round_number, "COUNTER_OFFER", 500, LATE).json()
    assert (session["status"], session["outcome"], session["round_number"]) == ("FAILED", "FAILED", 3)
    assert respond(api, negotiation_id, 4, "ACCEPT").status_code == 409
    db.expire_all()
    assert requisition_service.get(db, uuid.UUID(negotiation_id))["status"] == "FAILED"
    state = api.get("/agents/PURCHASING_AGENT/state").json()
    assert [r["round"] for r in state["own_offer_history"]] == [1, 2, 3]
    assert [r["round"] for r in state["opponent_offer_history"]] == [1, 2, 3]
    assert (AGENT_PURCHASING, "NEGOTIATION_FAILED") in decision_types(api, negotiation_id=negotiation_id)
    results = api.get(f"/agents/planning/orders/{order_id}/procurement-results").json()
    assert next(r for r in results if r["negotiation_id"] == negotiation_id)["outcome"] == "FAILED"


def test_invalid_supplier_responses_change_nothing(api, order_id):
    display = procurement(start(api, order_id), "Display")
    negotiation_id = display["negotiation_id"]
    before = api.get(f"/negotiations/{negotiation_id}").json()["messages"]
    wrong_round = respond(api, negotiation_id, 2, "ACCEPT")
    assert wrong_round.status_code == 409 and wrong_round.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    no_terms = respond(api, negotiation_id, 1, "COUNTER_OFFER")
    assert no_terms.status_code == 422 and no_terms.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.get(f"/negotiations/{negotiation_id}").json()["messages"] == before


def test_valid_llm_proposal_is_used_and_invalid_one_replaced(api, order_id, monkeypatch):
    # (600, 2026-10-20) is within both shortages' limits: Display [500, 600] by [10-15, 10-26], Battery [600, 700] by [10-13, 10-26].
    proposal = {"action": "COUNTER_OFFER", "terms": {"quantity": 600, "delivery_date": "2026-10-20"},
                "rationale": "One date that suits both suppliers."}
    monkeypatch.setattr(base, "_llm_client", FakeLLMClient([json.dumps(proposal)]))
    body = start(api, order_id)
    display = procurement(body, "Display")
    offer = api.get(f"/negotiations/{display['negotiation_id']}").json()["messages"][1]
    assert terms_of(offer) == (600, "2026-10-20")
    assert (AGENT_PURCHASING, "LLM_PROPOSAL_REJECTED") not in decision_types(api, order_id=str(order_id))

    # After the supplier accepts, the same proposal would only repeat the table: refused, the policy agrees instead.
    session = respond(api, display["negotiation_id"], 1, "ACCEPT").json()
    assert session["status"] == "AGREEMENT_PROPOSED" and session["agreement"]["agreed_terms"]["quantity"] == 600
    types = decision_types(api, negotiation_id=display["negotiation_id"])
    assert types.count((AGENT_PURCHASING, "LLM_PROPOSAL_REJECTED")) == 1


def test_handling_the_order_again_opens_no_new_session(api, db, order_id):
    first = start(api, order_id)
    second = start(api, order_id)
    assert {p["negotiation_id"] for p in first["procurement"]} == {p["negotiation_id"] for p in second["procurement"]}
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(tables.NegotiationSession)) == 2
    assert db.scalar(select(func.count()).select_from(tables.NegotiationMessage)) == 4  # REQUEST + OFFER each


def test_order_without_shortage_needs_no_procurement(api):
    from app.data.seed_data import CUSTOMER_ID

    order = api.post("/orders", json={"order_number": "SO-0002", "customer_id": str(CUSTOMER_ID),
                                      "order_date": "2026-10-01", "due_date": "2026-10-31", "priority": 2,
                                      "lines": [{"item_id": x1.PRODUCT_ID, "quantity": 100}]}).json()
    body = start(api, order["id"])
    assert (body["plan_status"], body["procurement"]) == ("VALIDATED", [])
    assert all(a["action"] == "ALLOCATE_FROM_STOCK" for a in body["inventory_assessment"])
    assert api.get("/agents/PRODUCTION_PLANNING_AGENT/state").json()["current_task"]["status"] == "DONE"


def test_only_purchasing_may_create_requisitions(db, order_id):
    from app.services import planning_service

    plan = planning_service.run_plan(db, order_id)
    with pytest.raises(AppError) as exc:
        requisition_service.create(db, uuid.uuid4(), plan.shortages[0], AGENT_PLANNING)
    assert exc.value.code == ErrorCode.BUSINESS_RULE_VIOLATION


def test_unknown_order_and_agent_use_c5_errors(api):
    assert api.post(f"/agents/planning/orders/{uuid.uuid4()}").json()["error"]["code"] == "NOT_FOUND"
    assert api.get("/agents/SUPPLIER_AGENT/state").json()["error"]["code"] == "VALIDATION_ERROR"
