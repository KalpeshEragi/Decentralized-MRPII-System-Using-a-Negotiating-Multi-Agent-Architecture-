"""One compact snapshot for the control panel, polled every second or two (FE-6, API-2). Read-only: agents' read
modules and infrastructure tables only (API-3). The timeline (`views.timeline`) is polled next to it with a cursor."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.events.models import Event
from app.hr_agent import reads as hr
from app.inventory_agent import reads as inventory
from app.models.core import Item
from app.negotiation.models import Session as NegotiationSession
from app.observability.models import LlmCall
from app.planning_agent import reads as planning
from app.simulation.clock import get_clock
from app.simulation.models import Run
from app.simulation import runner
from app.simulation.runner import waiting
from app.simulation.settings import setting
from app.warehouse_agent import reads as warehouse

ACTIVE = ("RELEASED", "STARTED", "FIRM")


def live(db: Session) -> dict:
    clock = get_clock(db)
    day = clock.current_day
    items = {str(i.id): i for i in db.scalars(select(Item).where(Item.is_active.is_(True)).order_by(Item.sku))}
    balances = inventory.balances(db)  # one query for every item
    empty = {"on_hand": "0", "reserved": "0", "held": "0"}
    stock = [{"item_id": item_id, "sku": item.sku, "name": item.name, "type": str(item.item_type.value),
              **{k: balances.get(item_id, empty)[k] for k in ("on_hand", "reserved", "held")}}
             for item_id, item in items.items()]
    demands = planning.demands(db, limit=1000)
    shipped = {e.payload["order_ref"]: e.payload.get("date") for e in db.scalars(
        select(Event).where(Event.event_type == "ShipmentDispatched"))}
    completed = [d for d in demands if d["status"] == "COMPLETED"]
    on_time = sum(1 for d in completed if d["committed_day"] and shipped.get(d["demand_id"], "9999") <= d["committed_day"])
    orders = planning.production_orders(db)
    run = db.scalar(select(Run).where(Run.status == "RUNNING").order_by(Run.id.desc()))
    return {
        "clock": {"day": day.isoformat(), "status": clock.status, "waiting": waiting(db),
                  "pause_reason": runner.pause_reason},
        "ai_enabled": bool(int(setting(db, "ai_enabled"))),
        "run": {"id": run.id, "scenario": run.scenario, "start_day": run.start_day.isoformat()} if run else None,
        "kpis": {
            "stock_on_hand": str(sum((Decimal(s["on_hand"]) for s in stock), Decimal(0))),
            "orders_open": sum(1 for d in demands if d["status"] in ("COMMITTED", "PLANNING", "ANSWERED")),
            "orders_completed": len(completed),
            "on_time_percent": round(100 * on_time / len(completed), 1) if completed else None,
            "plan_at_risk": db.scalar(select(func.count()).select_from(Event).where(
                Event.event_type == "PlanAtRisk")) or 0,
            "ai_calls": db.scalar(select(func.count()).select_from(LlmCall)) or 0,
        },
        "stock": stock,
        "zones": warehouse.zones(db),
        "workers": hr.workers(db, day),
        "lines": [_line(db, wc, day, orders, items) for wc in planning.work_centers(db)],
        "docks": {
            "inbound": [{**d, "sku": items[d["item_id"]].sku if d["item_id"] in items else None}
                        for d in warehouse.deliveries_on(db, day) + warehouse.deliveries_on(db, day + timedelta(days=1))],
            "outbound": [{**s, "sku": items[s["item_id"]].sku if s["item_id"] in items else None}
                         for s in planning.shipments_due(db, day + timedelta(days=1))],
        },
        "orders": [{k: d[k] for k in ("demand_id", "order_number", "item_id", "quantity", "status", "committed_day",
                                      "requested_day")} | {"sku": items[d["item_id"]].sku if d["item_id"] in items else None}
                   for d in demands[:50]],
        "negotiations_open": [
            {"session_id": str(s.id), "case_id": s.case_id, "starter": s.starter, "owner": s.owner,
             "resource_type": s.resource_type, "status": s.status, "round": s.round}
            for s in db.scalars(select(NegotiationSession).where(NegotiationSession.status.in_(
                ("NEGOTIATING", "AGREEMENT_PROPOSED"))).order_by(NegotiationSession.created_at).limit(100))],
    }


def _line(db: Session, work_center: str, day: date, orders: list[dict], items: dict) -> dict:
    """A production line today: free machine-hours and the production orders that have work on it today."""
    today_text = day.isoformat()
    running = [{"id": o["id"], "sku": items[o["item_id"]].sku if o["item_id"] in items else None,
                "quantity": o["quantity"], "status": o["status"]}
               for o in orders if o["status"] in ACTIVE and work_center in o["work_centers"]
               and o["start_day"] <= today_text <= o["end_day"]]
    return {"work_center": work_center, "machine_hours_free": planning.machine_hours_free(db, work_center, day),
            "orders_today": running}
