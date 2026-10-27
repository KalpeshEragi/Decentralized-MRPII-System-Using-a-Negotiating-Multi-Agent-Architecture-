"""The read-only Sales dashboard views count and list exactly what is in the Sales tables, and change nothing."""

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.sales_agent import api, dashboard
from app.sales_agent.models import AuditLog, Conversation, Customer, Inquiry, Option, Order, Product


def _seed(db):
    """One customer with a confirmed order, and one unknown sender whose inquiry closed with no option."""
    product = Product(sku="WIDGET", name="Widget")
    customer = Customer(phone="+100", name="Asha")
    db.add_all([product, customer])
    db.flush()
    conv = Conversation(channel="SIMULATED", sender_ref="+100", customer_id=customer.id)
    other = Conversation(channel="TEST", sender_ref="+200")
    db.add_all([conv, other])
    db.flush()
    won = Inquiry(conversation_id=conv.id, customer_id=customer.id, stage="CONFIRMED", product_id=product.id,
                  quantity=Decimal(50), requested_date=date(2026, 11, 10))
    lost = Inquiry(conversation_id=other.id, stage="CLOSED", closed_reason="NO_OPTION")
    db.add_all([won, lost])
    db.flush()
    option = Option(inquiry_id=won.id, kind="LATER_DATE", quantity=Decimal(50), delivery_date=date(2026, 11, 12),
                    status="SELECTED")
    db.add(option)
    db.flush()
    db.add_all([
        Order(order_number="SO-1", customer_id=customer.id, inquiry_id=won.id, option_id=option.id,
              product_id=product.id, quantity=Decimal(50), delivery_date=date(2026, 11, 12),
              confirmed_at=datetime(2026, 10, 1, tzinfo=timezone.utc)),
        AuditLog(actor="SALES_AI", event_type="MODEL_FAILED", inquiry_id=lost.id, details={"error": "timeout"}),
        AuditLog(actor="SYSTEM", event_type="OPTIONS_PRESENTED", inquiry_id=won.id, details={}),
    ])
    db.commit()
    return customer


def test_overview_counts_the_sales_tables(db):
    _seed(db)
    view = dashboard.overview(db)
    assert view["customers"] == 1
    assert view["inquiries"] == 2 and view["inquiry_stages"] == {"CONFIRMED": 1, "CLOSED": 1}
    assert view["closed_reasons"] == {"NO_OPTION": 1}
    assert view["orders_placed"] == 1 and view["order_statuses"] == {"CONFIRMED": 1}
    assert view["conversion_rate"] == 0.5 and view["units_ordered"] == 50
    assert view["ai_failures"] == 1


def test_lists_and_rules_are_served_read_only(db, engine):
    customer = _seed(db)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(api.router)
    def session_per_request():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = session_per_request
    client = TestClient(app)

    orders = client.get("/sales/dashboard/orders").json()
    assert [(o["order_number"], o["customer"], o["product"], o["quantity"], o["delivery_date"]) for o in orders] == \
        [("SO-1", "Asha", "Widget", 50, "2026-11-12")]
    inquiries = client.get("/sales/dashboard/inquiries").json()
    assert {(i["stage"], i["customer"]) for i in inquiries} == {("CONFIRMED", "Asha"), ("CLOSED", "+200")}
    assert client.get("/sales/dashboard/customers").json()[0]["orders"] == 1
    assert client.get(f"/sales/dashboard/customers/{customer.id}/memories").json() == []
    assert [a["event_type"] for a in client.get("/sales/dashboard/audit", params={"event_type": "MODEL_FAILED"}).json()] \
        == ["MODEL_FAILED"]
    rules = client.get("/sales/dashboard/rules").json()
    assert {r["name"] for r in rules["tuning"]} >= {"Offer validity", "Planning wait limit"}
    assert "GATHERING" in rules["safety"][0]["value"]

    assert dashboard.overview(db)["orders_placed"] == 1  # reading changed nothing
