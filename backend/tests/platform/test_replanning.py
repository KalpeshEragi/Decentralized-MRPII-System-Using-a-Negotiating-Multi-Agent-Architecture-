"""Step 6 replanning (planning_agent/2 §3 method 8, RD-4): what a fact change does to committed plans.
The factory is `phone_factory.py`."""

from datetime import date, timedelta
from decimal import Decimal as D

from app.events import channel
from app.hr_agent import manager as hr_manager, reads as workforce
from app.inventory_agent import reads as stock
from app.planning_agent import plan as planner, reads as plans
from app.simulation.clock import today
from app.warehouse_agent import reads as space
from tests.platform.phone_factory import confirm, request, run_day


def test_cancellation_releases_exactly_what_was_held_and_released_work_goes_on(session_factory, pump, factory):
    """S6. Due in 3 days: the PCB order starts tomorrow, so it is already RELEASED when the customer cancels and is
    never changed automatically; the phone order is only FIRM and is cancelled. Every owner releases exactly what it
    held for the cancelled parts; the PCBs that are still made go to free stock."""
    start, client = factory["start"], factory["client"]
    due = start + timedelta(days=3)
    sent = request(client, "REQ-S6", 100, due, start)
    pump()
    confirm(session_factory, sent, "SA-S6", 100, due)
    pump()
    with session_factory() as db:
        orders = {o["item_id"]: o for o in plans.get_order_plan(db, "SA-S6")["production_orders"]}
        assert (orders[factory["pcb"]]["status"], orders[factory["phone"]]["status"]) == ("RELEASED", "FIRM")
        phone_day = date.fromisoformat(orders[factory["phone"]]["start_day"])

    with session_factory() as db:  # the customer cancels (Sales publishes OrderCancelled)
        channel.publish(db, event_type="OrderCancelled", publisher="SALES", entity_type="sales_order",
                        entity_id="SA-S6", entity_version=2, correlation_id="SA-S6",
                        payload={"order_number": "SA-S6"})
        db.commit()
    pump()

    with session_factory() as db:
        plan = plans.get_order_plan(db, "SA-S6")
        statuses = {o["item_id"]: o["status"] for o in plan["production_orders"]}
        assert plan["status"] == "CANCELLED" and statuses == {factory["pcb"]: "RELEASED"}  # phone order cancelled
        case, chip = stock.stock_position(db, factory["case"]), stock.stock_position(db, factory["chip"])
        assert (D(case["on_hand"]), D(case["reserved"]), D(case["held"])) == (500, 0, 0)  # released exactly
        assert D(chip["reserved"]) == 200  # still needed by the released PCB order
        hours = workforce.free_worker_hours(db, "ASSEMBLY", phone_day, phone_day)[phone_day.isoformat()]
        assert D(hours) == 16  # both assemblers free again
        assert D(space.free_space(db, "FINISHED_GOODS", due, due)[due.isoformat()]) == 500  # no space kept
        assert planner.machine_free(db, "ASM", phone_day) == 8  # Planning's own machine-hours back

    run_day(session_factory, pump, client)  # the released PCB order runs; its output is free stock
    with session_factory() as db:
        pcb, chip = stock.stock_position(db, factory["pcb"]), stock.stock_position(db, factory["chip"])
        assert (D(pcb["on_hand"]), D(pcb["reserved"])) == (100, 0)
        assert (D(chip["on_hand"]), D(chip["reserved"])) == (800, 0)


