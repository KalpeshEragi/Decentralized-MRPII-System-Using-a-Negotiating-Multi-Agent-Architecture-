"""S1 end to end (demo.md §5): one normal order, request -> options -> confirmation -> commitment -> production ->
shipment, through the real doors, negotiations and events, on simulated days. Sales is played by the test at its
doors (door 1 request, door 3 result in Planning's outbox, `OrderConfirmed` through the real Sales connector).

Factory: a phone = 1 PCB + 1 case; a PCB = 2 chips. PCBs are made on SMT, phones on ASM. Chips and cases are in stock.
"""

import uuid
from datetime import timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_db
from app.events.models import Event
from app.hr_agent import manager as hr
from app.inventory_agent import manager as inventory, reads as stock
from app.main import app
from app.models.core import Bom, BomItem, Item, ItemType, Routing
from app.planning_agent import manager as planning, reads as plans
from app.planning_agent.models import SalesOutbox
from app.sales_agent.models import Product
from app.sales_agent.planning import RealPlanning
from app.simulation.clock import next_day, today
from app.warehouse_agent import manager as warehouse

PRODUCT_ID = uuid.UUID("5e1e0000-0000-4000-8000-000000000001")
KEY = "s1-test-key"


def make_item(db, sku, kind, sourcing, space=0) -> str:
    item = Item(sku=sku, name=sku, item_type=kind, unit="pcs", sourcing=sourcing, space_per_unit=D(space))
    db.add(item)
    db.flush()
    return str(item.id)


def make_bom(db, parent, lines) -> None:
    bom = Bom(parent_item_id=uuid.UUID(parent), version=1)
    db.add(bom)
    db.flush()
    for child, per in lines:
        db.add(BomItem(bom_id=bom.id, component_item_id=uuid.UUID(child), quantity_required=D(per)))


@pytest.fixture
def factory(session_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "planning_door_key", KEY)
    monkeypatch.setattr(get_settings(), "simulation_door_key", KEY)

    def test_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with session_factory() as db:
        phone = make_item(db, "S1-PHONE", ItemType.FINISHED_PRODUCT, "MAKE", space=1)
        pcb = make_item(db, "S1-PCB", ItemType.COMPONENT, "MAKE")
        chip = make_item(db, "S1-CHIP", ItemType.RAW_MATERIAL, "BUY")
        case = make_item(db, "S1-CASE", ItemType.RAW_MATERIAL, "BUY")
        make_bom(db, phone, [(pcb, 1), (case, 1)])
        make_bom(db, pcb, [(chip, 2)])
        db.add_all([Routing(item_id=uuid.UUID(pcb), step_no=1, work_center_code="SMT", skill="SMT", crew_size=1,
                            setup_hours=D(1), run_hours_per_unit=D("0.05")),
                    Routing(item_id=uuid.UUID(phone), step_no=1, work_center_code="ASM", skill="ASSEMBLY",
                            crew_size=1, setup_hours=D(1), run_hours_per_unit=D("0.05"))])
        db.merge(Product(id=PRODUCT_ID, sku="S1-PHONE", name="S1 Phone", active=True))
        db.flush()
        inventory.setup(db, [{"item_id": chip, "on_hand": 1000}, {"item_id": case, "on_hand": 500}])
        planning.setup(db, {"SMT": 8, "ASM": 8})
        hr.setup(db, [{"code": "S1", "primary_skill": "SMT"}, {"code": "S2", "primary_skill": "SMT"},
                      {"code": "A1", "primary_skill": "ASSEMBLY"}, {"code": "A2", "primary_skill": "ASSEMBLY"}])
        warehouse.setup(db, {"zones": {"MATERIALS": {"capacity_units": 10000}, "FINISHED_GOODS": {"capacity_units": 500}},
                             "receiving_units_per_day": 1000, "shipping_units_per_day": 1000})
        start = today(db)
        db.commit()
    yield {"phone": phone, "pcb": pcb, "chip": chip, "case": case, "start": start}
    app.dependency_overrides.pop(get_db, None)


def event_types(session_factory) -> list[str]:
    with session_factory() as db:
        return [e.event_type for e in db.scalars(select(Event).order_by(Event.seq))]


def test_one_normal_order_goes_from_request_to_shipment(session_factory, pump, factory):
    client = TestClient(app)
    due = factory["start"] + timedelta(days=4)  # PCBs on day 1, phones on day 2, shipped on day 4
    request = {"request_ref": "REQ-S1", "inquiry_id": str(uuid.uuid4()), "customer": {"phone": "+1"},
               "order": {"product_id": str(PRODUCT_ID), "quantity": 100, "requested_date": due.isoformat(),
                         "order_date": factory["start"].isoformat()}}

    # 1. Request (door 1) -> Planning plans and secures the best option with every owner -> READY to Sales (door 3).
    assert client.post("/planning/requests", json=request, headers={"X-Door-Key": "wrong"}).status_code == 403
    assert client.post("/planning/requests", json=request, headers={"X-Door-Key": KEY}).json()["status"] == "received"
    assert client.post("/planning/requests", json=request, headers={"X-Door-Key": KEY}).json()["status"] == "duplicate"
    pump()
    with session_factory() as db:
        (result,) = db.scalars(select(SalesOutbox)).all()
        assert result.payload["status"] == "READY"
        assert result.payload["options"] == [{"kind": "REQUESTED", "quantity": "100", "delivery_date": due.isoformat(),
                                              "held": True}]
        assert D(stock.stock_position(db, factory["chip"])["held"]) == 200  # held, not reserved: nothing is promised
        assert D(stock.stock_position(db, factory["case"])["held"]) == 100
    assert "PlanCommitted" not in event_types(session_factory)

    # 2. The customer confirms (Sales publishes OrderConfirmed) -> every owner commits -> PlanCommitted.
    RealPlanning(session_factory).send_confirmation({"inquiry_id": request["inquiry_id"], "order_number": "SA-S1",
                                                     "quantity": "100", "delivery_date": due.isoformat()})
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
        with session_factory() as db:
            next_day(db)
            db.commit()
        pump()
        with session_factory() as db:
            day = today(db)
            starting = [o["id"] for o in plans.production_orders(db, "RELEASED") if o["start_day"] == day.isoformat()]
        for order_id in starting:  # the simulated shop floor runs each order in one day
            for kind, quantity in (("STARTED", None), ("QUANTITY_COMPLETED", "100")):
                body = {"report_id": f"{order_id}:{kind}", "production_order_id": order_id, "kind": kind,
                        "quantity": quantity}
                assert client.post("/planning/shop-floor/reports", json=body, headers={"X-Door-Key": KEY}).status_code == 202
        pump()
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
