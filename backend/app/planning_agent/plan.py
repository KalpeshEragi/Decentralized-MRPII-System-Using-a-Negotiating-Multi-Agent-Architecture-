"""Planning's calculation step (planning_agent/2 §3 methods 1–2): plan one request against the current committed and
held state (capable-to-promise, PL-2) and compute the options for Sales.

Reads only: `core` (items, BOM, routings), Inventory's and HR's read modules, Planning's own machine-hours. The pure
calculations are `app/mrpii` (multi-level MRP, backward scheduling on machine-hours and worker-hours).

A bought item that is short is bought through Purchasing (PI-6): the plan is feasible when Purchasing's estimate says
it can arrive the day before the production that uses it starts (deliveries are received in the morning routine,
before kits are issued).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.hr_agent import reads as hr
from app.inventory_agent import reads as inventory
from app.models.core import Bom, BomItem, Item, Routing
from app.mrpii.atp import Dated
from app.mrpii.hours import RoutingStep, round_hours_up as round_hours, schedule_backward
from app.mrpii.multilevel import BUY, MAKE, BomLine, Demand, ItemData, PlannedOrder, run_mrp
from app.planning_agent.models import WorkCenter, WorkCenterDay
from app.purchasing_agent import reads as purchasing
from app.simulation.clock import today
from app.simulation.settings import setting
from app.warehouse_agent import reads as warehouse

ZERO = Decimal(0)
DEMAND = "DEMAND"


@dataclass
class ProductionSpec:
    key: str  # "<item>@<need day>"
    item_id: str
    quantity: Decimal
    start_day: date
    end_day: date
    for_key: str  # DEMAND or the parent production key
    steps: list[dict]


@dataclass
class StockNeed:
    item_id: str
    quantity: Decimal
    needed_by: date
    for_key: str  # DEMAND (finished goods) or a production key (components)


@dataclass
class SupplyNeed:
    item_id: str
    quantity: Decimal
    needed_by: date  # arrival: the day before the production that uses it starts
    for_key: str  # the production key it is bought for


@dataclass
class PlanSpec:
    feasible: bool
    item_id: str
    quantity: Decimal
    delivery_day: date
    production: list[ProductionSpec] = field(default_factory=list)
    stock: list[StockNeed] = field(default_factory=list)
    supply: list[SupplyNeed] = field(default_factory=list)
    reason: str | None = None

    def to_json(self) -> dict:
        return {"item_id": self.item_id, "quantity": str(self.quantity), "delivery_day": self.delivery_day.isoformat(),
                "production": [{"key": p.key, "item_id": p.item_id, "quantity": str(p.quantity),
                                "start_day": p.start_day.isoformat(), "end_day": p.end_day.isoformat(),
                                "for_key": p.for_key, "steps": p.steps} for p in self.production],
                "stock": [{"item_id": s.item_id, "quantity": str(s.quantity), "needed_by": s.needed_by.isoformat(),
                           "for_key": s.for_key} for s in self.stock],
                "supply": [{"item_id": s.item_id, "quantity": str(s.quantity), "needed_by": s.needed_by.isoformat(),
                            "for_key": s.for_key} for s in self.supply]}


def machine_free(db: DbSession, work_center: str, day: date) -> Decimal:
    row = db.get(WorkCenterDay, (work_center, day))
    if row is not None:
        return row.capacity_hours - row.committed_hours - row.held_hours
    center = db.get(WorkCenter, work_center)
    return center.machine_hours_per_day if center else ZERO


def _master(db: DbSession):
    items = {str(i.id): i for i in db.scalars(select(Item).where(Item.is_active.is_(True)))}
    lines = []
    for bom in db.scalars(select(Bom).where(Bom.is_active.is_(True))):
        for line in db.scalars(select(BomItem).where(BomItem.bom_id == bom.id)):
            lines.append(BomLine(str(bom.parent_item_id), str(line.component_item_id), line.quantity_required))
    routings = defaultdict(list)
    for r in db.scalars(select(Routing)):
        routings[str(r.item_id)].append(RoutingStep(r.step_no, r.work_center_code, r.skill, r.crew_size,
                                                    r.setup_hours, r.run_hours_per_unit))
    return items, lines, routings


def _item_data(db: DbSession, item: Item) -> ItemData:
    position = inventory.stock_position(db, str(item.id))
    return ItemData(str(item.id), item.sourcing, on_hand=Decimal(position["on_hand"]),
                    safety_stock=Decimal(position["safety_stock"]),
                    incoming=tuple(Dated(date.fromisoformat(r["day"]), Decimal(r["quantity"])) for r in position["incoming"]),
                    promises=tuple(Dated(date.fromisoformat(p["day"]), Decimal(p["quantity"])) for p in position["promises"]))


class ReadFacts:
    """The other owners' facts read directly through their read modules — the old way. Still used for repairs,
    customer changes and the re-plan at confirmation; new requests plan from the owners' quotes (DC-1)."""

    def __init__(self, db: DbSession):
        self.db = db

    def item_data(self, item: Item) -> ItemData:
        return _item_data(self.db, item)

    def free_worker(self, skill: str, day: date) -> Decimal:
        return Decimal(hr.free_worker_hours(self.db, skill, day, day)[day.isoformat()])

    def free_receiving(self, day: date) -> Decimal:
        return Decimal(warehouse.free_receiving(self.db, day, day)[day.isoformat()])

    def supply_lead_time_days(self, item_id: str, quantity: Decimal) -> int | None:
        return purchasing.supply_lead_time_days(self.db, item_id, quantity)


