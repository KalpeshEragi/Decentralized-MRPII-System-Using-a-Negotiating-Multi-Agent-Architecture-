"""Planning plans a new customer request from the owners' quotes (DC-1, QD-1), not from their data.

1. `start`: Planning works out what the request could involve from its own master data (the product's BOM tree and
   routings) and asks the owners in parallel, with QUOTE_REQUEST (non-binding, nothing held):
     Inventory   — every item of the tree: what can you promise, from which day?
     Purchasing  — every bought item: which supplier options do you have?
     HR          — every skill of the routings: how many hours are free per day?
     Warehouse   — how much can the receiving dock take per day?
2. `on_answer`: each QUOTE (or REJECT = nothing to offer) is stored in the quote round.
3. `finish`: when every owner answered, Planning runs its own MRP and backward scheduling on the quotes
   (`QuoteFacts`): what the quoted stock covers comes from stock, a made item short of stock gets a production order,
   a bought item short of stock is bought with the quoted supplier options (make or buy, recorded as Planning's
   decision). Then it secures the best option exactly as before (binding REQUEST → hold → commit, each owner
   re-checks its own facts).
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.agent_decisions import Decision, Situation, record
from app.models.core import Bom, BomItem, Item, Routing
from app.mrpii.atp import Dated
from app.mrpii.multilevel import ItemData
from app.negotiation import layer
from app.negotiation.envelope import Envelope, MessageType as M, ResourceType, Terms
from app.negotiation.quoting import value_on
from app.planning_agent.models import AuditLog, CustomerDemand, QuoteRound
from app.simulation.clock import today
from app.simulation.settings import setting

AGENT = "PLANNING"
ZERO = Decimal(0)


# -- 1. asking ----------------------------------------------------------------------------------------------------------


def start(db: DbSession, demand: CustomerDemand) -> QuoteRound:
    """Ask every owner for its quote (caller holds the demand's lock and commits)."""
    items, children, routings = _tree(db, demand.item_id)
    first = today(db)
    last = max(demand.requested_day, first) + timedelta(days=int(setting(db, "later_date_horizon_days")) + 1)
    quote = QuoteRound(id=f"QUOTE-{uuid.uuid4().hex[:12].upper()}", demand_id=demand.id, status="QUOTING", sessions={})
    db.add(quote)
    db.flush()

    def ask(owner: str, resource: ResourceType, ref: str, need: str, unit: str = "pcs") -> None:
        session_id = str(uuid.uuid4())
        quote.sessions = {**quote.sessions, session_id: {"owner": owner, "need": need, "resource": resource.value,
                                                         "ref": ref, "status": "QUOTING", "options": []}}
        terms = Terms(resource_type=resource, resource_ref=ref, quantity=demand.quantity, unit=unit, date_from=first,
                      date_to=last, order_id=str(demand.id))
        layer.send(db, Envelope(message_id=str(uuid.uuid4()), session_id=session_id, case_id=quote.id, sender=AGENT,
                                receiver=owner, message_type=M.QUOTE_REQUEST, terms=terms,
                                text=f"quote request: {need}", sent_at=datetime.now(timezone.utc)))

    for item in items.values():
        ask("INVENTORY", ResourceType.STOCK, str(item.id), f"stock {item.sku}")
        if item.sourcing == "BUY":
            ask("PURCHASING", ResourceType.SUPPLY, str(item.id), f"supply {item.sku}")
    for skill in sorted({step.skill for steps in routings.values() for step in steps}):
        ask("HR", ResourceType.WORKFORCE, skill, f"workers {skill}", unit="h")
    ask("WAREHOUSE", ResourceType.RECEIVING_SLOT, "RECEIVING", "receiving dock")
    db.add(AuditLog(actor="SYSTEM", event_type="QUOTES_REQUESTED", case_id=quote.id,
                    details={"demand_id": str(demand.id), "asked": len(quote.sessions), "window": [first.isoformat(),
                                                                                                   last.isoformat()]}))
    return quote


def _tree(db: DbSession, item_id: str):
    """The product, everything below it in its BOM, and the routings of what is made."""
    lines = defaultdict(list)
    for bom in db.scalars(select(Bom).where(Bom.is_active.is_(True))):
        for line in db.scalars(select(BomItem).where(BomItem.bom_id == bom.id)):
            lines[str(bom.parent_item_id)].append(str(line.component_item_id))
    found, todo = {}, [item_id]
    while todo:
        current = todo.pop()
        if current in found:
            continue
        item = db.get(Item, uuid.UUID(current))
        if item is None:
            continue
        found[current] = item
        todo += lines.get(current, [])
    routings = {i: db.scalars(select(Routing).where(Routing.item_id == uuid.UUID(i))).all()
                for i, item in found.items() if item.sourcing == "MAKE"}
    return found, lines, routings


# -- 2. collecting ------------------------------------------------------------------------------------------------------


def on_answer(db: DbSession, quote: QuoteRound, message: Envelope) -> bool:
    """Store one owner's QUOTE (or REJECT: nothing to offer). Returns True when every owner has answered."""
    sid = message.session_id
    if quote.status != "QUOTING" or sid not in quote.sessions:
        return False
    options = [o.model_dump(mode="json") for o in (message.options or [])]
    status = "QUOTED" if message.message_type == M.QUOTE else "REJECTED"
    quote.sessions = {**quote.sessions, sid: {**quote.sessions[sid], "status": status, "options": options}}
    return all(s["status"] != "QUOTING" for s in quote.sessions.values())


# -- 3. planning from the quotes -----------------------------------------------------------------------------------------


class QuoteFacts:
    """The other owners' facts as they quoted them (DC-1). Same questions as `plan.ReadFacts`, answered from quotes."""

    def __init__(self, quote: QuoteRound):
        self.stock, self.supply, self.hours, self.receiving = {}, {}, {}, []
        for s in quote.sessions.values():
            options = s["options"]
            if s["owner"] == "INVENTORY":
                self.stock[s["ref"]] = options
            elif s["owner"] == "PURCHASING":
                self.supply[s["ref"]] = options
            elif s["owner"] == "HR":
                self.hours[s["ref"]] = options
            elif s["owner"] == "WAREHOUSE":
                self.receiving = options

    def item_data(self, item: Item) -> ItemData:
        """What Inventory promised, as stock now plus what becomes promisable later (its safety stock already kept
        back, so none here). An item Inventory did not quote has nothing."""
        steps = sorted((Terms.model_validate(o) for o in self.stock.get(str(item.id), [])),
                       key=lambda o: o.available_from or date.min)
        if not steps:
            return ItemData(str(item.id), item.sourcing, on_hand=ZERO, safety_stock=ZERO, incoming=(), promises=())
        incoming, promises = [], []
        for before, after in zip(steps, steps[1:]):
            change = after.quantity - before.quantity
            (incoming if change > 0 else promises).append(Dated(after.available_from, abs(change)))
        return ItemData(str(item.id), item.sourcing, on_hand=steps[0].quantity, safety_stock=ZERO,
                        incoming=tuple(incoming), promises=tuple(promises))

    def free_worker(self, skill: str, day: date) -> Decimal:
        return value_on(self.hours.get(skill, []), day)

    def free_receiving(self, day: date) -> Decimal:
        return value_on(self.receiving, day)

    def supply_lead_time_days(self, item_id: str, quantity: Decimal) -> int | None:
        """Days until `quantity` could arrive from Purchasing's quoted suppliers (fastest first, together enough)."""
        covered = ZERO
        for option in sorted((Terms.model_validate(o) for o in self.supply.get(item_id, [])),
                             key=lambda o: o.extra.get("lead_time_days", 999)):
            covered += option.quantity
            if covered >= quantity:
                return int(option.extra["lead_time_days"])
        return None


def finish(db: DbSession, quote: QuoteRound) -> None:
    """Every owner answered: plan from the quotes and secure the best option (caller holds the locks, commits)."""
    from app.planning_agent import manager

    quote.status = "PLANNED"
    demand = db.get(CustomerDemand, quote.demand_id, with_for_update=True)
    if demand is None or demand.status != "PLANNING":
        return
    facts = QuoteFacts(quote)
    found = manager.plan_with(db, demand, facts)
    _record_make_or_buy(db, quote, demand, found)


def _record_make_or_buy(db: DbSession, quote: QuoteRound, demand: CustomerDemand, found) -> None:
    """Planning's decision from the quotes: what comes from stock, what is made, what is bought (recorded like every
    agent decision, so it shows in the agent drawer and the timeline). The model chooses here in a later step (AB)."""
    skus = {str(i.id): i.sku for i in db.scalars(select(Item))}
    asked = {s["owner"] for s in quote.sessions.values()}
    if not found:
        action, params = "NOTHING_FEASIBLE", {}
    else:
        kind, spec = found[0]
        action = f"PLAN_{kind}"
        params = {"quantity": str(spec.quantity), "delivery_day": spec.delivery_day.isoformat(),
                  "from_stock": [f"{n.quantity} {skus.get(n.item_id, '?')}" for n in spec.stock],
                  "make": [f"{p.quantity} {skus.get(p.item_id, '?')} ({p.start_day}..{p.end_day})" for p in spec.production],
                  "buy": [f"{s.quantity} {skus.get(s.item_id, '?')} (arrives {s.needed_by})" for s in spec.supply]}
    situation = Situation(
        agent=AGENT, point="D6", goal="Plan the order from the owners' quotes: stock first, make what is made, buy what "
                                      "is bought, on time and without touching other orders' commitments.",
        facts={"order": {"quantity": str(demand.quantity), "wanted_by": demand.requested_day.isoformat()},
               "quotes_from": sorted(asked),
               "quotes": {s["need"]: len(s["options"]) for s in quote.sessions.values()}},
        actions={"PLAN": "the MRP plan built from the quotes"}, case_id=quote.id, order_id=str(demand.id))
    record(db, AuditLog, situation, Decision(action, params, "FALLBACK", reason="make or buy from the quotes "
                                             "(deterministic MRP; the agent's own choice comes with AB-1)",
                                             fallback=(action, params), fallback_reason="DETERMINISTIC_POLICY"))
