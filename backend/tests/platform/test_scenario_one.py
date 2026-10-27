"""Scenario ONE (SIM-1..3, SIM-5, DC-1): one order of 150 tablets played hour by hour through the simulator's own cycle.
Planning asks the owners for quotes and plans from them (not from their data): stock covers part, main boards and
tablets are made in batches, and what stock cannot cover is bought through Purchasing. After the customer's
confirmation nothing needs a click: purchases arrive, batches are made and stored, the order ships complete."""

from collections import Counter
from decimal import Decimal

from sqlalchemy import select

from app.events.models import Event
from app.negotiation.models import Message
from app.planning_agent import reads as plans
from app.planning_agent.models import AuditLog
from app.simulation import runner
from app.simulation.clock import shift
from app.simulation.states import reconcile
from tests.platform.phone_factory import KEY


def test_one_order_is_planned_from_quotes_made_and_bought_and_delivered(session_factory, pump, factory):
    client = factory["client"]
    assert client.post("/simulation/scenarios/ONE/start", json={"seed": 1}, headers={"X-Door-Key": KEY}).status_code == 201

    def settle() -> dict:
        pump()
        return {}

    hours_seen = set()
    for _ in range(16 * 8):  # at most 16 working days of 8 hours
        step = runner.run_one_hour(session_factory, settle)
        hours_seen.add(step["hour"])
        with session_factory() as db:
            demands = plans.demands(db)
            if demands and demands[0]["status"] in plans.FINISHED_DEMANDS:
                break

    with session_factory() as db:
        demand = plans.demands(db)[0]
        assert demand["status"] == "COMPLETED", demand
        assert Decimal(demand["quantity_shipped"]) == Decimal(demand["committed_quantity"]) == 150
        assert reconcile(db) == {"inventory": [], "hr": [], "warehouse": [], "planning": []}
        start, end = shift(db)
        assert len(hours_seen) == end - start
        events = db.scalars(select(Event).order_by(Event.seq)).all()
        messages = db.scalars(select(Message)).all()
        plan_decision = db.scalar(select(AuditLog).where(AuditLog.event_type == "DECISION")).details

    # 1. Planning asked the owners and planned from their quotes (DC-1)
    quote_requests = Counter(m.receiver for m in messages if m.envelope["message_type"] == "QUOTE_REQUEST")
    quotes = Counter(m.sender for m in messages if m.envelope["message_type"] == "QUOTE")
    assert set(quote_requests) == {"INVENTORY", "PURCHASING", "HR", "WAREHOUSE"} and quotes == quote_requests
    assert plan_decision["decision_point"] == "D6" and plan_decision["action"] == "PLAN_REQUESTED"
    made, bought = plan_decision["params"]["make"], plan_decision["params"]["buy"]
    assert any("MB" in m for m in made) and any("TABLET-T" in m for m in made)  # make what is made
    assert bought  # buy what stock cannot cover (make or buy)

    # 2. what was bought arrived through Purchasing and the Warehouse
    kinds = Counter(e.event_type for e in events)
    assert kinds["ProcurementCommitted"] >= 1 and kinds["MaterialReceived"] >= 1

    # 3. production in batches, each stored on its own, components before assembly
    batches = [e for e in events if e.event_type == "ProductionBatchCompleted"]
    finals = [e for e in events if e.event_type == "ProductionCompleted"]
    assert batches and all(Decimal(b.payload["quantity"]) == 25 for b in batches)
    assert all(start <= b.payload["hour"] <= end for b in batches)
    assert kinds["FinishedGoodsStored"] == len(batches) + len(finals)
    first_assembly = min(e.seq for e in events if e.event_type == "ProductionStarted"
                         and e.payload["for_kind"] == "CUSTOMER_DEMAND")
    last_board_stored = max(e.seq for e in events if e.event_type == "FinishedGoodsStored"
                            and e.payload["for_kind"] == "PRODUCTION_ORDER")
    assert last_board_stored < first_assembly
    assert kinds["ShipmentDispatched"] >= 1
