"""WH-1 and S4 (demo.md §8): Purchasing negotiates a receiving slot with Warehouse before it offers supply to Planning.
With the receiving dock limited (a simulator trigger through Warehouse's own input), the deliveries one order needs no
longer fit on one day: Planning reads Warehouse's free receiving and plans a delivery earlier, Purchasing gets every
slot confirmed by Warehouse before it offers the supply, and the order ships on time. No day takes more than the dock."""

from decimal import Decimal

from sqlalchemy import select

from app.negotiation.models import Message
from app.planning_agent import reads as plans
from app.purchasing_agent.link_models import ReceivingSlotLink
from app.simulation.states import reconcile
from app.warehouse_agent.models import DailyCapacity, ReceivingDay, SpaceCommitment
from tests.platform.phone_factory import KEY, run_day

HEADERS = {"X-Door-Key": KEY}


def test_s4_a_full_receiving_dock_moves_the_delivery_to_a_later_slot_and_the_order_still_ships(
        session_factory, pump, factory):
    client = factory["client"]
    started = client.post("/simulation/scenarios/S4/start", json={"seed": 1}, headers=HEADERS)
    assert started.status_code == 201, started.text

    for _ in range(25):
        run_day(session_factory, pump, client)
        with session_factory() as db:
            assert reconcile(db) == {"inventory": [], "hr": [], "warehouse": [], "planning": []}
            demands = plans.demands(db)
            if demands and all(d["status"] in plans.FINISHED_DEMANDS for d in demands):
                break

    with session_factory() as db:
        (demand,) = plans.demands(db)
        slots = db.scalars(select(ReceivingSlotLink)).all()
        said = [(m.sender, m.envelope["message_type"]) for m in db.scalars(select(Message).order_by(Message.created_at))
                if m.envelope.get("terms", {}) and m.envelope["terms"].get("resource_type") == "RECEIVING_SLOT"]
        assert demand["status"] == "COMPLETED" and demand["quantity_shipped"] == demand["committed_quantity"]
        assert demand["committed_day"] == demand["requested_day"]  # on time
        assert slots and all(s.status == "COMMITTED" for s in slots)
        assert said.count(("PURCHASING", "REQUEST")) == len(slots)  # one slot negotiation per delivery
        capacity = db.get(DailyCapacity, "RECEIVING").units
        assert sum((s.quantity for s in slots), Decimal(0)) > capacity  # they could not all come on one day
        for row in db.scalars(select(ReceivingDay)):  # never more committed on a day than the dock takes
            assert row.committed_units <= capacity, (row.day, row.committed_units)
        deliveries = db.scalars(select(SpaceCommitment).where(SpaceCommitment.kind == "DELIVERY")).all()
        assert all(d.status == "RECEIVED" and d.receiving_units > Decimal(0) for d in deliveries)
