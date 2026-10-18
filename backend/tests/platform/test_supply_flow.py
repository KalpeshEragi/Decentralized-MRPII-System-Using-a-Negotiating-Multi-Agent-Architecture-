"""S3 material shortage through the real Purchasing Agent (PI-1 to PI-6): Planning buys what is short, Purchasing
negotiates with a simulated supplier, Planning's COMMIT approves it, the delivery arrives the day before production
and is reserved for the order that needs it. The factory is `phone_factory.py`, with only 100 chips in stock."""

from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import select

from app.events.models import Event
from app.inventory_agent import manager as inventory, reads as stock
from app.planning_agent import reads as plans
from app.inventory_agent.models import IncomingReceipt
from app.purchasing_agent.models import DecisionAudit, ProcurementRequest, PurchaseRequisition
from app.simulation.clock import today
from app.supplier_service.models import Item as SupplierItem, Supplier, SupplierItem as SupplierTerms
from app.warehouse_agent.models import SpaceCommitment
from tests.platform.phone_factory import KEY, confirm, request, result_for, run_day


def short_of_chips(session_factory, factory) -> None:
    """Only 100 chips in stock (200 needed for 100 phones); one supplier with a 2-day lead time."""
    with session_factory() as db:
        inventory.setup(db, [{"item_id": factory["chip"], "on_hand": 100}])
        chip = SupplierItem(sku="S1-CHIP", name="S1 chip", unit="pcs")
        supplier = Supplier(name="Chip Supplier One", is_active=True)
        db.add_all([chip, supplier])
        db.flush()
        db.add(SupplierTerms(supplier_id=supplier.id, item_id=chip.id, lead_time_days=2, min_order_qty=D(1),
                             available_qty=D(1000)))
        db.commit()


def test_a_shortage_is_bought_through_purchasing_and_the_order_still_ships_on_time(session_factory, pump, factory):
    """S3."""
    start, client = factory["start"], factory["client"]
    short_of_chips(session_factory, factory)
    due = start + timedelta(days=6)  # PCBs on day 4: the chips must arrive by day 3; the supplier needs 2 days

    sent = request(client, "REQ-S3", 100, due, start)
    pump()
    with session_factory() as db:
        assert result_for(db, "REQ-S3")["status"] == "READY"
        (procurement,) = db.scalars(select(ProcurementRequest)).all()
        assert (procurement.status, procurement.shortage_quantity) == ("AGREEMENT_PROPOSED", 100)  # held, not bought
        assert procurement.required_date == start + timedelta(days=3)
        assert D(stock.stock_position(db, factory["chip"])["held"]) == 100  # the 100 in stock

    confirm(session_factory, sent, "SA-S3", 100, due)
    pump()
    with session_factory() as db:
        procurement = db.scalars(select(ProcurementRequest)).one()
        assert procurement.status == "COMMITTED"  # Planning's COMMIT is the approval (PI-2)
        approval = db.scalars(select(DecisionAudit).where(DecisionAudit.decision_type == "APPROVAL")).one()
        assert approval.context["decided_by"] == "PLANNING"
        assert plans.get_order_plan(db, "SA-S3")["status"] == "COMMITTED"

    for _ in range(8):
        run_day(session_factory, pump, client)
        with session_factory() as db:
            if plans.get_order_plan(db, "SA-S3")["status"] == "COMPLETED":
                break
    with session_factory() as db:
        assert plans.get_order_plan(db, "SA-S3")["status"] == "COMPLETED" and today(db) == due
        chips = stock.stock_position(db, factory["chip"])
        assert (D(chips["on_hand"]), D(chips["reserved"]), D(chips["held"])) == (0, 0, 0)  # 100 + 100 bought - 200
        received = db.scalars(select(Event).where(Event.event_type == "MaterialReceived")).one()
        assert received.payload["day"] == (start + timedelta(days=3)).isoformat()


def test_a_supplier_delay_moves_the_expected_delivery_and_puts_the_order_at_risk(session_factory, pump, factory):
    """S2. After the purchase is committed, the supplier announces the chips 2 days late (simulator trigger, through
    Purchasing). Warehouse and Inventory move their expected delivery; the PCB order can no longer start on time, so
    Planning reports the order at risk with an estimated new delivery day. Firm work is not moved automatically."""
    start, client = factory["start"], factory["client"]
    short_of_chips(session_factory, factory)
    due = start + timedelta(days=6)
    sent = request(client, "REQ-S2", 100, due, start)
    pump()
    confirm(session_factory, sent, "SA-S2", 100, due)
    pump()
    with session_factory() as db:
        (leg,) = db.scalars(select(PurchaseRequisition).where(PurchaseRequisition.status == "COMMITTED")).all()
    late = leg.agreed_delivery_date + timedelta(days=2)
    answer = client.post("/simulation/triggers/supplier-delay", json={"leg_id": str(leg.id), "new_date": late.isoformat()},
                         headers={"X-Door-Key": KEY})
    assert answer.status_code == 200, answer.text
    pump()

    with session_factory() as db:
        receipt = db.scalars(select(IncomingReceipt).where(IncomingReceipt.purchasing_commitment_ref == str(leg.id))).one()
        delivery = db.scalars(select(SpaceCommitment).where(SpaceCommitment.negotiation_id == str(leg.id))).one()
        assert receipt.expected_day == late and delivery.arrival_day == late
        risk = db.scalars(select(Event).where(Event.event_type == "PlanAtRisk")).one()
        assert (risk.payload["reason"], risk.payload["days_late"]) == ("SUPPLIER_DELAY", 2)
        assert risk.payload["estimated_delivery_day"] == (due + timedelta(days=2)).isoformat()
        assert plans.get_order_plan(db, "SA-S2")["status"] == "COMMITTED"  # nothing changed without the customer
