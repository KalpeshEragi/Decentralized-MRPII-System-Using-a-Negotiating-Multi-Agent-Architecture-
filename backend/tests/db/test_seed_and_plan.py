"""Migrations, X1 seed/reset and the persisted plan (needs TEST_DATABASE_URL)."""

import uuid
from datetime import date

from sqlalchemy import func, select, text

from app.data import x1_fixture as x1
from app.data.seed_data import reset_and_seed
from app.models import Base
from app.models import audit, inventory, planning, sales
from app.services import inventory_service, planning_service


def net_by_name(plan):
    return {x1.component_name(r.item_id): int(r.net_requirement) for r in plan.requirements}


def test_all_25_percent_tables_exist_and_no_purchase_order_tables(db):
    tables = {(t.schema, t.name) for t in Base.metadata.sorted_tables}
    assert len(tables) == 24
    present = {row[0] + "." + row[1] for row in db.execute(text(
        "select table_schema, table_name from information_schema.tables "
        "where table_schema in ('core','sales','inventory','planning','purchasing','agent','negotiation','simulation','audit')"))}
    assert {f"{s}.{n}" for s, n in tables} <= present
    assert not any("purchase_order" in name for name in present)


def test_seed_matches_the_fixture(db):
    positions = inventory_service.get_positions(db, x1.COMPONENT_IDS.values())
    available = {x1.component_name(i): int(p.available_quantity) for i, p in positions.items()}
    assert available == {"Display": 500, "Main Board": 1000, "Battery": 400, "Camera Module": 2500, "Speaker": 1300, "Charging Port": 1350}
    assert db.scalar(select(func.count()).select_from(sales.CustomerOrder)) == 1
    assert inventory_service.get_position(db, x1.PRODUCT_ID).available_quantity == 0  # no finished goods in the baseline


def test_baseline_plan_is_persisted_and_readable(db, order_id):
    plan = planning_service.run_plan(db, order_id)
    stored = planning_service.get_plan(db, order_id)
    assert stored.model_dump(mode="json") == plan.model_dump(mode="json")
    assert (stored.mps[0].planned_quantity, stored.mps[0].planned_start, stored.mps[0].planned_end) == (1000, date(2026, 10, 26), date(2026, 10, 31))
    assert net_by_name(stored) == {"Display": 500, "Main Board": 0, "Battery": 600, "Camera Module": 0, "Speaker": 0, "Charging Port": 0}
    assert sorted((x1.component_name(s.item_id), int(s.shortage_quantity)) for s in stored.shortages) == [("Battery", 600), ("Display", 500)]
    assert db.scalar(select(func.count()).select_from(planning.MpsPlan)) == 1
    assert db.scalar(select(func.count()).select_from(planning.MrpRequirement)) == 6
    types = {row[0] for row in db.execute(select(audit.DecisionAudit.decision_type))}
    assert {"PLAN_CREATED", "SHORTAGE_DETECTED"} <= types


def test_replanning_replaces_rows_instead_of_duplicating(db, order_id):
    planning_service.run_plan(db, order_id)
    planning_service.run_plan(db, order_id)
    assert db.scalar(select(func.count()).select_from(planning.MpsPlan)) == 1
    assert db.scalar(select(func.count()).select_from(planning.MrpRequirement)) == 6


def test_finished_goods_reduce_the_persisted_mps(db, order_id):
    balance = inventory.InventoryBalance(
        item_id=uuid.UUID(x1.PRODUCT_ID), warehouse_id=db.scalar(select(inventory.Warehouse.id)),
        on_hand=300, reserved=0, safety_stock=0,
    )
    db.add(balance)
    db.commit()
    plan = planning_service.run_plan(db, order_id)
    assert plan.finished_goods[0].net_production_requirement == 700 and plan.mps[0].planned_quantity == 700


def test_reset_returns_to_the_baseline(db, order_id):
    planning_service.run_plan(db, order_id)
    reset_and_seed(db)
    assert db.scalar(select(func.count()).select_from(planning.MpsPlan)) == 0
    assert db.scalar(select(func.count()).select_from(audit.DecisionAudit)) == 0
    assert db.scalar(select(func.count()).select_from(sales.CustomerOrder)) == 1
