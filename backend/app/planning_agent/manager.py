"""Planning Agent (planning_agent/1-3). Plans requests, secures the best option with the resource owners, answers
Sales, commits confirmed orders, runs production orders. Deterministic in step 5: the fixed ranking and template
wording stand in for the AI steps until S1 works (IMP-2).

Flow (planning_agent/1 §6):
1. `accept_request` (door 1) -> work item PLAN_REQUEST -> `plan_request`: options (PL-1/PL-2); the best option is
   secured by a case: machine-hours held by Planning itself, and one negotiation per owner need (stock, worker hours,
   finished-goods space). When every owner agreed (holds placed) -> READY result to Sales (door 3).
2. `on_order_confirmed` (event from Sales): held option -> COMMIT to every session; unheld -> secure, then commit.
   All owners committed -> production orders FIRM, machine-hours committed, `PlanCommitted`.
3. Day start -> FIRM orders inside the release lead are RELEASED (`ProductionOrderReleased`).
4. Shop-floor reports -> `ProductionStarted` / `ProductionCompleted`. Shipment -> demand COMPLETED.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core import http_doors
from app.core.config import get_settings
from app.core.owner_tables import LedgerWriter
from app.core.work_runner import Registration, WorkItem as QueueItem, enqueue
from app.events import channel
from app.events.models import Event
from app.inventory_agent import reads as inventory
from app.models.core import Item
from app.negotiation import layer
from app.negotiation.envelope import Envelope, MessageType as M, ResourceType, Terms
from app.negotiation.models import Session
from app.planning_agent import plan as planner
from app.planning_agent.models import (AuditLog, Case, CustomerDemand, EventVersion, MachineHoursLedger, Option,
                                       ProductionOrder, SalesOutbox, ShopFloorReport, WorkCenter, WorkCenterDay,
                                       WorkItem)
from app.sales_agent import reads as sales
from app.simulation.clock import today
from app.simulation.settings import setting

logger = logging.getLogger(__name__)
AGENT = "PLANNING"
ZERO = Decimal(0)


def _audit(db: DbSession, event_type: str, case_id: str | None = None, **details) -> None:
    db.add(AuditLog(actor="SYSTEM", event_type=event_type, case_id=case_id,
                    details={k: str(v) if not isinstance(v, (dict, list, int, bool, type(None))) else v
                             for k, v in details.items()}))


# -- door 1: requests from Sales ---------------------------------------------------------------------------------------


def accept_request(db: DbSession, request: dict) -> str:
    """Store a Sales request and queue its planning (fast). 'duplicate' if the request_ref is known."""
    ref = request["request_ref"]
    if db.scalar(select(CustomerDemand.id).where(CustomerDemand.request_ref == ref)) is not None:
        return "duplicate"
    order = request["order"]
    sku = sales.product_sku(db, order["product_id"])
    item = db.scalar(select(Item).where(Item.sku == sku)) if sku else None
    demand = CustomerDemand(request_ref=ref, sales_inquiry_id=str(request["inquiry_id"]),
                            item_id=str(item.id) if item else "", quantity=Decimal(str(order["quantity"])),
                            requested_day=date.fromisoformat(order["requested_date"]),
                            order_day=date.fromisoformat(order["order_date"]), status="RECEIVED",
                            request_payload=request, version=1)  # customer context is stored, never used (fairness)
    db.add(demand)
    db.flush()
    enqueue(db, WorkItem, scope_key=str(demand.id), kind="PLAN_REQUEST", payload={"demand_id": str(demand.id)})
    return "received"


def handle_work_item(db: DbSession, row: WorkItem) -> None:
    demand = db.get(CustomerDemand, uuid.UUID(row.payload["demand_id"]), with_for_update=True)
    if row.kind == "PLAN_REQUEST":
        plan_request(db, demand)


def plan_request(db: DbSession, demand: CustomerDemand) -> None:
    if not demand.item_id:
        _send_result(db, demand, "NOTHING_FEASIBLE", reason="UNKNOWN_PRODUCT")
        return
    found = planner.options(db, demand.item_id, demand.quantity, demand.requested_day)
    if not found:
        demand.status = "ANSWERED"
        _send_result(db, demand, "NOTHING_FEASIBLE", reason="NO_FEASIBLE_PLAN")
        return
    for kind, spec in found:
        db.add(Option(demand_id=demand.id, kind=kind, quantity=spec.quantity, delivery_day=spec.delivery_day,
                      held=False, status="OFFERED", plan=spec.to_json()))
    db.flush()
    demand.status = "PLANNING"
    best = _options(db, demand)[0]
    _secure(db, demand, best, auto_commit=False)


def _options(db: DbSession, demand: CustomerDemand) -> list[Option]:
    order = {"REQUESTED": 0, "LATER_DATE": 1, "LESS_QUANTITY": 2}
    return sorted(db.scalars(select(Option).where(Option.demand_id == demand.id)), key=lambda o: order[o.kind])


# -- securing an option: Planning's own machine-hours + one negotiation per owner need ----------------------------------


def _machine_day(db: DbSession, work_center: str, day: date) -> WorkCenterDay:
    row = db.get(WorkCenterDay, (work_center, day), with_for_update=True)
    if row is None:
        center = db.get(WorkCenter, work_center)
        row = WorkCenterDay(work_center=work_center, day=day, capacity_hours=center.machine_hours_per_day,
                            committed_hours=ZERO, held_hours=ZERO)
        db.add(row)
        db.flush()
    return row


def _machine_hours(db: DbSession, case: Case, column: str, sign: int, reason: str, source_id: str) -> None:
    ledger = LedgerWriter(db, MachineHoursLedger, f"{source_id}:{case.id}:{column}:{reason}", today(db))
    for order in db.scalars(select(ProductionOrder).where(ProductionOrder.case_id == case.id)):
        for step in order.steps:
            for day_text, hours_text in step["hours_by_day"].items():
                row = _machine_day(db, step["work_center"], date.fromisoformat(day_text))
                delta = sign * Decimal(hours_text)
                setattr(row, column, getattr(row, column) + delta)
                ledger.write(step["work_center"], "HELD" if column == "held_hours" else "COMMITTED", delta, reason,
                             day=row.day, production_order=order.id)


def _request(db: DbSession, case: Case, receiver: str, terms: Terms, need: str) -> None:
    session_id = str(uuid.uuid4())
    case.sessions = {**case.sessions, session_id: {"owner": receiver, "need": need, "status": "OPEN"}}
    layer.send(db, Envelope(message_id=str(uuid.uuid4()), session_id=session_id, case_id=case.id, sender=AGENT,
                            receiver=receiver, message_type=M.REQUEST, terms=terms, text=f"request: {need}",
                            sent_at=datetime.now(timezone.utc)))


def _secure(db: DbSession, demand: CustomerDemand, option: Option, auto_commit: bool) -> None:
    """Create the case and production orders of `option`, hold machine-hours, and ask every owner (in parallel)."""
    spec = option.plan
    case = Case(id=planner.new_case_id(), demand_id=demand.id, option_id=option.id, kind="NEW_REQUEST",
                auto_commit=auto_commit, status="OPEN", sessions={}, depth=0)
    db.add(case)
    db.flush()
    orders: dict[str, ProductionOrder] = {}
    for production in spec["production"]:  # parents first (they come first in the plan)
        order = ProductionOrder(demand_id=demand.id, option_id=option.id, item_id=production["item_id"],
                                quantity=Decimal(production["quantity"]),
                                start_day=date.fromisoformat(production["start_day"]),
                                end_day=date.fromisoformat(production["end_day"]), for_kind="CUSTOMER_DEMAND",
                                for_ref=str(demand.id), steps=production["steps"], status="PLANNED",
                                quantity_completed=ZERO, case_id=case.id, version=1)
        db.add(order)
        db.flush()
        orders[production["key"]] = order
    for production in spec["production"]:
        if production["for_key"] != planner.DEMAND:
            parent = orders[production["for_key"]]
            orders[production["key"]].for_kind, orders[production["key"]].for_ref = "PRODUCTION_ORDER", str(parent.id)
    _machine_hours(db, case, "held_hours", 1, "HOLD", case.id)

    for need in spec["stock"]:
        for_kind = "CUSTOMER_DEMAND" if need["for_key"] == planner.DEMAND else "PRODUCTION_ORDER"
        for_ref = str(demand.id) if for_kind == "CUSTOMER_DEMAND" else str(orders[need["for_key"]].id)
        _request(db, case, "INVENTORY", Terms(resource_type=ResourceType.STOCK, resource_ref=need["item_id"],
                                              quantity=Decimal(need["quantity"]),
                                              needed_by=date.fromisoformat(need["needed_by"]), order_id=for_ref,
                                              extra={"for_kind": for_kind}), f"stock {need['item_id']}")
    for production in spec["production"]:
        order = orders[production["key"]]
        for step in production["steps"]:
            hours = {d: str(Decimal(h) * step["crew"]) for d, h in step["hours_by_day"].items()}
            _request(db, case, "HR", Terms(resource_type=ResourceType.WORKFORCE, resource_ref=step["skill"],
                                           quantity=sum((Decimal(h) for h in hours.values()), ZERO), unit="h",
                                           date_from=order.start_day, date_to=order.end_day, order_id=str(order.id),
                                           extra={"hours_by_day": hours, "allow_overtime": False}),
                     f"workers {step['skill']}")
    top = next((orders[p["key"]] for p in spec["production"] if p["for_key"] == planner.DEMAND), None)
    if top is not None:
        _request(db, case, "WAREHOUSE", Terms(resource_type=ResourceType.STORAGE_SPACE, resource_ref="FINISHED_GOODS",
                                              quantity=top.quantity, needed_by=top.end_day, order_id=str(demand.id),
                                              extra={"item_id": demand.item_id,
                                                     "until_day": spec["delivery_day"]}), "finished-goods space")
    _audit(db, "OPTION_SECURING", case.id, option=option.kind, sessions=len(case.sessions))
    if not case.sessions:  # everything already in Planning's hands
        _all_agreed(db, case)


# -- Planning's inbox (Planning is the starter) ----------------------------------------------------------------------------


def handle_message(db: DbSession, message: Envelope, session: Session) -> None:
    case = db.get(Case, message.case_id, with_for_update=True)
    if case is None:
        return
    kind = message.message_type
    if kind == M.OFFER and case.status == "OPEN":
        layer.send(db, layer.reply_to(message, M.ACCEPT, text="accept"))
    elif kind == M.COUNTER_OFFER and case.status == "OPEN":
        # Step 5: any change to the planned terms means the option cannot be secured as planned (step 6 adds
        # alternatives and the ranking here).
        layer.send(db, layer.reply_to(message, M.REJECT, reason_code=message.reason_code, text="cannot use that"))
        _fail_case(db, case, f"COUNTER_{message.reason_code}")
    elif kind == M.AGREEMENT_PROPOSED:
        _set(case, session, "AGREED")
        if all(s["status"] == "AGREED" for s in case.sessions.values()):
            _all_agreed(db, case)
    elif kind == M.ACCEPT and case.status == "COMMITTING":
        _set(case, session, "COMMITTED")
        if all(s["status"] == "COMMITTED" for s in case.sessions.values()):
            _finish_commit(db, case)
    elif kind == M.REJECT:
        _set(case, session, "REJECTED")
        if case.status == "COMMITTING":
            _commit_failed(db, case, message.reason_code.value)
        elif case.status in ("OPEN", "AGREED"):
            _fail_case(db, case, message.reason_code.value)


def _set(case: Case, session: Session, status: str) -> None:
    sessions = dict(case.sessions)
    sessions[str(session.id)] = {**sessions[str(session.id)], "status": status}
    case.sessions = sessions


def _all_agreed(db: DbSession, case: Case) -> None:
    demand = db.get(CustomerDemand, case.demand_id, with_for_update=True)
    option = db.get(Option, case.option_id)
    if case.auto_commit:
        _commit(db, case)
        return
    case.status = "AGREED"
    option.held = True
    demand.status = "ANSWERED"
    _send_result(db, demand, "READY")


def _fail_case(db: DbSession, case: Case, reason: str) -> None:
    """The option cannot be secured: abort the other open sessions, release Planning's holds, try the next option."""
    case.status = "FAILED"
    _abort_open_sessions(db, case)
    _machine_hours(db, case, "held_hours", -1, "HOLD_RELEASED", case.id)
    for order in db.scalars(select(ProductionOrder).where(ProductionOrder.case_id == case.id)):
        order.status = "CANCELLED"
    option = db.get(Option, case.option_id)
    option.status, option.held = "WITHDRAWN", False
    demand = db.get(CustomerDemand, case.demand_id, with_for_update=True)
    _audit(db, "OPTION_FAILED", case.id, reason=reason)
    if demand.status == "ANSWERED":  # the offer was already with the customer: its hold expired or was lost
        demand.status = "EXPIRED"
        return
    tried = len(db.scalars(select(Case).where(Case.demand_id == demand.id)).all())
    remaining = [o for o in _options(db, demand) if o.status == "OFFERED"]
    if remaining and tried <= int(setting(db, "best_option_repicks")):
        _secure(db, demand, remaining[0], auto_commit=case.auto_commit)
    elif case.auto_commit:
        _publish_plan_event(db, demand, "PlanCommitFailed", {"reason": reason})
        demand.status = "COMMIT_FAILED"
    else:
        demand.status = "ANSWERED"
        _send_result(db, demand, "NOTHING_FEASIBLE", reason=reason)


