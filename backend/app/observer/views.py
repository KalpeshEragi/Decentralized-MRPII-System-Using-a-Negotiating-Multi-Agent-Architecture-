"""The observer (backend_api.md §7, API-3): read-only views for the demo frontend. It decides nothing and writes
nothing; it only composes what already exists, through the agents' read modules (IB-2) and the infrastructure tables
(events, negotiation, simulation, observability)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import work_runner
from app.events.channel import CATALOGUE
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
    first = {}  # each session's opening request: what was asked, for which production order or demand
    if session_ids:
        for m in db.scalars(select(Message).where(Message.session_id.in_(session_ids)).order_by(Message.created_at)):
            first.setdefault(str(m.session_id), m)
    labels = _labels(db)
    plan = {**plan, "label": labels.get(demand_id), "sku": labels.get(str(plan["item_id"])),
            "production_orders": [{**o, "label": labels.get(o["id"]), "sku": labels.get(str(o["item_id"]))}
                                  for o in plan["production_orders"]]}
    return {
        "plan": plan,
        "sales": sales.inquiry_status(db, plan["sales_inquiry_id"]),
        "customer": sales.customer_conversation(db, plan["sales_inquiry_id"]),
        # every id this order is known by, so the panel can pick its lines out of the timeline
        "refs": sorted(refs | {str(s) for s in session_ids}),
        "owners": {
            "inventory": [r for ref in [demand_id, *orders_] for r in inventory.reservations_for(db, ref)],
            "hr": [{**c, "production_order_id": ref} for ref in orders_ for c in hr.commitments_for(db, ref)],
            "warehouse": warehouse.commitments_for(db, demand_id),
        },
        "cases": [{k: c[k] for k in ("case_id", "kind", "status", "depth", "created_at")} for c in cases],
        "negotiations": [_negotiation(s, first.get(str(s.id)), labels) for s in sessions],
        "events": [_event(e) for e in events],
    }


def _negotiation(s: NegotiationSession, opening: Message | None, labels: dict[str, str]) -> dict:
    """One negotiation of an order, with what was asked and readable names (the order story's plan tree)."""
    asked = (opening.envelope.get("terms") if opening else None) or {}
    return {"session_id": str(s.id), "case_id": s.case_id, "starter": s.starter, "owner": s.owner,
            "resource_type": s.resource_type, "resource_ref": s.resource_ref,
            "resource_label": labels.get(str(s.resource_ref), s.resource_ref), "status": s.status,
            "asked": asked, "order_id": asked.get("order_id"), "order_label": labels.get(str(asked.get("order_id"))),
            "started_at": opening.created_at.isoformat() if opening else None,
            "agreed_terms": s.agreed_terms, "last_reason_code": s.last_reason_code}


# -- timeline -------------------------------------------------------------------------------------------------------------


def timeline(db: Session, after: datetime | None = None, case_id: str | None = None) -> dict:
    """One stream in time order: events, negotiation messages, triggers, AI calls, agents' decisions and failed work. Poll with the
    returned `next` cursor (API-2).

    Rows saved in one transaction share one time (PostgreSQL `now()`), and the cursor is a time. So a full page never
    ends inside such a group: it stops before the last time and then takes that whole group, even past the limit.
    Otherwise the next page (`> next`) would skip the rest of the group."""
    items = sorted(_timeline_rows(db, case_id, after=after, limit=TIMELINE_LIMIT), key=lambda i: i["time"])
    if len(items) >= TIMELINE_LIMIT:  # a source may have more: end the page with a whole time group
        last = items[TIMELINE_LIMIT - 1]["time"]
        items = [i for i in items[:TIMELINE_LIMIT] if i["time"] != last] + _timeline_rows(db, case_id, at=last)
    for item in items:
        item["time"] = item["time"].isoformat()
    return {"items": items, "next": items[-1]["time"] if items else (after.isoformat() if after else None)}


def _labels(db: Session) -> dict[str, str]:
    """Readable names for the ids negotiation terms carry: items by SKU, production orders as "PO <SKU>×<qty>",
    customer demands by their Sales order number (or "order <SKU>×<qty>" before confirmation)."""
    skus = {str(i.id): i.sku for i in db.scalars(select(Item))}
    labels = dict(skus)
    for o in planning.production_orders(db):
        labels[o["id"]] = f"PO {skus.get(str(o['item_id']), '?')}×{_qty(o['quantity'])}"
    for d in planning.demands(db):
        labels[d["demand_id"]] = d["order_number"] or f"order {skus.get(str(d['item_id']), '?')}×{_qty(d['quantity'])}"
    return labels


def _qty(text: str) -> str:
    return format(Decimal(text).normalize(), "f")


def _timeline_rows(db: Session, case_id: str | None, after: datetime | None = None, at: datetime | None = None,
                   limit: int | None = None) -> list[dict]:
    """The timeline's rows of every source: later than `after` (up to `limit` per source), or exactly at `at`."""
    def window(query, column):
        if at is not None:
            return query.where(column == at)
        query = query.where(column > after) if after else query
        return query.limit(limit) if limit else query

    items = []
    query = window(select(Event).order_by(Event.published_at, Event.seq), Event.published_at)
    if case_id:
        query = query.where(Event.correlation_id == case_id)
    items += [{"source": "event", **_event(e), "time": e.published_at} for e in db.scalars(query)]

    messages = [m for m in db.scalars(window(select(Message).order_by(Message.created_at), Message.created_at))
                if not case_id or m.envelope.get("case_id") == case_id]
    labels = _labels(db) if messages else {}
    for m in messages:
        envelope, terms = m.envelope, m.envelope.get("terms") or {}
        items.append({"time": m.created_at, "source": "negotiation", "type": envelope.get("message_type"),
                      "from": m.sender, "to": m.receiver, "case_id": envelope.get("case_id"),
                      "session_id": str(m.session_id), "terms": envelope.get("terms"),
                      "reason_code": envelope.get("reason_code"), "text": envelope.get("text"),
                      "options": envelope.get("options"),  # QUOTE: the owner's quoted options (QD-1)
                      "order_label": labels.get(str(terms.get("order_id"))),
                      "resource_label": labels.get(str(terms.get("resource_ref")), terms.get("resource_ref"))})
    if not case_id:
        query = window(select(TriggerLog).order_by(TriggerLog.created_at), TriggerLog.created_at)
        items += [{"time": t.created_at, "source": "trigger", "type": t.kind, "params": t.params,
                   "status": t.status, "scheduled_day": t.scheduled_day.isoformat() if t.scheduled_day else None}
                  for t in db.scalars(query)]
    query = window(select(LlmCall).order_by(LlmCall.queued_at), LlmCall.queued_at)
    if case_id:
        query = query.where(LlmCall.case_id == case_id)
    items += [{"time": c.queued_at, "source": "ai_call", "agent": c.agent, "purpose": c.purpose, "outcome": c.outcome,
               "case_id": c.case_id, "seconds": (c.finished_at - c.started_at).total_seconds()
               if c.finished_at and c.started_at else None} for c in db.scalars(query)]
    for owner in (planning, inventory, hr, warehouse):  # the agents' own decision records (QD-3), via their reads
        items += [d for d in owner.decisions(db, after=after, at=at, limit=limit)
                  if not case_id or d["case_id"] == case_id]
    if not case_id:
        items += _failed_work(db, after, at)
    return items


def _failed_work(db: Session, after: datetime | None, at: datetime | None = None) -> list[dict]:
    from app.simulation.runner import queue_counts, queue_models

    failing = queue_counts(db, (work_runner.FAILED,))  # one query; rows only from queues that have failures
    found = []
    for model in queue_models():
        if f"{model.__table__.schema}.{model.__tablename__}" not in failing:
            continue
        query = select(model).where(model.status == work_runner.FAILED)
        if at is not None:
            query = query.where(model.created_at == at)
        elif after:
            query = query.where(model.created_at > after)
        found += [{"time": row.created_at, "source": "failed_work", "queue": f"{model.__table__.schema}.{model.__tablename__}",
                   "kind": row.kind, "attempts": row.attempts, "error": row.last_error} for row in db.scalars(query)]
    return found


def _event(e: Event) -> dict:
    subscribers = CATALOGUE.get(e.event_type, (None, ()))[1]  # who the channel delivers it to (static catalogue)
    return {"event_id": str(e.event_id), "type": e.event_type, "publisher": e.publisher,
            "entity": f"{e.entity_type}:{e.entity_id}", "correlation_id": e.correlation_id, "payload": e.payload,
            "subscribers": sorted(subscribers), "time": e.published_at.isoformat()}


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
