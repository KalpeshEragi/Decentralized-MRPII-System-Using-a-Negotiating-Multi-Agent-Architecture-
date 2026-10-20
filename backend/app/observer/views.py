"""The observer (backend_api.md §7, API-3): read-only views for the demo frontend. It decides nothing and writes
nothing; it only composes what already exists, through the agents' read modules (IB-2) and the infrastructure tables
(events, negotiation, simulation, observability)."""

import uuid
from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import work_runner
from app.events.models import Event
from app.hr_agent import reads as hr
from app.inventory_agent import reads as inventory
from app.models.core import Item
from app.negotiation.models import Message, Session as NegotiationSession
from app.observability.models import LlmCall
from app.planning_agent import reads as planning
from app.sales_agent import reads as sales
from app.simulation.models import TriggerLog
from app.warehouse_agent import reads as warehouse

TIMELINE_LIMIT = 200


# -- orders ---------------------------------------------------------------------------------------------------------------


def orders(db: Session) -> list[dict]:
    """Every order Planning knows, with where Sales and production stand."""
    found = []
    for demand in planning.demands(db):
        plan = planning.get_order_plan(db, demand["demand_id"])
        found.append({**demand, "sales": sales.inquiry_status(db, demand["sales_inquiry_id"]),
                      "production": [{"id": o["id"], "item_id": o["item_id"], "quantity": o["quantity"],
                                      "status": o["status"], "start_day": o["start_day"], "end_day": o["end_day"]}
                                     for o in plan["production_orders"]]})
    return found


def order_story(db: Session, order_ref: str) -> dict | None:
    """One order's whole story: Sales, the plan, what every owner holds or committed for it, its negotiations and
    its events (oldest first). `order_ref` = Planning's demand id, the request ref or the Sales order number."""
    plan = planning.get_order_plan(db, order_ref)
    if plan is None:
        return None
    demand_id = plan["demand_id"]
    orders_ = [o["id"] for o in plan["production_orders"]]
    cases = planning.cases_for(db, demand_id)
    session_ids = [uuid.UUID(s) for c in cases for s in c["sessions"]]
    refs = {demand_id, plan["request_ref"], *(orders_), *(c["case_id"] for c in cases)}
    if plan.get("order_number"):
        refs.add(plan["order_number"])
    sessions = db.scalars(select(NegotiationSession).where(NegotiationSession.id.in_(session_ids))).all() \
        if session_ids else []
    events = db.scalars(select(Event).where(or_(Event.correlation_id.in_(refs), Event.entity_id.in_(refs)))
                        .order_by(Event.seq)).all()
    return {
        "plan": plan,
        "sales": sales.inquiry_status(db, plan["sales_inquiry_id"]),
        "owners": {
            "inventory": [r for ref in [demand_id, *orders_] for r in inventory.reservations_for(db, ref)],
            "hr": [{**c, "production_order_id": ref} for ref in orders_ for c in hr.commitments_for(db, ref)],
            "warehouse": warehouse.commitments_for(db, demand_id),
        },
        "negotiations": [{"session_id": str(s.id), "case_id": s.case_id, "starter": s.starter, "owner": s.owner,
                          "resource_type": s.resource_type, "resource_ref": s.resource_ref, "status": s.status,
                          "agreed_terms": s.agreed_terms, "last_reason_code": s.last_reason_code} for s in sessions],
        "events": [_event(e) for e in events],
    }


# -- timeline -------------------------------------------------------------------------------------------------------------