def _abort_open_sessions(db: DbSession, case: Case) -> None:
    for session_id in case.sessions:
        session = db.get(Session, uuid.UUID(session_id))
        if session is not None and session.status in ("NEGOTIATING", "AGREEMENT_PROPOSED"):
            layer.send(db, Envelope(message_id=str(uuid.uuid4()), session_id=session_id, case_id=case.id,
                                    sender=AGENT, receiver=session.owner, message_type=M.ABORT, text="abort",
                                    sent_at=datetime.now(timezone.utc)))


# -- confirmation and commit ------------------------------------------------------------------------------------------------


def on_order_confirmed(db: DbSession, event: Event) -> None:
    if not channel.is_newer(db, EventVersion, event):
        return
    notice = event.payload
    demand = db.scalar(select(CustomerDemand).where(CustomerDemand.sales_inquiry_id == str(notice["inquiry_id"]))
                       .with_for_update())
    if demand is None:
        logger.error("order confirmed for unknown inquiry %s", notice["inquiry_id"])
        return
    quantity, day = Decimal(str(notice["quantity"])), date.fromisoformat(notice["delivery_date"])
    option = next((o for o in _options(db, demand) if o.quantity == quantity and o.delivery_day == day
                   and o.status == "OFFERED"), None)
    demand.sales_order_number = notice.get("order_number")
    if option is None:
        _publish_plan_event(db, demand, "PlanCommitFailed", {"reason": "UNKNOWN_OPTION"})
        demand.status = "COMMIT_FAILED"
        return
    demand.status, demand.chosen_option_id, option.status = "CONFIRMED", option.id, "CHOSEN"
    case = db.scalar(select(Case).where(Case.option_id == option.id, Case.status == "AGREED").with_for_update())
    if option.held and case is not None:
        _commit(db, case)  # execution policy (NG-4): confirmed + every session agreed + still held
    else:
        spec = planner.make_plan(db, demand.item_id, option.quantity, option.delivery_day)  # re-plan: facts moved
        if not spec.feasible:
            _publish_plan_event(db, demand, "PlanCommitFailed", {"reason": spec.reason})
            demand.status = "COMMIT_FAILED"
            return
        option.plan = spec.to_json()
        _secure(db, demand, option, auto_commit=True)


