"""Scenario ONE (SIM-1..3, SIM-5): one order of 80 tablets played hour by hour through the simulator's own cycle.
After the customer's confirmation nothing needs a click: main boards and tablets are made in batches during the
shift, each batch is stored at once (so components exist as soon as they are made), and the order ships complete."""

from collections import Counter
from decimal import Decimal

from sqlalchemy import select

from app.events.models import Event
from app.planning_agent import reads as plans
from app.simulation import runner
from app.simulation.clock import current_hour, shift
from app.simulation.states import reconcile
from tests.platform.phone_factory import KEY


def test_one_order_is_made_in_batches_hour_by_hour_and_delivered(session_factory, pump, factory):
    client = factory["client"]
    assert client.post("/simulation/scenarios/ONE/start", json={"seed": 1}, headers={"X-Door-Key": KEY}).status_code == 201

    def settle() -> dict:
        pump()
        return {}

    hours_seen = set()
    for _ in range(12 * 8):  # at most 12 working days of 8 hours
        step = runner.run_one_hour(session_factory, settle)
        hours_seen.add(step["hour"])
        with session_factory() as db:
            demand = plans.demands(db)[0] if plans.demands(db) else None
            if demand and demand["status"] in plans.FINISHED_DEMANDS:
                break
    with session_factory() as db:
        demand = plans.demands(db)[0]
        assert demand["status"] == "COMPLETED", demand
        assert Decimal(demand["quantity_shipped"]) == Decimal(demand["committed_quantity"]) == 80
        assert reconcile(db) == {"inventory": [], "hr": [], "warehouse": [], "planning": []}
        start, end = shift(db)
        assert len(hours_seen) == end - start  # every working hour was played
        events = db.scalars(select(Event).order_by(Event.seq)).all()

    kinds = Counter(e.event_type for e in events)
    batches = [e for e in events if e.event_type == "ProductionBatchCompleted"]
    assert batches, "production must come in batches"
    assert all(Decimal(b.payload["quantity"]) == 25 for b in batches)        # every batch but the last is a full one
    assert all(start <= b.payload["hour"] <= end for b in batches)           # finished during the shift
    finals = [e for e in events if e.event_type == "ProductionCompleted"]
    assert kinds["FinishedGoodsStored"] == len(batches) + len(finals)       # each batch stored on its own
    for order in {b.payload["production_order_id"] for b in batches}:        # batches add up to the order
        made = sum(Decimal(e.payload["quantity"]) for e in batches + finals if e.payload["production_order_id"] == order)
        assert made == Decimal(next(b.payload["total"] for b in batches if b.payload["production_order_id"] == order))
    first_assembly = min(e.seq for e in events if e.event_type == "ProductionStarted"
                         and e.payload["for_kind"] == "CUSTOMER_DEMAND")
    last_board_stored = max(e.seq for e in events if e.event_type == "FinishedGoodsStored"
                            and e.payload["for_kind"] == "PRODUCTION_ORDER")
    assert last_board_stored < first_assembly  # the main boards existed before the tablets were assembled
    assert kinds["ShipmentDispatched"] >= 1
