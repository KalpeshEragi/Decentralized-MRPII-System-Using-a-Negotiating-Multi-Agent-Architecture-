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
from app.hr_agent import reads as hr
from app.inventory_agent import reads as inventory
from app.models.core import Bom, BomItem, Item, Routing
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
from app.warehouse_agent import reads as warehouse

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
    return sorted((o for o in db.scalars(select(Option).where(Option.demand_id == demand.id)) if o.kind in order),
                  key=lambda o: order[o.kind])


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


def _secure(db: DbSession, demand: CustomerDemand, option: Option, auto_commit: bool,
            kind: str = "NEW_REQUEST") -> None:
    """Create the case and production orders of `option`, hold machine-hours, and ask every owner (in parallel)."""
    spec = option.plan
    case = Case(id=planner.new_case_id(), demand_id=demand.id, option_id=option.id, kind=kind,
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
        # Any change to the planned terms means the option (or the repair) cannot be done as planned.
        layer.send(db, layer.reply_to(message, M.REJECT, reason_code=message.reason_code, text="cannot use that"))
        _fail_case(db, case, f"COUNTER_{message.reason_code}")
    elif kind == M.AGREEMENT_PROPOSED:
        _set(case, session, "AGREED")
        if all(s["status"] == "AGREED" for s in case.sessions.values()):
            _all_agreed(db, case)
    elif kind == M.ACCEPT and case.status == "COMMITTING":
        _set(case, session, "COMMITTED")
        if all(s["status"] == "COMMITTED" for s in case.sessions.values()):
            if case.kind == "REPAIR":
                _finish_repair(db, case)
            else:
                _finish_commit(db, case)
    elif kind == M.REJECT:
        _set(case, session, "REJECTED")
        if case.kind == "REPAIR" or (case.kind == "CHANGE" and case.status != "COMMITTING"):
            _fail_case(db, case, message.reason_code.value)
        elif case.status == "COMMITTING":
            _commit_failed(db, case, message.reason_code.value)
        elif case.status in ("OPEN", "AGREED"):
            _fail_case(db, case, message.reason_code.value)


def _set(case: Case, session: Session, status: str) -> None:
    sessions = dict(case.sessions)
    sessions[str(session.id)] = {**sessions[str(session.id)], "status": status}
    case.sessions = sessions


def _all_agreed(db: DbSession, case: Case) -> None:
    if case.kind == "REPAIR":  # a repair of a committed plan is committed as soon as the owner agrees
        _commit(db, case)
        return
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
    if case.kind == "CHANGE":  # the extra quantity cannot be secured: the order stays exactly as it was
        _machine_hours(db, case, "held_hours", -1, "HOLD_RELEASED", case.id)
        for order in db.scalars(select(ProductionOrder).where(ProductionOrder.case_id == case.id)):
            order.status = "CANCELLED"
        db.get(Option, case.option_id).status = "WITHDRAWN"
        demand = db.get(CustomerDemand, case.demand_id, with_for_update=True)
        _publish_plan_event(db, demand, "PlanRevised", {"reason": "CHANGE_REJECTED", "detail": reason,
                                                        "quantity": str(demand.committed_quantity), "releases": []})
        return
    if case.kind == "REPAIR":  # nothing of Planning's own was moved yet; the order stays at risk
        repair = _repair_of(case)
        _plan_at_risk(db, db.get(ProductionOrder, uuid.UUID(repair["order_id"])), repair["from_day"],
                      repair["skill"], repair["worker_hours"], f"REPAIR_FAILED_{reason}")
        return
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
    if case.kind == "CHANGE":
        demand.committed_quantity += option.quantity
        _publish_plan_event(db, demand, "PlanRevised", {
            "reason": "QUANTITY_INCREASED", "quantity": str(demand.committed_quantity), "releases": [],
            "production_orders": [{"id": str(o.id), "item_id": o.item_id, "quantity": str(o.quantity)} for o in orders]})
        return
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


# -- cancellation (S6) -------------------------------------------------------------------------------------------------------


def on_order_cancelled(db: DbSession, event: Event) -> None:
    """The customer cancelled. Production orders not yet released are cancelled and their machine-hours freed; one
    `PlanRevised` lists exactly what each owner should release. Released or started orders are never changed
    automatically (RD-4): they finish, and their output goes to free stock instead of the cancelled order."""
    if not channel.is_newer(db, EventVersion, event):
        return
    demand = db.scalar(select(CustomerDemand).where(CustomerDemand.sales_order_number == event.payload["order_number"])
                       .with_for_update())
    if demand is None or demand.status in ("CANCELLED", "COMPLETED"):
        return
    orders = db.scalars(select(ProductionOrder).where(ProductionOrder.demand_id == demand.id,
                                                      ProductionOrder.status != "CANCELLED")
                        .with_for_update()).all()
    cancelled = [o for o in orders if o.status in ("PLANNED", "FIRM")]
    running = [o for o in orders if o.status in ("RELEASED", "STARTED")]
    _free_machine_hours(db, cancelled, str(event.event_id))
    for order in cancelled:
        order.status, order.version = "CANCELLED", order.version + 1
    for order in running:
        order.for_kind, order.for_ref = "STOCK", ""  # its output no longer belongs to an order
    releases = _releases_for(db, demand, cancelled)
    demand.status = "CANCELLED"
    _publish_plan_event(db, demand, "PlanRevised", {
        "reason": "CANCELLED", "releases": releases,
        "cancelled_production_orders": [str(o.id) for o in cancelled],
        "continuing_production_orders": [str(o.id) for o in running]})


def _free_machine_hours(db: DbSession, orders: list[ProductionOrder], source_id: str) -> None:
    """Give back the committed machine-hours of these orders from today on."""
    start = today(db)
    ledger = LedgerWriter(db, MachineHoursLedger, f"{source_id}:machine-release", start)
    for order in orders:
        for step in order.steps:
            for day_text, hours_text in step["hours_by_day"].items():
                day = date.fromisoformat(day_text)
                if order.status == "FIRM" and day >= start:
                    row = _machine_day(db, step["work_center"], day)
                    row.committed_hours -= Decimal(hours_text)
                    ledger.write(step["work_center"], "COMMITTED", -Decimal(hours_text), "RELEASE", day=day,
                                 production_order=order.id)


def _open_reservations(db: DbSession, refs: list[str], item_id: str | None = None) -> list[dict]:
    """Inventory releases for every open reservation of these demand / production order ids."""
    releases = []
    for ref in refs:
        for r in inventory.reservations_for(db, ref):
            open_quantity = Decimal(r["quantity"]) - Decimal(r.get("issued", "0"))
            if (r["kind"] == "RESERVATION" and r["status"] in ("ACTIVE", "AT_RISK") and open_quantity > 0
                    and (item_id is None or r["item_id"] == item_id)):
                releases.append({"owner": "INVENTORY", "reservation_id": r["id"], "quantity": str(open_quantity)})
    return releases


def _releases_for(db: DbSession, demand: CustomerDemand, cancelled: list[ProductionOrder]) -> list[dict]:
    """What each owner holds for the demand and the cancelled production orders (read through their read modules)."""
    releases = _open_reservations(db, [str(demand.id), *[str(o.id) for o in cancelled]])
    for order in cancelled:
        releases += [{"owner": "HR", "commitment_id": c["id"]} for c in hr.commitments_for(db, str(order.id))
                     if c["status"] in ("ACTIVE", "AT_RISK")]
    releases += [{"owner": "WAREHOUSE", "commitment_id": c["id"]} for c in warehouse.commitments_for(db, str(demand.id))
                 if c["status"] == "ACTIVE"]
    return releases


# -- order change (S7) -------------------------------------------------------------------------------------------------------


def on_order_change(db: DbSession, event: Event) -> None:
    """The customer changes the quantity of a committed order. Handled as a delta (QA-3): what is committed stays.
    More: only the extra quantity is planned and secured. Less: within the dampener (RD-8) nothing is changed; beyond
    it, production orders that are still FIRM and outside the time fence shrink and owners release exactly the delta.
    Whatever cannot shrink is released when the order is complete."""
    if not channel.is_newer(db, EventVersion, event):
        return
    demand = db.scalar(select(CustomerDemand).where(CustomerDemand.sales_order_number == event.payload["order_number"])
                       .with_for_update())
    if demand is None or demand.status != "COMMITTED":
        return
    new, old = Decimal(str(event.payload["quantity"])), demand.committed_quantity
    if new > old:
        _increase(db, demand, new - old)
    elif new < old:
        _decrease(db, demand, old - new, str(event.event_id))


def _increase(db: DbSession, demand: CustomerDemand, extra: Decimal) -> None:
    spec = planner.make_plan(db, demand.item_id, extra, demand.committed_day)
    if not spec.feasible:
        _publish_plan_event(db, demand, "PlanRevised", {"reason": "CHANGE_REJECTED", "detail": spec.reason,
                                                        "quantity": str(demand.committed_quantity), "releases": []})
        return
    option = Option(demand_id=demand.id, kind="CHANGE", quantity=extra, delivery_day=demand.committed_day,
                    held=False, status="CHOSEN", plan=spec.to_json())
    db.add(option)
    db.flush()
    _secure(db, demand, option, auto_commit=True, kind="CHANGE")


def _decrease(db: DbSession, demand: CustomerDemand, cut: Decimal, source_id: str) -> None:
    old = demand.committed_quantity
    demand.committed_quantity = old - cut
    if cut / old <= Decimal(str(setting(db, "dampener_quantity_share"))):  # harmless: the plan is not touched
        _publish_plan_event(db, demand, "PlanRevised", {"reason": "QUANTITY_DECREASED_DAMPENED",
                                                        "quantity": str(demand.committed_quantity), "releases": []})
        return
    fence = today(db) + timedelta(days=int(setting(db, "time_fence_days")))
    releases: list[dict] = []
    ledger = LedgerWriter(db, MachineHoursLedger, f"{source_id}:shrink", today(db))
    remaining = cut
    for order in db.scalars(select(ProductionOrder).where(
            ProductionOrder.demand_id == demand.id, ProductionOrder.for_kind == "CUSTOMER_DEMAND",
            ProductionOrder.status == "FIRM", ProductionOrder.start_day > fence)
            .order_by(ProductionOrder.start_day.desc(), ProductionOrder.quantity, ProductionOrder.id)
            .with_for_update()).all():  # latest first; small ones go whole first (fewer orders remain)
        take = min(remaining, order.quantity)
        if take > 0:
            _shrink(db, order, take, fence, ledger, releases)
            remaining -= take
    if remaining > 0:  # then finished goods reserved from stock for this order
        for release in _open_reservations(db, [str(demand.id)], demand.item_id):
            take = min(remaining, Decimal(release["quantity"]))
            if take > 0:
                releases.append({**release, "quantity": str(take)})
                remaining -= take
    _publish_plan_event(db, demand, "PlanRevised", {"reason": "QUANTITY_DECREASED",
                                                    "quantity": str(demand.committed_quantity), "releases": releases})


def _shrink(db: DbSession, order: ProductionOrder, cut: Decimal, fence: date, ledger: LedgerWriter,
            releases: list[dict]) -> None:
    """Make `cut` fewer of this FIRM order: free its run hours (machine: Planning; workers: HR, from the last day back),
    then shrink the sub-assembly orders that feed it, or release the components reserved for it."""
    order.quantity -= cut
    order.version += 1
    whole = order.quantity <= 0
    if whole:
        order.status = "CANCELLED"
    commitments = hr.commitments_for(db, str(order.id))
    steps = []
    for step in order.steps:
        routing = db.scalar(select(Routing).where(Routing.item_id == uuid.UUID(order.item_id),
                                                  Routing.work_center_code == step["work_center"]))
        hours = {d: Decimal(h) for d, h in step["hours_by_day"].items()}
        free = sum(hours.values(), ZERO) if whole else planner.round_hours(routing.run_hours_per_unit * cut)
        for day_text in sorted(hours, reverse=True):
            take = min(free, hours[day_text])
            if take <= 0:
                continue
            hours[day_text] -= take
            free -= take
            row = _machine_day(db, step["work_center"], date.fromisoformat(day_text))
            row.committed_hours -= take
            ledger.write(step["work_center"], "COMMITTED", -take, "QUANTITY_DECREASED", day=row.day,
                         production_order=order.id)
            commitment = next((c for c in commitments if c["skill"] == step["skill"] and day_text in c["lines"]
                               and c["status"] in ("ACTIVE", "AT_RISK")), None)
            if commitment is not None:
                releases.append({"owner": "HR", "commitment_id": commitment["id"], "day": day_text,
                                 "hours": str(take * Decimal(step["crew"]))})
        steps.append({**step, "hours_by_day": {d: str(h) for d, h in hours.items() if h > 0}})
    order.steps = steps
    bom = db.scalar(select(Bom).where(Bom.parent_item_id == uuid.UUID(order.item_id), Bom.is_active.is_(True)))
    for line in db.scalars(select(BomItem).where(BomItem.bom_id == bom.id)) if bom else []:
        need = line.quantity_required * cut
        child_id = str(line.component_item_id)
        for child in db.scalars(select(ProductionOrder).where(
                ProductionOrder.for_kind == "PRODUCTION_ORDER", ProductionOrder.for_ref == str(order.id),
                ProductionOrder.item_id == child_id, ProductionOrder.status == "FIRM",
                ProductionOrder.start_day > fence).with_for_update()).all():
            take = min(need, child.quantity)
            if take > 0:
                _shrink(db, child, take, fence, ledger, releases)
                need -= take
        for release in _open_reservations(db, [str(order.id)], child_id):
            take = min(need, Decimal(release["quantity"]))
            if take > 0:
                releases.append({**release, "quantity": str(take)})
                need -= take


# -- worker absence repair (S5) -------------------------------------------------------------------------------------------


def on_workforce_changed(db: DbSession, event: Event) -> None:
    """HR could not cover some committed hours (HR-5: what is left after its own cover is AT_RISK). For each affected
    production order: inside the time fence, or already released or started, it is not changed automatically (RD-4)
    and reported as `PlanAtRisk`; otherwise Planning tries to move the missing hours to another day."""
    if not channel.is_newer(db, EventVersion, event):
        return
    for entry in event.payload.get("at_risk", []):
        try:
            order = db.get(ProductionOrder, uuid.UUID(entry["production_order_id"]), with_for_update=True)
        except ValueError:
            continue
        if order is None or order.status in ("CANCELLED", "COMPLETED"):
            continue
        missing = Decimal(entry["missing_hours"])
        skill = next((s["skill"] for s in order.steps if entry["day"] in s["hours_by_day"]), None)
        fence = today(db) + timedelta(days=int(setting(db, "time_fence_days")))
        if order.status != "FIRM" or order.start_day <= fence or skill is None:
            _plan_at_risk(db, order, entry["day"], skill, str(missing), "INSIDE_TIME_FENCE")
            continue
        _start_repair(db, order, skill, date.fromisoformat(entry["day"]), missing, entry["commitment_id"], fence)


def _start_repair(db: DbSession, order: ProductionOrder, skill: str, from_day: date, missing: Decimal,
                  commitment_id: str, fence: date) -> None:
    """Find the nearest other day with room for the missing hours (workers and machine): after the time fence, no
    later than the order's end day, and not before its start if a sub-assembly made here must be finished first.
    Then ask HR for those hours (a normal negotiation)."""
    step = next(s for s in order.steps if s["skill"] == skill and from_day.isoformat() in s["hours_by_day"])
    machine = min(missing / Decimal(step["crew"]), Decimal(step["hours_by_day"][from_day.isoformat()]))
    has_inputs_made_here = db.scalar(select(ProductionOrder.id).where(
        ProductionOrder.for_kind == "PRODUCTION_ORDER", ProductionOrder.for_ref == str(order.id),
        ProductionOrder.status != "CANCELLED")) is not None
    first = max(order.start_day, fence + timedelta(days=1)) if has_inputs_made_here else fence + timedelta(days=1)
    candidates = [first + timedelta(days=n) for n in range((order.end_day - first).days + 1)]
    candidates = sorted((d for d in candidates if d != from_day),
                        key=lambda d: (abs((d - from_day).days), -d.toordinal()))  # nearest; later first on a tie
    to_day = next((d for d in candidates
                   if Decimal(hr.free_worker_hours(db, skill, d, d)[d.isoformat()]) >= missing
                   and planner.machine_free(db, step["work_center"], d) >= machine), None)
    if to_day is None:
        _plan_at_risk(db, order, from_day.isoformat(), skill, str(missing), "NO_OTHER_DAY")
        return
    case = Case(id=planner.new_case_id(), demand_id=order.demand_id, option_id=order.option_id, kind="REPAIR",
                auto_commit=True, status="OPEN", sessions={}, depth=1)
    db.add(case)
    db.flush()
    _request(db, case, "HR", Terms(resource_type=ResourceType.WORKFORCE, resource_ref=skill, quantity=missing,
                                   unit="h", date_from=to_day, date_to=to_day, order_id=str(order.id),
                                   extra={"hours_by_day": {to_day.isoformat(): str(missing)}, "allow_overtime": True}),
             f"workers {skill} (repair)")
    session_id = next(iter(case.sessions))
    repair = {"order_id": str(order.id), "work_center": step["work_center"], "skill": skill,
              "commitment_id": commitment_id, "from_day": from_day.isoformat(), "to_day": to_day.isoformat(),
              "worker_hours": str(missing), "machine_hours": str(machine)}
    case.sessions = {session_id: {**case.sessions[session_id], "repair": repair}}
    _audit(db, "REPAIR_STARTED", case.id, **repair)


def _repair_of(case: Case) -> dict:
    return next(iter(case.sessions.values()))["repair"]


def _finish_repair(db: DbSession, case: Case) -> None:
    """HR committed the hours on the new day: move Planning's own machine-hours and the order's schedule, and ask HR
    (through `PlanRevised`) to release exactly the missing hours of the old day."""
    case.status = "COMMITTED"
    repair = _repair_of(case)
    order = db.get(ProductionOrder, uuid.UUID(repair["order_id"]), with_for_update=True)
    machine, from_day, to_day = Decimal(repair["machine_hours"]), repair["from_day"], repair["to_day"]
    ledger = LedgerWriter(db, MachineHoursLedger, f"{case.id}:repair", today(db))
    for day_text, delta in ((from_day, -machine), (to_day, machine)):
        row = _machine_day(db, repair["work_center"], date.fromisoformat(day_text))
        row.committed_hours += delta
        ledger.write(repair["work_center"], "COMMITTED", delta, "REPAIR", day=row.day, production_order=order.id)
    steps = []
    for step in order.steps:
        if step["work_center"] == repair["work_center"] and step["skill"] == repair["skill"]:
            hours = {d: Decimal(h) for d, h in step["hours_by_day"].items()}
            hours[from_day] -= machine
            hours[to_day] = hours.get(to_day, ZERO) + machine
            step = {**step, "hours_by_day": {d: str(h) for d, h in sorted(hours.items()) if h > 0}}
        steps.append(step)
    order.steps = steps
    order.start_day = min(date.fromisoformat(d) for s in steps for d in s["hours_by_day"])
    order.version += 1
    demand = db.get(CustomerDemand, order.demand_id, with_for_update=True)
    _publish_plan_event(db, demand, "PlanRevised", {
        "reason": "WORKFORCE_REPAIR", "production_order_id": str(order.id), "from_day": from_day, "to_day": to_day,
        "releases": [{"owner": "HR", "commitment_id": repair["commitment_id"], "day": from_day,
                      "hours": repair["worker_hours"]}]})


def _plan_at_risk(db: DbSession, order: ProductionOrder, day: str, skill: str | None, hours: str, reason: str) -> None:
    demand = db.get(CustomerDemand, order.demand_id, with_for_update=True)
    _publish_plan_event(db, demand, "PlanAtRisk", {
        "reason": reason, "production_order_id": str(order.id), "day": day, "skill": skill, "missing_hours": hours,
        "delivery_day": demand.committed_day.isoformat() if demand.committed_day else None})


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
        orders = db.scalars(select(ProductionOrder).where(ProductionOrder.demand_id == demand.id)).all()
        leftovers = _open_reservations(db, [str(demand.id), *[str(o.id) for o in orders]])
        if leftovers:
            _publish_plan_event(db, demand, "PlanRevised", {"reason": "ORDER_COMPLETED", "releases": leftovers})


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
    channel.subscribe(AGENT, "OrderCancelled", on_order_cancelled)
    channel.subscribe(AGENT, "WorkforceCapacityChanged", on_workforce_changed)
    channel.subscribe(AGENT, "OrderChangeRequested", on_order_change)