def _commit(db: DbSession, case: Case) -> None:
    case.status = "COMMITTING"
    for session_id in case.sessions:
        session = db.get(Session, uuid.UUID(session_id))
        layer.send(db, Envelope(message_id=str(uuid.uuid4()), session_id=session_id, case_id=case.id, sender=AGENT,
                                receiver=session.owner, message_type=M.COMMIT, text="commit",
                                sent_at=datetime.now(timezone.utc)))
    if not case.sessions:
        _finish_commit(db, case)


def _finish_commit(db: DbSession, case: Case) -> None:
    case.status = "COMMITTED"
    demand = db.get(CustomerDemand, case.demand_id, with_for_update=True)
    option = db.get(Option, case.option_id)
    _machine_hours(db, case, "held_hours", -1, "COMMIT", case.id)
    _machine_hours(db, case, "committed_hours", 1, "COMMIT", case.id)
    orders = db.scalars(select(ProductionOrder).where(ProductionOrder.case_id == case.id)).all()
    lead = timedelta(days=int(setting(db, "release_lead_days")))
    for order in orders:
        order.status = "FIRM"
        if order.start_day - lead <= today(db):  # already inside the release lead: release now, not tomorrow
            _release(db, order, None)
    demand.status, demand.committed_quantity, demand.committed_day = "COMMITTED", option.quantity, option.delivery_day
    _publish_plan_event(db, demand, "PlanCommitted", {
        "delivery_day": option.delivery_day.isoformat(), "quantity": str(option.quantity),
        "production_orders": [{"id": str(o.id), "item_id": o.item_id, "quantity": str(o.quantity),
                               "start_day": o.start_day.isoformat(), "end_day": o.end_day.isoformat()}
                              for o in orders]})


