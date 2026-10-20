"""Step 7 (demo.md §9, DM-7): the customer driver. Structured mode: the simulator alone runs an order from the
customer's request to the shipment, with a quantity change on the way (customer -> Sales as data, no language model -> Planning -> owners -> shop floor
-> shipment). Chat mode: the customer writes messages that Sales reads with the model (scripted here).
The factory is `phone_factory.py`; every day goes through the simulator's own day cycle."""

import json
from datetime import timedelta

from sqlalchemy import select

from app.llm.client import FakeLLMClient
from app.main import app
from app.planning_agent import reads as plans
from app.sales_agent import api as sales_api
from app.sales_agent import reads as sales
from app.sales_agent.models import Message
from app.simulation.settings import update_settings
from tests.platform.phone_factory import KEY, run_day


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

    # the customer asks for 90 instead (S7): Planning decides; Sales then shows the quantity Planning commits
    changed = client.post("/simulation/triggers", json={"kind": "CHANGE_ORDER", "params": {"quantity": 90}},
                          headers={"X-Door-Key": KEY})
    assert changed.json()["status"] == "DONE", changed.text
    pump()
    with session_factory() as db:
        demand = plans.demands(db)[0]
        assert demand["committed_quantity"] == "90"
        assert sales.inquiry_status(db, demand["sales_inquiry_id"])["order_quantity"] == "90"

    for _ in range(6):
        run_day(session_factory, pump, client)
        with session_factory() as db:
            if plans.demands(db)[0]["status"] == "COMPLETED":
                break
    with session_factory() as db:
        demand = plans.demands(db)[0]
        assert demand["status"] == "COMPLETED" and demand["quantity_shipped"] == "90"
        assert db.scalars(select(Message).where(Message.direction == "OUT")).all() == []  # no chat replies needed


def test_a_chat_customer_orders_by_writing_messages_that_sales_reads(session_factory, pump, factory):
    """DM-7 chat mode: the simulated customer writes chat messages; Sales reads them with the language model (here a
    scripted fake, so no Ollama is needed) and answers; the customer picks the option and says yes."""
    def model_answer(reply, step="ask_more", **details) -> str:
        return json.dumps({"reply": reply, "next_step": step, "details": details, "reason": "scripted"})

    due = factory["start"] + timedelta(days=7)  # asked on day 1 for 6 days later
    model = FakeLLMClient([
        model_answer("I will check with the planning team.", "send_request", product="S1 Phone", quantity=100,
                     requested_date=due.isoformat()),
        model_answer(f"Here is your option. A) 100 x S1 Phone by {due:%B} {due.day}, {due.year}. Would you like it?"),
        json.dumps({"decision": "choose", "option": "A"}),
        json.dumps({"decision": "yes", "option": None}),
    ])
    app.dependency_overrides[sales_api.get_llm_client] = lambda: model
    try:
        with session_factory() as db:
            update_settings(db, {"customer_orders_per_day": 1, "customer_chat_mode": 1, "customer_quantity_min": 100,
                                 "customer_quantity_max": 100, "customer_lead_days_min": 6,
                                 "customer_lead_days_max": 6})
            db.commit()
        run_day(session_factory, pump, factory["client"])
    finally:
        app.dependency_overrides.pop(sales_api.get_llm_client, None)
    with session_factory() as db:
        (demand,) = plans.demands(db)
        assert (demand["status"], demand["committed_quantity"]) == ("COMMITTED", "100")
        assert sales.inquiry_status(db, demand["sales_inquiry_id"])["stage"] == "CONFIRMED"
        assert db.scalars(select(Message).where(Message.direction == "OUT")).all()  # Sales answered in the chat
