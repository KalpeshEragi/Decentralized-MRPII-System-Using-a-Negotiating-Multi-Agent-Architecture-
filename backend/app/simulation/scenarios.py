"""Scenarios and runs (demo.md §8, §12, DM-4).

A scenario = a starting state + factory settings + triggers on days counted from the run's first day + a seed. Starting
it restores the state (Factory A is built first when it does not exist yet), applies the settings, schedules the
triggers and opens a run; Play or Next day then moves time. Finishing a run saves its report (metrics, the final
factory state and the timeline), which is kept when the run is later reset.

The numbers are starting values (DM-O3): tune them after watching the runs.
"""

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.events.models import Event
from app.observability.models import LlmCall
from app.simulation import factory_a, states, triggers
from app.simulation.clock import today
from app.simulation.models import Run, RunReport, Snapshot
from app.simulation.settings import update_settings

PHONES = {"product_sku": "PHONE-P"}
TABLETS = {"product_sku": "TABLET-T"}

# name: description, settings, [(day, trigger kind, params)] — day 1 = the first simulated day of the run
SCENARIOS: dict[str, tuple[str, dict, list[tuple[int, str, dict]]]] = {
    "MANUAL": ("Manual demo: an empty factory on day 1; you add each order yourself (no simulated customers)",
               {"customer_orders_per_day": 0}, []),
    "ONE": ("One order end to end (SIM, DC-1): 150 tablets in 12 days. The owners quote; Planning takes what stock "
            "covers, makes main boards and tablets in batches, and buys the batteries, boards and chips stock cannot "
            "cover — then storage and shipment. Watch it hour by hour with Next hour",
            {}, [(1, "NEW_ORDER", {**TABLETS, "quantity": 150, "lead_days": 12})]),
    "S1": ("One normal order: request -> options -> confirmation -> commitment -> production -> shipment", {},
           [(1, "NEW_ORDER", {**PHONES, "quantity": 100, "lead_days": 7})]),
    "S2": ("Supplier delay: a big order needs chips bought; the supplier then delivers 3 days late", {},
           [(1, "NEW_ORDER", {**PHONES, "quantity": 400, "lead_days": 14}),
            (3, "SUPPLIER_DELAY", {"item_sku": "CHIP", "days": 3})]),
    "S3": ("Material shortage: a big order needs batteries and chips bought through Purchasing", {},
           [(1, "NEW_ORDER", {**PHONES, "quantity": 400, "lead_days": 14})]),
    "S4": ("Receiving limit: the dock takes 600 pieces a day; deliveries are spread and each slot is agreed first",
           {}, [(1, "WAREHOUSE_CAPACITY", {"resource": "RECEIVING", "units": 600}),
                (1, "NEW_ORDER", {**PHONES, "quantity": 400, "lead_days": 14})]),
    "S5": ("Worker absence: two assemblers are absent while the order is planned", {},
           [(1, "NEW_ORDER", {**PHONES, "quantity": 300, "lead_days": 10}),
            (2, "WORKER_ABSENT", {"worker": "A1", "first_day_offset": 5, "last_day_offset": 8}),
            (2, "WORKER_ABSENT", {"worker": "A2", "first_day_offset": 5, "last_day_offset": 8})]),
    "S6": ("Cancellation: the customer cancels the order two days after confirming it", {},
           [(1, "NEW_ORDER", {**PHONES, "quantity": 200, "lead_days": 8}),
            (3, "CANCEL_ORDER", {"order_number": "latest"})]),
    "S7": ("Order change: the customer first adds 50, then goes down to 120", {},
           [(1, "NEW_ORDER", {**PHONES, "quantity": 200, "lead_days": 10}),
            (2, "CHANGE_ORDER", {"order_number": "latest", "quantity": 250}),
            (3, "CHANGE_ORDER", {"order_number": "latest", "quantity": 120})]),
    "S8": ("Competing orders: phones and tablets need the same main boards and assemblers on the same days", {},
           [(1, "NEW_ORDER", {**PHONES, "quantity": 150, "lead_days": 6}),
            (1, "NEW_ORDER", {**TABLETS, "quantity": 100, "lead_days": 6}),
            (1, "NEW_ORDER", {**PHONES, "quantity": 120, "lead_days": 6}),
            (1, "NEW_ORDER", {**TABLETS, "quantity": 80, "lead_days": 6})]),
    "LOAD-10": ("Load: 10 simulated customers on day 1 (structured)",
                {"customer_orders_per_day": 10, "customer_order_days": 1}, []),
    "LOAD-20": ("Load: 20 simulated customers on day 1 (structured)",
                {"customer_orders_per_day": 20, "customer_order_days": 1}, []),
    "LOAD-100": ("Load: 100 simulated customers, 20 a day for 5 days (structured)",
                 {"customer_orders_per_day": 20, "customer_order_days": 5}, []),
}


