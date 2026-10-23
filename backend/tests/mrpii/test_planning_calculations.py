"""Step 2 pure calculations, checked against the numbers written in the approved docs:
the research report's phone example (§4.2) for multi-level MRP + capacity, quantity_accounting.md §5.3 for ATP and a
supplier delay, and planning_agent/2 §6 for the fixed ranking."""

from datetime import date, timedelta
from decimal import Decimal as D

from app.mrpii.atp import Dated, atp, earliest_full_date, uncovered_promises
from app.mrpii.hours import RoutingStep, machine_hours, schedule_backward
from app.mrpii.multilevel import BUY, MAKE, MULTIPLE, BomLine, Demand, ItemData, run_mrp
from app.mrpii.ranking import Alternative, check_ai_choice, rank

DAY0 = date(2026, 11, 1)


def day(n: int) -> date:
    return DAY0 + timedelta(days=n)


ROUTINGS = {
    "P": [RoutingStep(1, "ASM", "ASSEMBLY", 1, D("1"), D("0.05"))],
    "MB": [RoutingStep(1, "SMT", "SMT", 1, D("0.5"), D("0.02"))],
}
MACHINE = {"ASM": D(16), "SMT": D(8)}
WORKERS = {"ASSEMBLY": D(16), "SMT": D(8)}


def production_start(absent_assembly_hours: dict[date, D] | None = None):
    absent = absent_assembly_hours or {}

    def start(item_id, quantity, need_day):
        plan = schedule_backward(ROUTINGS[item_id], quantity, need_day, day(1),
                                 lambda wc, d: MACHINE[wc],
                                 lambda skill, d: WORKERS[skill] - (absent.get(d, D(0)) if skill == "ASSEMBLY" else 0))
        return plan[0].start_day if plan else None

    return start


ITEMS = {
    "P": ItemData("P", MAKE, on_hand=D(50)),
    "MB": ItemData("MB", MAKE, on_hand=D(20)),
    "BAT": ItemData("BAT", BUY, on_hand=D(300), safety_stock=D(50), incoming=(Dated(day(6), D(200)),),
                    promises=(Dated(day(4), D(100), "SO-0"),), lot_rule=MULTIPLE, lot_size=D(100), lead_time_days=5),
    "CASE": ItemData("CASE", BUY, on_hand=D(1000), safety_stock=D(100), lead_time_days=3),
    "PCB": ItemData("PCB", BUY, on_hand=D(100), lead_time_days=4),
    "CHIP": ItemData("CHIP", BUY, on_hand=D(300), safety_stock=D(100), lot_rule=MULTIPLE, lot_size=D(250),
                     lead_time_days=7),
}
BOM = [BomLine("P", "MB", D(1)), BomLine("P", "BAT", D(1)), BomLine("P", "CASE", D(1)),
       BomLine("MB", "PCB", D(1)), BomLine("MB", "CHIP", D(2))]


def test_research_phone_example_multi_level_mrp_with_capacity():
    assert machine_hours(ROUTINGS["MB"][0], D(430)) == D("9.25")  # 9.1 h rounded up (QA-5)
    result = run_mrp([Demand("P", D(500), day(15), "SO-1")], ITEMS, BOM, production_start())

    orders = {o.item_id: (o.quantity, o.need_day, o.release_day) for o in result.planned_orders}
    assert orders == {
        "P": (D(450), day(15), day(13)),     # 50 finished phones used; 23.5 h on ASM over days 13-14
        "MB": (D(430), day(13), day(11)),    # 9.25 h > 8 h/day: spread over days 11-12
        "BAT": (D(100), day(13), day(8)),    # keeps 50 safety stock; multiple 100; lead time 5
        "PCB": (D(330), day(11), day(7)),    # lot-for-lot; lead time 4
        "CHIP": (D(750), day(11), day(4)),   # net 660 rounded up to a multiple of 250; lead time 7
    }                                        # CASE: 1000 - 450 = 550 >= 100, no order
    assert result.records["BAT"].final_pab == D(50) and result.records["CHIP"].final_pab == D(190)
    assert not result.unschedulable

    # quantity_accounting.md §7.3: one assembly worker absent on day 13 still fits days 13-14 (8 h + 15.5 h) ...
    one_day = run_mrp([Demand("P", D(500), day(15), "SO-1")], ITEMS, BOM, production_start({day(13): D(8)}))
    assert {o.item_id: o.release_day for o in one_day.planned_orders}["P"] == day(13)
    # ... absent both days does not: production has to start a day earlier.
    two_days = run_mrp([Demand("P", D(500), day(15), "SO-1")], ITEMS, BOM,
                       production_start({day(13): D(8), day(14): D(8)}))
    assert {o.item_id: o.release_day for o in two_days.planned_orders}["P"] == day(12)


