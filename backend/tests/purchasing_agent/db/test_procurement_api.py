"""The Purchasing API on the test database: a Procurement Request becomes one Leg and one supplier offer.

Fixed clock: 2026-11-02 in Asia/Kolkata, the fixture's selection date.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.core.errors import install_error_handlers
from app.purchasing_agent import api
from app.supplier_service.seed import ITEM_IDS, SUPPLIER_IDS

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def make_client(engine) -> TestClient:
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def session_per_request():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    install_error_handlers(app)  # the same error format as the real backend
    app.include_router(api.router)
    app.dependency_overrides[get_db] = session_per_request
    app.dependency_overrides[api.get_clock] = lambda: lambda: NOW
    return TestClient(app)


def submit(client, ref="REQ-A1", item="DSP-100", quantity=500, required_date="2026-11-20"):
    return client.post("/purchasing/procurement-requests", json={
        "request_ref": ref, "item_id": str(ITEM_IDS[item]), "shortage_quantity": quantity,
        "required_date": required_date, "priority": 1, "requested_by": "test"})


def test_a1_a_request_selects_alpha_and_sends_it_a_template_offer_without_price(db, engine):
    client = make_client(engine)

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


def test_n11_the_same_request_ref_returns_the_existing_request_and_creates_no_new_leg(db, engine):
    client = make_client(engine)
    first = submit(client, ref="REQ-N11").json()

    again = submit(client, ref="REQ-N11", quantity=999)  # a retry, even with other values, changes nothing
    assert again.status_code == 200
    assert again.json() == first
    assert len(again.json()["legs"]) == 1


def test_unknown_items_and_invalid_input_are_refused_in_the_standard_error_format(db, engine):
    client = make_client(engine)

    unknown = client.post("/purchasing/procurement-requests", json={
        "request_ref": "REQ-X", "item_id": "00000000-0000-0000-0000-000000000000", "shortage_quantity": 10,
        "required_date": "2026-11-20", "priority": 1, "requested_by": "test"})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "VALIDATION_ERROR"
    assert unknown.json()["error"]["details"] == [{"field": "item_id", "issue": "unknown item"}]

    for bad in ({"shortage_quantity": 0}, {"shortage_quantity": -5}, {"required_date": None}, {"request_ref": "  "}):
        body = {"request_ref": "REQ-X", "item_id": str(ITEM_IDS["DSP-100"]), "shortage_quantity": 10,
                "required_date": "2026-11-20", "priority": 1, "requested_by": "test"} | bad
        response = client.post("/purchasing/procurement-requests", json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR", bad

    # Nothing was saved for the refused requests: the reference is still free.
    assert submit(client, ref="REQ-X").status_code == 201
    assert client.get("/purchasing/procurement-requests/00000000-0000-0000-0000-000000000000").status_code == 404


def test_without_a_feasible_priced_supplier_the_request_fails_and_opens_no_negotiation(db, engine):
    client = make_client(engine)

    failed = submit(client, ref="REQ-A4", quantity=300, required_date="2026-11-05").json()

    assert (failed["status"], failed["split_type"], failed["legs"]) == ("FAILED", None, [])
    assert failed["status_reason"]
