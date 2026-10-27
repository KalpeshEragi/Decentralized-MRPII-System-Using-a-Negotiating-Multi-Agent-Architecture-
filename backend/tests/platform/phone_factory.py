"""The small phone factory used by the end-to-end tests (S1, S6, ...), and helpers that play Sales and the shop floor.

A phone = 1 PCB + 1 case; a PCB = 2 chips. PCBs are made on SMT, phones on ASM. Chips (1000) and cases (500) are in
stock; two SMT and two assembly workers; 8 machine-hours per work center and day.
"""

import uuid
from datetime import date
from decimal import Decimal as D

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.hr_agent import manager as hr
from app.inventory_agent import manager as inventory
from app.models.core import Bom, BomItem, Item, ItemType, Routing
from app.planning_agent import manager as planning
from app.planning_agent.models import SalesOutbox
from app.sales_agent.models import Product
from app.sales_agent.planning import RealPlanning
from app.simulation import runner
from app.simulation.clock import today
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


def build(db) -> dict:
    """Create the factory (master data + every agent's starting state). Returns the item ids and the start day."""
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
    return {"phone": phone, "pcb": pcb, "chip": chip, "case": case, "start": today(db)}


def request(client: TestClient, ref: str, quantity: int, due: date, order_day: date) -> dict:
    """Sales sends a request to Planning door 1. Returns the request (its inquiry id is needed to confirm)."""
    body = {"request_ref": ref, "inquiry_id": str(uuid.uuid4()), "customer": {"phone": "+1"},
            "order": {"product_id": str(PRODUCT_ID), "quantity": quantity, "requested_date": due.isoformat(),
                      "order_date": order_day.isoformat()}}
    assert client.post("/planning/requests", json=body, headers={"X-Door-Key": KEY}).json()["status"] == "received"
    return body


def result_for(db, ref: str) -> dict:
    """Planning's result for a request, as it waits in Planning's outbox to Sales (door 3)."""
    return next(r.payload for r in db.scalars(select(SalesOutbox)) if r.payload["request_ref"] == ref)


def confirm(session_factory, sent: dict, order_number: str, quantity: int, due: date) -> None:
    """The customer accepts the option: Sales publishes OrderConfirmed through the real connector."""
    RealPlanning(session_factory).send_confirmation({  # the full OrderConfirmed shape Sales sends (event catalogue)
        "inquiry_id": sent["inquiry_id"], "order_number": order_number, "quantity": str(quantity),
        "delivery_date": due.isoformat(), "option_id": "test-option", "customer_id": "test-customer",
        "product_id": "test-product", "confirmed_at": "2026-11-02T09:00:00+00:00", "confirming_message_id": "test-yes",
        "payment": "ASSUMED_PAID"})


def run_day(session_factory, pump, client: TestClient) -> date:
    """One simulated day through the simulator's own day cycle (`app/simulation/runner.py`): advance the clock, let
    every agent finish, the simulated shop floor reports, let every agent finish. The pump stands in for the
    background workers (and fails the test if any work is left unfinished)."""
    def settle() -> dict:
        pump()
        return {}

    return date.fromisoformat(runner.run_one_day(session_factory, settle)["day"])