def test_worker_absence_is_repaired_by_moving_the_work_to_another_day(session_factory, pump, factory):
    """S5. Due in 7 days, the PCBs are made on day 5 (outside the 2-day time fence). Both SMT workers are then reported
    absent on day 5: HR cannot cover it and reports the 6 hours AT_RISK. Planning moves the work to the nearest day
    with room (day 4) through a normal HR negotiation; HR releases exactly the old day; the order still ships on time."""
    start, client = factory["start"], factory["client"]
    due = start + timedelta(days=7)
    sent = request(client, "REQ-S5", 100, due, start)
    pump()
    confirm(session_factory, sent, "SA-S5", 100, due)
    pump()
    day5, day4 = start + timedelta(days=5), start + timedelta(days=4)
    with session_factory() as db:
        pcb_order = next(o for o in plans.get_order_plan(db, "SA-S5")["production_orders"]
                         if o["item_id"] == factory["pcb"])
        assert (pcb_order["status"], pcb_order["start_day"]) == ("FIRM", day5.isoformat())

    with session_factory() as db:  # the simulator reports both SMT workers absent on day 5
        hr_manager.record_absence(db, "ABS-S1", "S1", day5, day5)
        hr_manager.record_absence(db, "ABS-S2", "S2", day5, day5)
        db.commit()
    pump()

    with session_factory() as db:
        pcb_order = next(o for o in plans.get_order_plan(db, "SA-S5")["production_orders"]
                         if o["item_id"] == factory["pcb"])
        assert pcb_order["start_day"] == day4.isoformat()  # moved one day earlier, still before the phones
        free = workforce.free_worker_hours(db, "SMT", day4, day5)
        assert (D(free[day4.isoformat()]), D(free[day5.isoformat()])) == (10, 0)  # 16 - 6 on day 4; nobody on day 5
        assert (planner.machine_free(db, "SMT", day4), planner.machine_free(db, "SMT", day5)) == (2, 8)
        assert {c["status"] for c in workforce.commitments_for(db, pcb_order["id"])} == {"ACTIVE"}  # no longer at risk

    for _ in range(8):  # the repaired plan still delivers on the promised day
        run_day(session_factory, pump, client)
        with session_factory() as db:
            if plans.get_order_plan(db, "SA-S5")["status"] == "COMPLETED":
                break
    with session_factory() as db:
        assert plans.get_order_plan(db, "SA-S5")["status"] == "COMPLETED" and today(db) == due


def change_quantity(session_factory, order_number: str, quantity: int, version: int) -> None:
    with session_factory() as db:  # Sales publishes the customer's change
        channel.publish(db, event_type="OrderChangeRequested", publisher="SALES", entity_type="sales_order",
                        entity_id=order_number, entity_version=version, correlation_id=order_number,
                        payload={"order_number": order_number, "quantity": quantity})
        db.commit()


def test_order_change_is_handled_as_a_delta(session_factory, pump, factory):
    """S7 (QA-3, RD-8). 100 phones due in 7 days; +20 plans and secures only the extra 20 (two more production
    orders); then down to 60: the latest, smallest orders shrink first (the extra 20 go whole, the 100 become 60) and
    every owner releases exactly the difference."""
    start, client = factory["start"], factory["client"]
    due = start + timedelta(days=7)
    sent = request(client, "REQ-S7", 100, due, start)
    pump()
    confirm(session_factory, sent, "SA-S7", 100, due)
    pump()

    change_quantity(session_factory, "SA-S7", 120, 2)
    pump()
    with session_factory() as db:
        plan = plans.get_order_plan(db, "SA-S7")
        assert plan["committed_quantity"] == "120" and len(plan["production_orders"]) == 4
        assert D(stock.stock_position(db, factory["case"])["reserved"]) == 120
        assert D(stock.stock_position(db, factory["chip"])["reserved"]) == 240

    change_quantity(session_factory, "SA-S7", 60, 3)
    pump()
    day5, day6 = start + timedelta(days=5), start + timedelta(days=6)
    with session_factory() as db:
        plan = plans.get_order_plan(db, "SA-S7")
        assert plan["committed_quantity"] == "60"
        assert sorted((o["item_id"], o["quantity"]) for o in plan["production_orders"]) == sorted(
            [(factory["phone"], "60"), (factory["pcb"], "60")])
        assert D(stock.stock_position(db, factory["case"])["reserved"]) == 60
        assert D(stock.stock_position(db, factory["chip"])["reserved"]) == 120
        # hours: 100 phones = 1 + 5 h, 20 phones = 1 + 1 h; after the change 1 + 5 - 2 = 4 h on each work center
        assert (planner.machine_free(db, "ASM", day6), planner.machine_free(db, "SMT", day5)) == (4, 4)
        assert D(workforce.free_worker_hours(db, "ASSEMBLY", day6, day6)[day6.isoformat()]) == 12
        assert D(workforce.free_worker_hours(db, "SMT", day5, day5)[day5.isoformat()]) == 12