def timeline(db: Session, after: datetime | None = None, case_id: str | None = None) -> dict:
    """One stream in time order: events, negotiation messages, triggers, AI calls and failed work. Poll with the
    returned `next` cursor (API-2)."""
    items = []
    query = select(Event).order_by(Event.published_at)
    if after:
        query = query.where(Event.published_at > after)
    if case_id:
        query = query.where(Event.correlation_id == case_id)
    items += [{"time": e.published_at, "source": "event", **_event(e)} for e in db.scalars(query.limit(TIMELINE_LIMIT))]

    query = select(Message).order_by(Message.created_at)
    if after:
        query = query.where(Message.created_at > after)
    for m in db.scalars(query.limit(TIMELINE_LIMIT)):
        envelope = m.envelope
        if case_id and envelope.get("case_id") != case_id:
            continue
        items.append({"time": m.created_at, "source": "negotiation", "type": envelope.get("message_type"),
                      "from": m.sender, "to": m.receiver, "case_id": envelope.get("case_id"),
                      "session_id": str(m.session_id), "terms": envelope.get("terms"),
                      "reason_code": envelope.get("reason_code"), "text": envelope.get("text")})
    if not case_id:
        query = select(TriggerLog).order_by(TriggerLog.created_at)
        if after:
            query = query.where(TriggerLog.created_at > after)
        items += [{"time": t.created_at, "source": "trigger", "type": t.kind, "params": t.params,
                   "status": t.status, "scheduled_day": t.scheduled_day.isoformat() if t.scheduled_day else None}
                  for t in db.scalars(query.limit(TIMELINE_LIMIT))]
    query = select(LlmCall).order_by(LlmCall.queued_at)
    if after:
        query = query.where(LlmCall.queued_at > after)
    if case_id:
        query = query.where(LlmCall.case_id == case_id)
    items += [{"time": c.queued_at, "source": "ai_call", "agent": c.agent, "purpose": c.purpose, "outcome": c.outcome,
               "case_id": c.case_id, "seconds": (c.finished_at - c.started_at).total_seconds()
               if c.finished_at and c.started_at else None} for c in db.scalars(query.limit(TIMELINE_LIMIT))]
    if not case_id:
        items += _failed_work(db, after)
    items.sort(key=lambda i: i["time"])
    items = items[:TIMELINE_LIMIT]
    for item in items:
        item["time"] = item["time"].isoformat()
    return {"items": items, "next": items[-1]["time"] if items else (after.isoformat() if after else None)}


def _failed_work(db: Session, after: datetime | None) -> list[dict]:
    from app.simulation.runner import queue_counts, queue_models

    failing = queue_counts(db, (work_runner.FAILED,))  # one query; rows only from queues that have failures
    found = []
    for model in queue_models():
        if f"{model.__table__.schema}.{model.__tablename__}" not in failing:
            continue
        query = select(model).where(model.status == work_runner.FAILED)
        if after:
            query = query.where(model.created_at > after)
        found += [{"time": row.created_at, "source": "failed_work", "queue": f"{model.__table__.schema}.{model.__tablename__}",
                   "kind": row.kind, "attempts": row.attempts, "error": row.last_error} for row in db.scalars(query)]
    return found


def _event(e: Event) -> dict:
    return {"event_id": str(e.event_id), "type": e.event_type, "publisher": e.publisher,
            "entity": f"{e.entity_type}:{e.entity_id}", "correlation_id": e.correlation_id, "payload": e.payload}


# -- factory state ------------------------------------------------------------------------------------------------------


def factory_state(db: Session, day: date) -> dict:
    """The factory on one simulated day, from every owner's read module."""
    items = []
    for item in db.scalars(select(Item).where(Item.is_active.is_(True)).order_by(Item.sku)):
        position = inventory.stock_position(db, str(item.id))
        items.append({"item_id": str(item.id), "sku": item.sku, "name": item.name, "on_hand": position["on_hand"],
                      "reserved": position["reserved"], "held": position["held"],
                      "safety_stock": position["safety_stock"],
                      "available_to_promise": inventory.atp_by_date(db, str(item.id), day, day)[day.isoformat()]})
    return {
        "day": day.isoformat(),
        "stock": items,
        "space": {zone: warehouse.free_space(db, zone, day, day)[day.isoformat()]
                  for zone in ("MATERIALS", "FINISHED_GOODS")},
        "receiving_free": warehouse.free_receiving(db, day, day)[day.isoformat()],
        "worker_hours_free": {skill: hr.free_worker_hours(db, skill, day, day)[day.isoformat()]
                              for skill in hr.skills(db)},
        "machine_hours_free": {wc: planning.machine_hours_free(db, wc, day) for wc in planning.work_centers(db)},
    }