# Load runs start with enough finished phones and tablets for about LOAD_COVER of the expected orders, so most orders
# can be promised from stock and the rest go through production, purchasing or a later-date option. Expected demand
# = orders x the customers' mean quantity (settings: 50..200 -> 125), split evenly over the two products. Space for
# finished goods is that stock plus half again. The default state "factory-a" (S1-S8, MANUAL) is unchanged.
LOAD_COVER = 0.75
LOAD_ORDERS = {"LOAD-10": 10, "LOAD-20": 20, "LOAD-100": 100}
MEAN_ORDER_QUANTITY = 125


def load_stock(orders: int) -> tuple[dict[str, int], int]:
    """Starting finished-goods stock per product and FINISHED_GOODS capacity for a load run of `orders` orders."""
    each = math.ceil(orders * MEAN_ORDER_QUANTITY / 2 * LOAD_COVER)
    stock = {"PHONE-P": each, "TABLET-T": each}
    space = sum(int(factory_a.ITEMS[sku][3]) * n for sku, n in stock.items())  # phone 1, tablet 2 space units
    return stock, math.ceil(space * 1.5 / 100) * 100


def _state_for(name: str) -> tuple[str, str]:
    if name in LOAD_ORDERS:
        stock = load_stock(LOAD_ORDERS[name])[0]
        return f"factory-a-{name.lower()}", (f"Factory A with {stock['PHONE-P']} phones and {stock['TABLET-T']} tablets "
                                             f"in stock (~{int(LOAD_COVER * 100)}% of {name}'s expected orders)")
    return "factory-a", "Default demo factory (demo.md §4.1)"


def _ensure_state(db: Session, state: str, description: str, name: str) -> None:
    """Build and save a starting state the first time it is used (configuring, never triggering)."""
    if db.get(Snapshot, state) is not None:
        return
    states.clear(db)
    if name in LOAD_ORDERS:
        stock, space = load_stock(LOAD_ORDERS[name])
        factory_a.build(db, finished_stock=stock, finished_space=space)
    else:
        factory_a.build(db)
    db.flush()
    states.save(db, state, description)


def listing() -> list[dict]:
    return [{"name": name, "description": description, "settings": settings,
             "triggers": [{"day": day, "kind": kind, "params": params} for day, kind, params in plan]}
            for name, (description, settings, plan) in SCENARIOS.items()]


def start(db: Session, name: str, seed: int = 1) -> dict:
    """Restore the scenario's starting state, apply its settings and seed, schedule its triggers, open a run."""
    if name not in SCENARIOS:
        raise AppError(ErrorCode.NOT_FOUND, f"no scenario {name}")
    if db.scalar(select(Run.id).where(Run.status == "RUNNING")) is not None:
        raise AppError(ErrorCode.CONFLICT, "a run is still running: finish it first")
    description, settings, plan = SCENARIOS[name]
    state, state_description = _state_for(name)
    _ensure_state(db, state, state_description, name)
    restored = states.restore(db, state)
    update_settings(db, {**settings, "customer_seed": seed})
    from app.simulation.clock import get_clock, shift

    get_clock(db, lock=True).current_hour = shift(db)[1]  # the start day is over: the first hour starts day 1
    first_day = today(db) + timedelta(days=1)
    for day, kind, params in plan:
        triggers.add(db, kind, params, first_day + timedelta(days=day - 1))
    run = Run(scenario=name, seed=seed, state=state, start_day=today(db), status="RUNNING")
    db.add(run)
    db.flush()
    return {"run_id": run.id, "scenario": name, "description": description, "start_day": run.start_day.isoformat(),
            "reconcile": restored["reconcile"], "scheduled_triggers": len(plan)}


