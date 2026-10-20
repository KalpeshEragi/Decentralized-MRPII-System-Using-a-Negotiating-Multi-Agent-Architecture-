"""Step 7 (demo.md §9, DM-7 structured mode): the simulator alone runs an order from the customer's request to the
shipment — simulated customer -> Sales (as data, no language model) -> Planning -> owners -> shop floor -> shipment.
The factory is `phone_factory.py`; every day goes through the simulator's own day cycle."""

from sqlalchemy import select

from app.planning_agent import reads as plans
from app.sales_agent import reads as sales
from app.sales_agent.models import Message
from app.simulation.settings import update_settings
from tests.platform.phone_factory import run_day


def test_a_simulated_customer_order_runs_from_request_to_shipment(session_factory, pump, factory):
    client = factory["client"]
    with session_factory() as db:  # one structured customer on the first day, asking 100 phones 5 days later
        update_settings(db, {"customer_orders_per_day": 1, "customer_quantity_min": 100, "customer_quantity_max": 100,
                             "customer_lead_days_min": 5, "customer_lead_days_max": 5})
        db.commit()
    run_day(session_factory, pump, client)
    with session_factory() as db:
        update_settings(db, {"customer_orders_per_day": 0})
        db.commit()
        (demand,) = plans.demands(db)
        assert (demand["status"], demand["committed_quantity"]) == ("COMMITTED", "100")  # accepted REQUESTED, committed
        status = sales.inquiry_status(db, demand["sales_inquiry_id"])
        assert status["stage"] == "CONFIRMED" and status["order_number"] == demand["order_number"]

    for _ in range(6):
        run_day(session_factory, pump, client)
        with session_factory() as db:
            if plans.demands(db)[0]["status"] == "COMPLETED":
                break
    with session_factory() as db:
        demand = plans.demands(db)[0]
        assert demand["status"] == "COMPLETED" and demand["quantity_shipped"] == "100"
        assert db.scalars(select(Message).where(Message.direction == "OUT")).all() == []  # no chat replies needed