def _commit_failed(db: DbSession, case: Case, reason: str) -> None:
    """Compensation (negotiation.md §8): no rollback across agents; abort what is open, release what was committed."""
    case.status = "COMMIT_FAILED"
    demand = db.get(CustomerDemand, case.demand_id, with_for_update=True)
    _abort_open_sessions(db, case)
    _machine_hours(db, case, "held_hours", -1, "COMMIT_FAILED", case.id)
    releases = [{"owner": "INVENTORY", "reservation_id": r["id"], "quantity": r["quantity"]}
                for order_ref in [str(demand.id), *[str(o.id) for o in db.scalars(
                    select(ProductionOrder).where(ProductionOrder.case_id == case.id))]]
                for r in inventory.reservations_for(db, order_ref) if r["kind"] == "RESERVATION"]
    for order in db.scalars(select(ProductionOrder).where(ProductionOrder.case_id == case.id)):
        order.status = "CANCELLED"
    demand.status = "COMMIT_FAILED"
    _publish_plan_event(db, demand, "PlanCommitFailed", {"reason": reason})
    if releases:
        _publish_plan_event(db, demand, "PlanRevised", {"reason": "COMMIT_FAILED", "releases": releases})


def _publish_plan_event(db: DbSession, demand: CustomerDemand, event_type: str, payload: dict) -> None:
    demand.version += 1
    channel.publish(db, event_type=event_type, publisher=AGENT, entity_type="customer_demand",
                    entity_id=str(demand.id), entity_version=demand.version, correlation_id=demand.request_ref,
                    payload={"demand_id": str(demand.id), "order_number": demand.sales_order_number,
                             "request_ref": demand.request_ref, **payload})