def make_plan(db: DbSession, item_id: str, quantity: Decimal, due_day: date, facts=None) -> PlanSpec:
    """One plan for a request. `facts` gives the other owners' facts: their quotes (`quotes.QuoteFacts`, DC-1) or, by
    default, their read modules (`ReadFacts`). Planning's own machine-hours are always its own."""
    facts = facts or ReadFacts(db)
    start_of_today = today(db) + timedelta(days=1)  # today's morning routine (kits) has run: start tomorrow at the earliest
    items, bom, routings = _master(db)
    used = defaultdict(lambda: ZERO)  # hours this plan already takes, per (kind, resource, day)
    schedules: dict[str, list] = {}

    def free_machine(work_center: str, day: date) -> Decimal:
        return machine_free(db, work_center, day) - used[("M", work_center, day)]

    def free_worker(skill: str, day: date) -> Decimal:
        return facts.free_worker(skill, day) - used[("W", skill, day)]

    def receiving_day(earliest: date, latest: date, pieces: Decimal) -> date | None:
        """The latest day from `latest` back to `earliest` on which Warehouse can still receive the delivery
        (Warehouse's free receiving minus what this plan already puts on that day). Warehouse confirms it in the
        receiving-slot negotiation (WH-1); this only keeps the plan from counting on a full dock."""
        day = latest
        while day >= earliest:
            free = facts.free_receiving(day) - used[("R", "RECEIVING", day)]
            if free >= pieces:
                return day
            day -= timedelta(days=1)
        return None

    def production_start(made_item: str, made_quantity: Decimal, need_day: date) -> date | None:
        steps = routings.get(made_item)
        if not steps:
            return need_day  # no routing: available when needed (no capacity used)
        plan = schedule_backward(steps, made_quantity, need_day, start_of_today, free_machine, free_worker)
        if plan is None:
            return None
        for step in plan:
            for day, hours in step.hours_by_day.items():
                used[("M", step.work_center, day)] += hours
                used[("W", step.skill, day)] += hours * step.crew_size
        schedules[f"{made_item}@{need_day.isoformat()}"] = [
            {"work_center": s.work_center, "skill": s.skill, "crew": s.crew_size,
             "hours_by_day": {d.isoformat(): str(h) for d, h in sorted(s.hours_by_day.items())}} for s in plan]
        return plan[0].start_day

    data = {i: facts.item_data(items[i]) for i in items}
    result = run_mrp([Demand(item_id, quantity, due_day, DEMAND)], data, bom, production_start)
    spec = PlanSpec(True, item_id, quantity, due_day)
    needed = for_this_request(result.planned_orders)
    for order in (o for o in needed if o.sourcing == BUY):
        lead = facts.supply_lead_time_days(order.item_id, order.quantity)
        latest = order.need_day - timedelta(days=1)
        if lead is None or today(db) + timedelta(days=lead) > latest:
            spec.feasible, spec.reason = False, "MATERIAL_SHORTAGE"
            break
        arrival = receiving_day(today(db) + timedelta(days=lead), latest, order.quantity)
        if arrival is None:  # the dock is full on every day the supplier could deliver in time (WH-1, S4)
            spec.feasible, spec.reason = False, "NO_RECEIVING_CAPACITY"
            break
        used[("R", "RECEIVING", arrival)] += order.quantity
        spec.supply.append(SupplyNeed(order.item_id, order.quantity, arrival,
                                      order.source.removeprefix("planned:").replace(":", "@")))
    if result.unschedulable:
        spec.feasible, spec.reason = False, "NO_CAPACITY"
    if not spec.feasible:
        return spec

    children = defaultdict(list)
    for line in bom:
        children[line.parent_id].append(line)
    made = [o for o in needed if o.sourcing == MAKE]
    for order in made:
        key = f"{order.item_id}@{order.need_day.isoformat()}"
        for_key = DEMAND if order.source == DEMAND else order.source.removeprefix("planned:").replace(":", "@")
        spec.production.append(ProductionSpec(key, order.item_id, order.quantity, order.release_day,
                                              order.need_day - timedelta(days=1), for_key, schedules.get(key, [])))
    top_made = sum((o.quantity for o in made if o.source == DEMAND), ZERO)
    if quantity - top_made > 0:
        spec.stock.append(StockNeed(item_id, quantity - top_made, due_day, DEMAND))
    for production in spec.production:
        for line in children[production.item_id]:
            gross = production.quantity * line.quantity_per
            produced = sum((o.quantity for o in result.planned_orders if o.item_id == line.child_id and  # made or bought
                            o.source == f"planned:{production.item_id}:{production.end_day + timedelta(days=1)}"), ZERO)
            if gross - produced > 0:
                spec.stock.append(StockNeed(line.child_id, gross - produced, production.start_day, production.key))
    return spec