def test_atp_by_date_and_supplier_delay():
    # quantity_accounting.md §5.3: on hand 1000, 800 promised for day 5, 2000 arriving day 10.
    promises = [Dated(day(5), D(800), "R1", 1)]
    incoming = [Dated(day(10), D(2000))]
    assert atp(day(3), D(1000), incoming, promises) == D(200)
    assert atp(day(12), D(1000), incoming, promises) == D(2200)
    assert earliest_full_date(D(1500), day(3), 60, D(1000), incoming, promises) == day(10)

    # A promise of 1500 for day 12 is made; then the delivery slips to day 15.
    promises.append(Dated(day(12), D(1500), "R2", 2))
    assert uncovered_promises(D(1000), incoming, promises) == []
    delayed = [Dated(day(15), D(2000))]
    assert uncovered_promises(D(1000), delayed, promises) == [("R2", D(1300))]


def _alt(key, **changes) -> Alternative:
    base = dict(quantity=D(500), target_quantity=D(500), completion_date=day(14), hard_ok=True,
                touches_protected=False, firm_changes=0, full_on_target=True, days_late=0, orders_moved=0,
                days_moved=0, safety_stock_used=D(0), extra_worker_hours=D(0), negotiations=1)
    return Alternative(key=key, **{**base, **changes})


def test_fixed_ranking_filters_orders_and_breaks_ties():
    alternatives = [
        _alt("a-overtime", extra_worker_hours=D(2)),
        _alt("b-late", full_on_target=False, days_late=2),
        _alt("c-moves-another-order", orders_moved=1, days_moved=1),
        _alt("d-firm-change", firm_changes=1),
        _alt("e-breaks-constraint", hard_ok=False),
        _alt("f-touches-released", touches_protected=True),
        _alt("g-fewer-pieces", quantity=D(400)),
        _alt("h-safety-stock", safety_stock_used=D(10)),
        _alt("i-overtime-twin", extra_worker_hours=D(2)),
    ]
    allowed, rejected = rank(alternatives)
    # Step 5 compares safety stock before extra worker-hours; the two overtime twins tie and fall back to the key.
    assert [a.key for a in allowed] == ["a-overtime", "i-overtime-twin", "h-safety-stock", "c-moves-another-order",
                                        "b-late", "d-firm-change"]
    assert rejected == {"e-breaks-constraint": "HARD_CONSTRAINT", "f-touches-released": "TOUCHES_PROTECTED_COMMITMENT",
                        "g-fewer-pieces": "LESS_THAN_TARGET_QUANTITY"}
    assert check_ai_choice("b-late", alternatives).key == "b-late"                 # a valid AI choice is kept
    assert check_ai_choice("f-touches-released", alternatives).key == "a-overtime"  # an invalid one is overruled


def test_a_request_never_plans_work_for_other_orders_promises():
    """MRP also plans an order that only covers other orders' reservations (source "promises"). It has no parent in
    this request, so it and its children are left out; before, it became a production order with an unknown parent and
    Planning crashed on every message of that case (KeyError 'promises')."""
    from app.mrpii.multilevel import run_mrp
    from app.planning_agent.plan import DEMAND, for_this_request

    items = {
        "PHONE": ItemData("PHONE", MAKE, on_hand=D(0)),
        # 100 boards in stock, but 150 are already promised to other orders on day 2: a 50 shortfall not ours
        "MB": ItemData("MB", MAKE, on_hand=D(100), promises=(Dated(day(2), D(150)),)),
        "CHIP": ItemData("CHIP", BUY, on_hand=D(0)),
    }
    bom = [BomLine("PHONE", "MB", D(1)), BomLine("MB", "CHIP", D(2))]
    result = run_mrp([Demand("PHONE", D(10), day(9), DEMAND)], items, bom, lambda item, qty, need: need)
    assert any(o.source == "promises" for o in result.planned_orders)  # MRP did plan the others' shortfall

    kept = for_this_request(result.planned_orders)
    assert all(o.source == DEMAND or o.source.startswith("planned:") for o in kept)
    assert sorted((o.item_id, o.quantity) for o in kept) == [("CHIP", D(20)), ("MB", D(10)), ("PHONE", D(10))]
