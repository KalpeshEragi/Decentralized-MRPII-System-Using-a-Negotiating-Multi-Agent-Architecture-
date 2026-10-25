"""Measurements of a run (system_design.md §10, step 8 load runs): how fast the six agents work under load, read from
what the infrastructure already records. A run starts from a restored state, so the tables hold exactly one run.
Read-only. Times are real seconds (wall clock), except where a field says simulated days.

- orders: by status, completed on time, real seconds from request to committed plan;
- days: real seconds each simulated day took until the factory was quiet (between two `SimulatedDayStarted`);
- event delivery: lag from publish to handled, attempts, failures;
- queues: per work queue, items, failures, real seconds from queued to done, most attempts;
- negotiations: by status, real seconds from first message to closed, messages per session;
- AI calls: by outcome, wait in the shared model's queue, response time.
"""

from sqlalchemy import Float, cast, extract, func, select
from sqlalchemy.orm import Session

from app.core import work_runner
from app.events.models import Event, EventDelivery
from app.negotiation.models import Session as NegotiationSession
from app.observability.models import LlmCall
from app.planning_agent import reads as planning
from app.planning_agent.models import CustomerDemand


def _stats(db: Session, seconds, *where) -> dict:
    """count, p50, p95 and max of a duration expression (seconds), over the rows that match `where`."""
    row = db.execute(select(func.count(seconds), func.percentile_cont(0.5).within_group(seconds),
                            func.percentile_cont(0.95).within_group(seconds), func.max(seconds)).where(*where)).one()
    count, p50, p95, most = row
    return {"count": count, "p50": _round(p50), "p95": _round(p95), "max": _round(most)}


def _round(value) -> float | None:
    return round(float(value), 2) if value is not None else None


def _seconds(later, earlier):
    return cast(extract("epoch", later - earlier), Float)


def measurements(db: Session) -> dict:
    return {"orders": _orders(db), "days": _days(db), "event_delivery": _event_delivery(db), "queues": _queues(db),
            "negotiations": _negotiations(db), "ai_calls": _ai_calls(db)}


def _orders(db: Session) -> dict:
    demands = planning.demands(db, limit=100000)
    shipped = {e.payload["order_ref"]: e.payload.get("date") for e in db.scalars(
        select(Event).where(Event.event_type == "ShipmentDispatched"))}
    completed = [d for d in demands if d["status"] == "COMPLETED"]
    on_time = [d for d in completed if d["committed_day"] and shipped.get(d["demand_id"], "9999") <= d["committed_day"]]
    by_status: dict[str, int] = {}
    for d in demands:
        by_status[d["status"]] = by_status.get(d["status"], 0) + 1
    committed = select(Event.correlation_id, func.min(Event.published_at).label("at")).where(
        Event.event_type == "PlanCommitted").group_by(Event.correlation_id).subquery()
    asked = select(Event.correlation_id, func.min(Event.published_at).label("at")).where(
        Event.event_type == "OrderConfirmed").group_by(Event.correlation_id).subquery()
    request_to_commit = _stats(db, _seconds(committed.c.at, CustomerDemand.created_at),
                               committed.c.correlation_id == CustomerDemand.request_ref)
    # Sales correlates by order number, Planning by request reference: joined through Planning's demand
    confirm_to_commit = _stats(db, _seconds(committed.c.at, asked.c.at),
                               committed.c.correlation_id == CustomerDemand.request_ref,
                               asked.c.correlation_id == CustomerDemand.sales_order_number)
    return {"total": len(demands), "by_status": by_status, "completed": len(completed),
            "completed_on_time": len(on_time),
            "on_time_percent": round(100 * len(on_time) / len(completed), 1) if completed else None,
            "seconds_request_to_committed": request_to_commit, "seconds_confirmed_to_committed": confirm_to_commit}


def _days(db: Session) -> dict:
    starts = [e.published_at for e in db.scalars(select(Event).where(Event.event_type == "SimulatedDayStarted")
                                                 .order_by(Event.published_at))]
    lengths = sorted((b - a).total_seconds() for a, b in zip(starts, starts[1:]))
    if not lengths:
        return {"count": len(starts), "p50": None, "p95": None, "max": None}
    pick = lambda q: round(lengths[min(len(lengths) - 1, int(q * len(lengths)))], 2)  # noqa: E731
    return {"count": len(starts), "p50": pick(0.5), "p95": pick(0.95), "max": round(lengths[-1], 2)}


def _event_delivery(db: Session) -> dict:
    lag = _stats(db, _seconds(EventDelivery.done_at, Event.published_at), EventDelivery.event_id == Event.event_id,
                 EventDelivery.done_at.is_not(None))
    attempts = db.execute(select(func.avg(EventDelivery.attempts), func.max(EventDelivery.attempts))).one()
    failed = db.scalar(select(func.count()).select_from(EventDelivery).where(EventDelivery.status == work_runner.FAILED))
    return {"seconds_lag": lag, "attempts_avg": _round(attempts[0]), "attempts_max": attempts[1], "failed": failed}


def _queues(db: Session) -> dict:
    from app.simulation.runner import queue_models

    found = {}
    for model in queue_models():
        name = f"{model.__table__.schema}.{model.__tablename__}"
        total = db.scalar(select(func.count()).select_from(model))
        if not total:
            continue
        found[name] = {
            "items": total,
            "failed": db.scalar(select(func.count()).select_from(model).where(model.status == work_runner.FAILED)),
            "seconds_queued_to_done": _stats(db, _seconds(model.done_at, model.created_at), model.done_at.is_not(None)),
            "attempts_max": db.scalar(select(func.max(model.attempts))),
        }
    return found


def _negotiations(db: Session) -> dict:
    by_status = dict(db.execute(select(NegotiationSession.status, func.count()).group_by(NegotiationSession.status)).all())
    duration = _stats(db, _seconds(NegotiationSession.closed_at, NegotiationSession.created_at),
                      NegotiationSession.closed_at.is_not(None))
    messages = db.execute(select(func.avg(NegotiationSession.message_count),
                                 func.max(NegotiationSession.message_count))).one()
    return {"by_status": by_status, "seconds_open_to_closed": duration, "messages_avg": _round(messages[0]),
            "messages_max": messages[1]}


def _ai_calls(db: Session) -> dict:
    by_outcome = dict(db.execute(select(LlmCall.outcome, func.count()).group_by(LlmCall.outcome)).all())
    wait = _stats(db, _seconds(LlmCall.started_at, LlmCall.queued_at), LlmCall.started_at.is_not(None))
    response = _stats(db, _seconds(LlmCall.finished_at, LlmCall.started_at), LlmCall.finished_at.is_not(None))
    return {"by_outcome": by_outcome, "seconds_waiting": wait, "seconds_responding": response}