def finish(db: Session, run_id: int) -> dict:
    """Close the run and save its report (DM-4). The run's data stays until a state is restored."""
    run = db.get(Run, run_id, with_for_update=True)
    if run is None:
        raise AppError(ErrorCode.NOT_FOUND, "no such run")
    if run.status != "RUNNING":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"the run is {run.status}")
    run.status, run.end_day, run.finished_at = "FINISHED", today(db), datetime.now(timezone.utc)
    report = build_report(db, run)
    db.merge(RunReport(run_id=run.id, report=report))
    return report


def build_report(db: Session, run: Run) -> dict:
    """Metrics (system_design §10, first set), the final factory state and the timeline of the run."""
    from app.observer import metrics, views
    from app.planning_agent import reads as planning

    demands = planning.demands(db, limit=10000)
    shipped_on = {e.payload["order_ref"]: e.payload.get("date") for e in db.scalars(
        select(Event).where(Event.event_type == "ShipmentDispatched").order_by(Event.seq))}
    completed = [d for d in demands if d["status"] == "COMPLETED"]
    on_time = [d for d in completed if shipped_on.get(d["demand_id"]) and d["committed_day"]
               and shipped_on[d["demand_id"]] <= d["committed_day"]]
    counts = dict(db.execute(select(Event.event_type, func.count()).group_by(Event.event_type)).all())
    ai_calls = dict(db.execute(select(LlmCall.outcome, func.count()).group_by(LlmCall.outcome)).all())
    return {
        "run": {"id": run.id, "scenario": run.scenario, "seed": run.seed, "state": run.state,
                "start_day": run.start_day.isoformat(), "end_day": run.end_day.isoformat() if run.end_day else None},
        "metrics": {
            "orders": len(demands),
            "orders_by_status": _count(d["status"] for d in demands),
            "completed": len(completed),
            "completed_on_time": len(on_time),
            "plan_at_risk_events": counts.get("PlanAtRisk", 0),
            "events_by_type": counts,
            "ai_calls_by_outcome": ai_calls,
        },
        "orders": demands,
        "triggers": [triggers.view(t) for t in db.scalars(select(triggers.TriggerLog).order_by(triggers.TriggerLog.id))],
        "measurements": metrics.measurements(db),
        "final_factory_state": views.factory_state(db, today(db)),
        "timeline": _whole_timeline(db),
    }


def _whole_timeline(db: Session, pages: int = 100) -> list[dict]:
    """Every timeline item of the run, page by page through the observer's cursor."""
    from app.observer import views

    items, after = [], None
    for _ in range(pages):
        page = views.timeline(db, datetime.fromisoformat(after) if after else None)
        if not page["items"]:
            break
        items += page["items"]
        after = page["next"]
    return items


def _count(values) -> dict[str, int]:
    found: dict[str, int] = {}
    for value in values:
        found[value] = found.get(value, 0) + 1
    return found


def report_of(db: Session, run_id: int) -> dict:
    row = db.get(RunReport, run_id)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "no report for this run (is it finished?)")
    return row.report


def runs(db: Session) -> list[dict]:
    return [{"id": r.id, "scenario": r.scenario, "seed": r.seed, "status": r.status,
             "start_day": r.start_day.isoformat(), "end_day": r.end_day.isoformat() if r.end_day else None}
            for r in db.scalars(select(Run).order_by(Run.id.desc()))]