def for_this_request(planned: list[PlannedOrder]) -> list[PlannedOrder]:
    """The planned orders this request needs: those for its own demand, and the children of those. MRP also plans
    orders that cover other orders' promises or refill safety stock (no parent here); those are not this request's
    work (Planning refills on its own, RD-6) and must not become production or purchases with an unknown parent."""
    kept, keys = [], set()
    for order in sorted(planned, key=lambda o: o.level):  # parents (lower level) before their children
        parent = order.source.removeprefix("planned:").replace(":", "@")
        if order.source == DEMAND or (order.source.startswith("planned:") and parent in keys):
            kept.append(order)
            keys.add(f"{order.item_id}@{order.need_day.isoformat()}")
    return kept


def options(db: DbSession, item_id: str, quantity: Decimal, due_day: date, facts=None) -> list[tuple[str, PlanSpec]]:
    """REQUESTED if feasible; otherwise the earliest LATER_DATE (within the horizon) and the largest LESS_QUANTITY.
    In the order of PL-1 (the first one is the best option and gets holds)."""
    facts = facts or ReadFacts(db)
    requested = make_plan(db, item_id, quantity, due_day, facts)
    if requested.feasible:
        return [("REQUESTED", requested)]
    found = []
    for days in range(1, int(setting(db, "later_date_horizon_days")) + 1):
        later = make_plan(db, item_id, quantity, due_day + timedelta(days=days), facts)
        if later.feasible:
            found.append(("LATER_DATE", later))
            break
    low, high, best = Decimal(1), quantity - 1, None
    while low <= high:
        middle = ((low + high) / 2).to_integral_value(rounding="ROUND_FLOOR")
        attempt = make_plan(db, item_id, middle, due_day, facts)
        if attempt.feasible:
            best, low = attempt, middle + 1
        else:
            high = middle - 1
    if best is not None:
        found.append(("LESS_QUANTITY", best))
    return found


def new_case_id() -> str:
    return f"CASE-{uuid.uuid4().hex[:12].upper()}"
