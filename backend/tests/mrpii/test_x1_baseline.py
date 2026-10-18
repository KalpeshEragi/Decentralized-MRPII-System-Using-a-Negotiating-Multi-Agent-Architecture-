"""X1 baseline and scenario numbers from app/data/x1_fixture.py."""

from datetime import date
from decimal import Decimal

from app.data import x1_fixture as x1
from app.mrpii.plan import plan_order
from app.mrpii.suppliers import covers_alone, is_split_feasible, is_usable
from app.schemas.domain import InventoryPosition, PlanStatus, ProductionParameters


def _net(plan):
    return {x1.component_name(r.item_id): int(r.net_requirement) for r in plan.requirements}


def test_baseline_plan():
    plan = plan_order(x1.x1_order(), x1.x1_bom(), x1.PRODUCTION, x1.x1_inventory())
    assert (plan.mps[0].planned_start, plan.mps[0].planned_end) == (date(2026, 10, 26), date(2026, 10, 31))
    assert plan.finished_goods[0].net_production_requirement == 1000 and plan.mps[0].planned_quantity == 1000
    assert plan.capacity_checks[0].required_days == 4 and plan.capacity_checks[0].feasible
    assert _net(plan) == {
        "Display": 500, "Main Board": 0, "Battery": 600, "Camera Module": 0, "Speaker": 0, "Charging Port": 0,
    }
    assert plan.status == PlanStatus.SHORTAGE
    assert sorted(int(s.shortage_quantity) for s in plan.shortages) == [500, 600]


def test_finished_goods_reduce_production_before_capacity():
    """100 ordered, 50 finished goods available, 60/day, 4-day lead time: produce 50, 1 day, capacity passes."""
    production = {x1.PRODUCT_ID: ProductionParameters(item_id=x1.PRODUCT_ID, production_lead_time_days=4, capacity_per_day=60)}
    stock = {x1.PRODUCT_ID: InventoryPosition(item_id=x1.PRODUCT_ID, on_hand=50, reserved=0, safety_stock=0)}
    plan = plan_order(x1.x1_order(quantity=100), x1.x1_bom(), production, x1.x1_inventory(), finished_goods=stock)
    netting = plan.finished_goods[0]
    assert (netting.available_finished_goods, netting.net_production_requirement) == (50, 50)
    assert plan.mps[0].planned_quantity == 50
    assert plan.capacity_checks[0].required_days == 1 and plan.capacity_checks[0].feasible
    assert _net(plan)["Display"] == 0  # components are netted for 50 units, not 100


def test_finished_goods_cover_whole_order_means_no_mps():
    stock = {x1.PRODUCT_ID: InventoryPosition(item_id=x1.PRODUCT_ID, on_hand=150, reserved=0, safety_stock=50)}
    plan = plan_order(x1.x1_order(quantity=100), x1.x1_bom(), x1.PRODUCTION, x1.x1_inventory(), finished_goods=stock)
    assert plan.mps == [] and plan.requirements == [] and plan.status == PlanStatus.VALIDATED


def test_s3_demand_1300():
    plan = plan_order(x1.x1_order(quantity=1300), x1.x1_bom(), x1.PRODUCTION, x1.x1_inventory())
    assert plan.capacity_checks[0].required_days == 5 and plan.capacity_checks[0].feasible
    assert _net(plan) == {
        "Display": 800, "Main Board": 300, "Battery": 900, "Camera Module": 100, "Speaker": 0, "Charging Port": 0,
    }


def test_s6_speaker_reservation():
    plan = plan_order(x1.x1_order(), x1.x1_bom(), x1.PRODUCTION, x1.x1_inventory(reserved={"Speaker": 500}))
    assert _net(plan)["Speaker"] == 100


def test_s7_due_date_20_days():
    plan = plan_order(x1.x1_order(due_date=date(2026, 10, 21)), x1.x1_bom(), x1.PRODUCTION, x1.x1_inventory())
    assert plan.mps[0].planned_start == date(2026, 10, 16)


def test_supplier_feasibility_baseline():
    by_name = {s.supplier: s for s in x1.x1_suppliers()}
    p, r = x1.PLANNING_DATE, date(2026, 10, 26)
    assert [is_usable(by_name[n], p, r) for n in ("Alpha Displays", "Beta Optics", "Gamma Screens")] == [True, True, False]
    assert covers_alone(by_name["Alpha Displays"], p, r, Decimal(500)) and covers_alone(by_name["Beta Optics"], p, r, Decimal(500))
    assert covers_alone(by_name["Volt Power"], p, r, Decimal(600)) and covers_alone(by_name["Cell Works"], p, r, Decimal(600))


def test_s2_and_s4_supplier_changes():
    p, r = x1.PLANNING_DATE, date(2026, 10, 26)
    volt_late = {s.supplier: s for s in x1.x1_suppliers({"Volt Power": {"lead_time_days": 27}})}
    assert not is_usable(volt_late["Volt Power"], p, r)
    alpha_small = {s.supplier: s for s in x1.x1_suppliers({"Alpha Displays": {"available_qty": 300}})}
    assert not covers_alone(alpha_small["Alpha Displays"], p, r, Decimal(500))
    assert is_split_feasible([(alpha_small["Alpha Displays"], Decimal(200)), (alpha_small["Beta Optics"], Decimal(300))], p, r, Decimal(500))
    assert not is_split_feasible([(alpha_small["Alpha Displays"], Decimal(300)), (alpha_small["Beta Optics"], Decimal(200))], p, r, Decimal(500))
