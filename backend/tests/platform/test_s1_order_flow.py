"""S1 end to end (demo.md §5): one normal order, request -> options -> confirmation -> commitment -> production ->
shipment, through the real doors, negotiations and events, on simulated days. Sales is played by the test at its
doors (door 1 request, door 3 result in Planning's outbox, `OrderConfirmed` through the real Sales connector).
The factory is `phone_factory.py`.
"""

from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import select

from app.events.models import Event
from app.inventory_agent import reads as stock
from app.planning_agent import reads as plans
from app.simulation.clock import today
from tests.platform.phone_factory import KEY, confirm, request, result_for, run_day


def event_types(session_factory) -> list[str]:
    with session_factory() as db:
        return [e.event_type for e in db.scalars(select(Event).order_by(Event.seq))]


def test_one_normal_order_goes_from_request_to_shipment(session_factory, pump, factory):
    client = factory["client"]
    due = factory["start"] + timedelta(days=4)  # PCBs on day 1, phones on day 2, shipped on day 4

    # 1. Request (door 1) -> Planning plans and secures the best option with every owner -> READY to Sales (door 3).
    sent = request(client, "REQ-S1", 100, due, factory["start"])
    assert client.post("/planning/requests", json=sent, headers={"X-Door-Key": "wrong"}).status_code == 403
    assert client.post("/planning/requests", json=sent, headers={"X-Door-Key": KEY}).json()["status"] == "duplicate"
    pump()
    with session_factory() as db:
        result = result_for(db, "REQ-S1")
        assert result["status"] == "READY"
        assert result["options"] == [{"kind": "REQUESTED", "quantity": "100", "delivery_date": due.isoformat(),
                                      "held": True}]
        assert D(stock.stock_position(db, factory["chip"])["held"]) == 200  # held, not reserved: nothing is promised
        assert D(stock.stock_position(db, factory["case"])["held"]) == 100
    assert "PlanCommitted" not in event_types(session_factory)

    # 2. The customer confirms (Sales publishes OrderConfirmed) -> every owner commits -> PlanCommitted.
    confirm(session_factory, sent, "SA-S1", 100, due)
    pump()
    with session_factory() as db:
        plan = plans.get_order_plan(db, "SA-S1")
        assert (plan["status"], plan["committed_quantity"], plan["committed_day"]) == ("COMMITTED", "100", due.isoformat())
        assert sorted(o["item_id"] for o in plan["production_orders"]) == sorted([factory["phone"], factory["pcb"]])
        for item, reserved in ((factory["chip"], 200), (factory["case"], 100)):
            position = stock.stock_position(db, item)
            assert (D(position["held"]), D(position["reserved"])) == (0, reserved)

    # 3. Simulated days: release -> kits issued -> shop floor reports -> goods stored -> shipped on the due day.
    for _ in range(6):
        run_day(session_factory, pump, client)
        with session_factory() as db:
            if plans.get_order_plan(db, "SA-S1")["status"] == "COMPLETED":
                break

    with session_factory() as db:
        plan = plans.get_order_plan(db, "SA-S1")
        assert plan["status"] == "COMPLETED" and today(db) == due  # shipped on the promised day, not before
        assert {o["status"] for o in plan["production_orders"]} == {"COMPLETED"}
        expected = {factory["chip"]: 800, factory["case"]: 400, factory["pcb"]: 0, factory["phone"]: 0}
        for item, on_hand in expected.items():  # every quantity accounted for; nothing left held or reserved
            position = stock.stock_position(db, item)
            assert (D(position["on_hand"]), D(position["reserved"]), D(position["held"])) == (on_hand, 0, 0), item
    happened = event_types(session_factory)
    lifecycle = ["OrderConfirmed", "PlanCommitted", "ProductionOrderReleased", "MaterialIssuedToProduction",
                 "ProductionStarted", "ProductionCompleted", "FinishedGoodsStored", "ShipmentDispatched"]
    assert [happened.index(e) for e in lifecycle] == sorted(happened.index(e) for e in lifecycle)

    # 4. The observer (read-only, for the frontend) tells the same story.
    story = client.get("/observer/orders/SA-S1").json()
    assert story["plan"]["status"] == "COMPLETED"
    assert {n["owner"] for n in story["negotiations"]} == {"INVENTORY", "HR", "WAREHOUSE"}
    assert {n["status"] for n in story["negotiations"]} == {"COMMITTED"}
    assert "ShipmentDispatched" in [e["type"] for e in story["events"]]
    state = client.get("/observer/factory-state").json()
    assert {s["sku"]: s["on_hand"] for s in state["stock"]}["S1-CHIP"] == "800"
    sources = {item["source"] for item in client.get("/observer/timeline").json()["items"]}
    assert {"event", "negotiation"} <= sources