# -- production orders --------------------------------------------------------------------------------------------------------


def on_day_started(db: DbSession, event: Event) -> None:
    """Release FIRM orders whose start is within the release lead (PL-7) -> ProductionOrderReleased."""
    day = date.fromisoformat(event.payload["date"])
    lead = timedelta(days=int(setting(db, "release_lead_days")))
    for order in db.scalars(select(ProductionOrder).where(ProductionOrder.status == "FIRM",
                                                          ProductionOrder.start_day - lead <= day)
                            .with_for_update()).all():
        _release(db, order, event.event_id)


def _release(db: DbSession, order: ProductionOrder, causation_id) -> None:
    order.status, order.version = "RELEASED", order.version + 1
    channel.publish(db, event_type="ProductionOrderReleased", publisher=AGENT, entity_type="production_order",
                    entity_id=str(order.id), entity_version=order.version, correlation_id=str(order.demand_id),
                    causation_id=causation_id,
                    payload={"production_order_id": str(order.id), "item_id": order.item_id,
                             "quantity": str(order.quantity), "start_day": order.start_day.isoformat(),
                             "end_day": order.end_day.isoformat(), "demand_id": str(order.demand_id),
                             "steps": order.steps})


def record_shop_floor_report(db: DbSession, report_id: str, production_order_id: str, kind: str,
                             quantity: Decimal | None = None) -> str:
    """Input from the simulated shop floor (RD-3). STARTED or QUANTITY_COMPLETED."""
    if db.get(ShopFloorReport, report_id) is not None:
        return "duplicate"
    order = db.get(ProductionOrder, uuid.UUID(production_order_id), with_for_update=True)
    if order is None or kind not in ("STARTED", "QUANTITY_COMPLETED"):
        raise ValueError("unknown production order or report kind")
    db.add(ShopFloorReport(report_id=report_id, production_order_id=order.id, kind=kind, quantity=quantity))
    order.version += 1
    common = {"production_order_id": str(order.id), "order_ref": str(order.demand_id), "item_id": order.item_id,
              "for_kind": order.for_kind, "for_ref": order.for_ref}
    if kind == "STARTED":
        order.status = "STARTED"
        channel.publish(db, event_type="ProductionStarted", publisher=AGENT, entity_type="production_order",
                        entity_id=str(order.id), entity_version=order.version, correlation_id=str(order.demand_id),
                        payload={**common, "quantity": str(order.quantity)})
        return "received"
    done = Decimal(quantity)
    order.quantity_completed += done
    if order.quantity_completed >= order.quantity:
        order.status = "COMPLETED"
    channel.publish(db, event_type="ProductionCompleted", publisher=AGENT, entity_type="production_order",
                    entity_id=str(order.id), entity_version=order.version, correlation_id=str(order.demand_id),
                    payload={**common, "quantity": str(done), "completion_day": today(db).isoformat()})
    return "received"


