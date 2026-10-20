"""S8 (demo.md §8): competing orders. Four orders on the same day (phones and tablets) need the same main boards, the
same SMT and assembly lines and the same assemblers. Each owner commits its own resource atomically, so nothing is
booked twice: every owner's records still add up, no machine-hours are over-committed, and every order that was
committed ships exactly its committed quantity. An order whose offer can no longer be secured ends NOT_FEASIBLE (the
customer is told), so the run can finish. Played only through the simulator's doors."""

from decimal import Decimal

from app.inventory_agent import reads as stock
from app.planning_agent import reads as plans
from app.simulation.states import reconcile
from tests.platform.phone_factory import KEY, run_day

HEADERS = {"X-Door-Key": KEY}


def test_s8_competing_orders_never_double_book_and_committed_orders_ship_in_full(session_factory, pump, factory):
    client = factory["client"]
    started = client.post("/simulation/scenarios/S8/start", json={"seed": 1}, headers=HEADERS)
    assert started.status_code == 201, started.text

    days = []
    for _ in range(25):
        days.append(run_day(session_factory, pump, client))
        with session_factory() as db:
            assert reconcile(db) == {"inventory": [], "hr": [], "warehouse": [], "planning": []}  # every day
            demands = plans.demands(db)
            if len(demands) == 4 and all(d["status"] in plans.FINISHED_DEMANDS for d in demands):
                break

    with session_factory() as db:
        demands = plans.demands(db)
        assert len(demands) == 4 and all(d["status"] in plans.FINISHED_DEMANDS for d in demands), demands
        assert not plans.open_demand_count(db)
        committed = [d for d in demands if d["committed_quantity"] is not None and d["status"] == "COMPLETED"]
        assert committed, "at least one competing order is committed and delivered"
        for d in committed:
            assert d["quantity_shipped"] == d["committed_quantity"]
        for balance in stock.balances(db).values():  # stock is never promised twice
            assert Decimal(balance["on_hand"]) >= 0 and Decimal(balance["reserved"]) + Decimal(balance["held"]) >= 0
        for work_center in plans.work_centers(db):  # machine-hours are never over-committed
            for day in days:
                assert Decimal(plans.machine_hours_free(db, work_center, day)) >= 0, (work_center, day)