def on_shipment(db: DbSession, event: Event) -> None:
    if not channel.is_newer(db, EventVersion, event):
        return
    demand = db.get(CustomerDemand, uuid.UUID(event.payload["order_ref"]), with_for_update=True)
    if demand is None:
        return
    demand.quantity_shipped += Decimal(event.payload["quantity"])
    if demand.quantity_shipped >= demand.committed_quantity:
        demand.status = "COMPLETED"


# -- door 3 to Sales (outbox) -------------------------------------------------------------------------------------------


def _send_result(db: DbSession, demand: CustomerDemand, status: str, reason: str | None = None) -> None:
    options = []
    if status == "READY":
        options = [{"kind": o.kind, "quantity": str(o.quantity), "delivery_date": o.delivery_day.isoformat(),
                    "held": o.held} for o in _options(db, demand) if o.status == "OFFERED"]
    enqueue(db, SalesOutbox, scope_key=demand.request_ref, kind=status,
            payload={"request_ref": demand.request_ref, "status": status, "options": options, "reason_code": reason})
    _audit(db, "RESULT_SENT", None, request_ref=demand.request_ref, status=status)


def send_to_sales(session_factory, item: QueueItem, renew) -> None:
    """Long-mode outbox handler: POST the result to Sales door 3. 5xx/network -> retried; 4xx -> recorded, not retried."""
    response = http_doors.post("/sales/planning/results", item.payload,
                               {"X-Planning-Key": get_settings().sales_planning_key or ""})
    if response.status_code >= 400:
        logger.error("Sales refused planning result %s: %s", item.payload["request_ref"], response.text[:300])


# -- setup and registration ----------------------------------------------------------------------------------------------------


def setup(db: DbSession, work_centers: dict[str, object]) -> None:
    """Work centers and their machine-hours per day: {"SMT": 8, "ASM": 16}."""
    for code, hours in work_centers.items():
        db.merge(WorkCenter(code=code, machine_hours_per_day=Decimal(str(hours))))
    db.flush()


def register(runner_register) -> None:
    runner_register(layer.register_inbox(AGENT, handle_message))
    runner_register(Registration(name="planning-work", model=WorkItem, handler=handle_work_item, mode="short",
                                 workers=4))
    runner_register(Registration(name="planning-sales-outbox", model=SalesOutbox, handler=send_to_sales, mode="long"))
    channel.subscribe(AGENT, "OrderConfirmed", on_order_confirmed)
    channel.subscribe(AGENT, "SimulatedDayStarted", on_day_started)
    channel.subscribe(AGENT, "ShipmentDispatched", on_shipment)
