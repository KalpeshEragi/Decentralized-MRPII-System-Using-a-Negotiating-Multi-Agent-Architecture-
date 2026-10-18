"""Warehouse Agent (warehouse_agent/1-3). Owner of receiving capacity, storage space and physical moves. Deterministic
(WH-5); template wording until the AI steps are switched on (IMP-2). One writer (WB-2) is a worker-count setting.

Space on day t (WD-1): free(t) = capacity − [occupied now + planned arrivals up to t − planned departures up to t]
− active holds covering t. Goods occupy space from their arrival day up to (not including) their until day.

Requests: STORAGE_SPACE (Planning, finished goods) and RECEIVING_SLOT (Purchasing, deliveries: receiving units on the
arrival day + MATERIALS space). Terms: resource_ref = zone ("FINISHED_GOODS") or "RECEIVING", quantity = pieces,
needed_by = arrival day, order_id = what it serves, extra = {"item_id", "until_day"}.
"""

import math
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.core.owner_tables import LedgerWriter
from app.events import channel
from app.events.models import Event
from app.inventory_agent import reads as inventory
from app.models.core import Bom, BomItem, Item
from app.mrpii.hours import round_space_up
from app.negotiation import layer
from app.negotiation.envelope import Envelope, Hold as HoldTerms, MessageType as M, ReasonCode, Terms
from app.negotiation.models import Session
from app.planning_agent import reads as planning
from app.simulation.clock import today
from app.simulation.settings import setting
from app.warehouse_agent.models import (AuditLog, DailyCapacity, EventVersion, Hold, ReceivingDay, ShippingDay,
                                        SpaceCommitment, SpaceLedger, SpaceMovement, Zone)

AGENT = "WAREHOUSE"
ZERO = Decimal(0)
MATERIALS, FINISHED_GOODS = "MATERIALS", "FINISHED_GOODS"


# -- space and capacity ----------------------------------------------------------------------------------------------------


def space_for(db: DbSession, item_id: str, quantity: Decimal) -> Decimal:
    item = db.get(Item, uuid.UUID(item_id))
    per_unit = item.space_per_unit if item is not None else ZERO
    return round_space_up(Decimal(quantity) * per_unit)


def free_space(db: DbSession, zone: str, day: date) -> Decimal:
    row = db.get(Zone, zone)
    if row is None:
        return ZERO
    arrivals = db.scalar(select(func.coalesce(func.sum(SpaceMovement.space_units), 0)).where(
        SpaceMovement.zone == zone, SpaceMovement.kind == "ARRIVAL", SpaceMovement.status == "PLANNED",
        SpaceMovement.planned_day <= day))
    departures = db.scalar(select(func.coalesce(func.sum(SpaceMovement.space_units), 0)).where(
        SpaceMovement.zone == zone, SpaceMovement.kind == "DEPARTURE", SpaceMovement.status == "PLANNED",
        SpaceMovement.planned_day <= day))
    held = sum((h.space_units for h in db.scalars(select(Hold).where(Hold.zone == zone, Hold.status == "ACTIVE",
                                                                     Hold.arrival_day <= day))
                if h.until_day is None or h.until_day > day), ZERO)
    return row.capacity_units - (row.occupied_now + Decimal(arrivals) - Decimal(departures)) - held


def free_receiving(db: DbSession, day: date) -> Decimal:
    capacity = db.get(DailyCapacity, "RECEIVING")
    row = db.get(ReceivingDay, day)
    used = (row.committed_units + row.held_units) if row else ZERO
    return (capacity.units if capacity else ZERO) - used


def _receiving_day(db: DbSession, day: date) -> ReceivingDay:
    row = db.get(ReceivingDay, day, with_for_update=True)
    if row is None:
        row = ReceivingDay(day=day, committed_units=ZERO, held_units=ZERO, used_units=ZERO)
        db.add(row)
        db.flush()
    return row


def fits(db: DbSession, zone: str, space: Decimal, arrival: date, until: date | None, receiving: Decimal) -> bool:
    """The capacity rule for every day of the stay (and receiving on the arrival day)."""
    if receiving > 0 and receiving > free_receiving(db, arrival):
        return False
    last = until or (arrival + timedelta(days=int(setting(db, "later_date_horizon_days"))))
    day = arrival
    while day < last or day == arrival:
        if space > free_space(db, zone, day):
            return False
        day += timedelta(days=1)
    return True


# -- the answer rule (same shape as IF-1) ----------------------------------------------------------------------------------


def _request(db: DbSession, terms: Terms) -> tuple[str, str, Decimal, Decimal, date, date | None]:
    """(kind, zone, space units, receiving units, arrival, until) of a request."""
    item_id = terms.extra["item_id"]
    until = date.fromisoformat(terms.extra["until_day"]) if terms.extra.get("until_day") else None
    arrival = terms.needed_by or terms.available_from or today(db)
    if terms.resource_ref == "RECEIVING":
        return "DELIVERY", MATERIALS, space_for(db, item_id, terms.quantity), terms.quantity, arrival, until
    return "FINISHED_GOODS", terms.resource_ref, space_for(db, item_id, terms.quantity), ZERO, arrival, until


def answer(db: DbSession, terms: Terms) -> tuple[M, Terms | None, ReasonCode | None]:
    kind, zone, space, receiving, arrival, until = _request(db, terms)
    reason = ReasonCode.NO_RECEIVING_CAPACITY if kind == "DELIVERY" and receiving > free_receiving(db, arrival) \
        else ReasonCode.NO_SPACE
    if fits(db, zone, space, arrival, until, receiving):
        return M.OFFER, terms.model_copy(update={"available_from": arrival}), None
    stay = (until - arrival) if until else None
    for shift in range(1, int(setting(db, "later_date_horizon_days")) + 1):
        later = arrival + timedelta(days=shift)
        later_until = later + stay if stay is not None else None
        if fits(db, zone, space, later, later_until, receiving):
            extra = {**terms.extra, "until_day": later_until.isoformat() if later_until else None}
            return M.COUNTER_OFFER, terms.model_copy(update={"needed_by": later, "available_from": later,
                                                             "extra": extra}), reason
    item = db.get(Item, uuid.UUID(terms.extra["item_id"]))
    per_unit = item.space_per_unit if item is not None and item.space_per_unit > 0 else None
    room = min((free_space(db, zone, arrival + timedelta(days=n)) for n in range(max(1, (stay or timedelta(1)).days))),
               default=ZERO)
    if kind == "DELIVERY":
        room_pieces = min(free_receiving(db, arrival), Decimal(math.floor(room / per_unit)) if per_unit else room)
    else:
        room_pieces = Decimal(math.floor(room / per_unit)) if per_unit else ZERO
    if room_pieces > 0:
        return M.COUNTER_OFFER, terms.model_copy(update={"quantity": room_pieces, "available_from": arrival}), reason
    return M.REJECT, None, reason


def _reply(db: DbSession, message: Envelope, kind: M, terms: Terms | None = None, reason: ReasonCode | None = None,
           hold: HoldTerms | None = None) -> None:
    text = f"{kind.value.lower()}" + (f": {terms.quantity} pcs in {terms.resource_ref} from "
                                      f"{terms.available_from or terms.needed_by}" if terms else "") + \
           (f" ({reason.value.lower()})" if reason else "")
    layer.send(db, layer.reply_to(message, kind, terms=terms, reason_code=reason, hold=hold, text=text))


def _zone_change(ledger: LedgerWriter, zone: Zone, delta: Decimal, reason: str, **refs) -> None:
    zone.occupied_now = max(ZERO, zone.occupied_now + delta)  # initial material occupancy is a configured estimate
    zone.version += 1
    ledger.write(zone.zone, "OCCUPIED", delta, reason, **refs)


# -- inbox -----------------------------------------------------------------------------------------------------------------------


def handle_message(db: DbSession, message: Envelope, session: Session) -> None:
    kind = message.message_type
    if kind in (M.REQUEST, M.COUNTER_OFFER):
        reply_kind, terms, reason = answer(db, message.terms)
        _reply(db, message, reply_kind, terms, reason)
    elif kind == M.ACCEPT and session.status == "NEGOTIATING":
        _place_hold(db, message, session)
    elif kind == M.COMMIT:
        _commit(db, message, session)
    elif kind == M.ABORT:
        _release(db, str(session.id), message.message_id, "HOLD_ABORTED", "ABORTED")


def _place_hold(db: DbSession, message: Envelope, session: Session) -> None:
    offer = Terms.model_validate(session.last_offer)
    kind, zone, space, receiving, arrival, until = _request(db, offer)
    if not fits(db, zone, space, arrival, until, receiving):
        _reply(db, message, M.REJECT, reason=ReasonCode.STALE)
        return
    expires_day = today(db) + timedelta(days=int(setting(db, "hold_validity_days")))
    hold = Hold(kind=kind, zone=zone, item_id=offer.extra["item_id"], quantity=offer.quantity, space_units=space,
                receiving_units=receiving, arrival_day=arrival, until_day=until,
                for_ref=offer.order_id or session.case_id, case_id=session.case_id, negotiation_id=str(session.id),
                expires_day=expires_day, status="ACTIVE")
    db.add(hold)
    db.flush()
    ledger = LedgerWriter(db, SpaceLedger, message.message_id, today(db))
    ledger.write(zone, "HELD", space, "HOLD", day=arrival, hold=hold.id)
    if receiving > 0:
        _receiving_day(db, arrival).held_units += receiving
        ledger.write("RECEIVING", "RECEIVING_HELD", receiving, "HOLD", day=arrival, hold=hold.id)
    expires_at = datetime.combine(expires_day, time.min, tzinfo=timezone.utc)
    _reply(db, message, M.AGREEMENT_PROPOSED, offer, hold=HoldTerms(hold_id=str(hold.id), expires_at=expires_at))


def _commit(db: DbSession, message: Envelope, session: Session) -> None:
    hold = db.scalar(select(Hold).where(Hold.negotiation_id == str(session.id)).with_for_update())
    if hold is None or hold.status != "ACTIVE":
        _reply(db, message, M.REJECT, reason=ReasonCode.UNAVAILABLE if hold is None else ReasonCode.HOLD_EXPIRED)
        return
    commitment = SpaceCommitment(kind=hold.kind, zone=hold.zone, item_id=hold.item_id, quantity=hold.quantity,
                                 space_units=hold.space_units, arrival_day=hold.arrival_day, until_day=hold.until_day,
                                 for_ref=hold.for_ref, case_id=hold.case_id, negotiation_id=hold.negotiation_id,
                                 status="ACTIVE", version=1)
    db.add(commitment)
    db.flush()
    db.add(SpaceMovement(commitment_id=commitment.id, zone=hold.zone, kind="ARRIVAL", space_units=hold.space_units,
                         planned_day=hold.arrival_day, status="PLANNED"))
    if hold.until_day is not None:
        db.add(SpaceMovement(commitment_id=commitment.id, zone=hold.zone, kind="DEPARTURE",
                             space_units=hold.space_units, planned_day=hold.until_day, status="PLANNED"))
    ledger = LedgerWriter(db, SpaceLedger, message.message_id, today(db))
    ledger.write(hold.zone, "HELD", -hold.space_units, "COMMIT", day=hold.arrival_day, hold=hold.id)
    ledger.write(hold.zone, "PLANNED_ARRIVAL", hold.space_units, "COMMIT", day=hold.arrival_day,
                 commitment=commitment.id)
    if hold.receiving_units > 0:
        row = _receiving_day(db, hold.arrival_day)
        row.held_units -= hold.receiving_units
        row.committed_units += hold.receiving_units
        ledger.write("RECEIVING", "RECEIVING_COMMITTED", hold.receiving_units, "COMMIT", day=hold.arrival_day,
                     commitment=commitment.id)
        channel.publish(db, event_type="ReceivingSlotCommitted", publisher=AGENT, entity_type="space_commitment",
                        entity_id=str(commitment.id), entity_version=1, correlation_id=hold.case_id,
                        payload={"commitment_id": str(commitment.id), "for_ref": hold.for_ref,
                                 "arrival_day": hold.arrival_day.isoformat(), "item_id": hold.item_id,
                                 "quantity": str(hold.quantity), "space_units": str(hold.space_units)})
    hold.status = "COMMITTED"
    _reply(db, message, M.ACCEPT)


def _release(db: DbSession, negotiation_id: str, source_id: str, reason: str, status: str) -> None:
    hold = db.scalar(select(Hold).where(Hold.negotiation_id == negotiation_id).with_for_update())
    if hold is None or hold.status != "ACTIVE":
        return
    ledger = LedgerWriter(db, SpaceLedger, f"{source_id}:{hold.id}", today(db))
    ledger.write(hold.zone, "HELD", -hold.space_units, reason, day=hold.arrival_day, hold=hold.id)
    if hold.receiving_units > 0:
        _receiving_day(db, hold.arrival_day).held_units -= hold.receiving_units
        ledger.write("RECEIVING", "RECEIVING_HELD", -hold.receiving_units, reason, day=hold.arrival_day,
                     hold=hold.id)
    hold.status = status


# -- physical moves -------------------------------------------------------------------------------------------------------


def store_finished_goods(db: DbSession, event: Event) -> None:
    """ProductionCompleted: put the goods away -> FinishedGoodsStored. Goods for a customer demand go to their
    committed finished-goods space; a sub-assembly for another production order goes to the materials zone."""
    if not channel.is_newer(db, EventVersion, event):
        return
    payload = event.payload
    quantity = Decimal(payload["quantity"])
    for_customer = payload.get("for_kind", "CUSTOMER_DEMAND") == "CUSTOMER_DEMAND"
    zone_name = FINISHED_GOODS if for_customer else MATERIALS
    commitment = db.scalar(select(SpaceCommitment).where(
        SpaceCommitment.for_ref == payload["order_ref"], SpaceCommitment.kind == "FINISHED_GOODS",
        SpaceCommitment.status == "ACTIVE").with_for_update()) if for_customer else None
    zone = db.get(Zone, zone_name, with_for_update=True)
    ledger = LedgerWriter(db, SpaceLedger, str(event.event_id), today(db))
    if commitment is not None:
        arrival = db.scalar(select(SpaceMovement).where(SpaceMovement.commitment_id == commitment.id,
                                                        SpaceMovement.kind == "ARRIVAL"))
        arrival.status = "DONE"
        ledger.write(FINISHED_GOODS, "PLANNED_ARRIVAL", -arrival.space_units, "FG_STORED", commitment=commitment.id)
        commitment.status = "IN_USE"
    _zone_change(ledger, zone, space_for(db, payload["item_id"], quantity), "FG_STORED", order=payload["order_ref"])
    channel.publish(db, event_type="FinishedGoodsStored", publisher=AGENT, entity_type="put_away",
                    entity_id=str(event.event_id), entity_version=1,  # each put-away is its own fact
                    correlation_id=event.correlation_id, causation_id=event.event_id,
                    payload={"order_ref": payload["order_ref"], "production_order_id": payload["production_order_id"],
                             "item_id": payload["item_id"], "quantity": str(quantity), "zone": zone_name,
                             "for_kind": payload.get("for_kind", "CUSTOMER_DEMAND"),
                             "for_ref": payload.get("for_ref", payload["order_ref"])})


def issue_kits(db: DbSession, production_order_id: str, quantity: Decimal, components: list[dict],
               correlation_id: str, source_id: str) -> Decimal:
    """WF-1: issue only complete kits for a production order starting today. `components` = [{item_id, quantity_per}].
    Returns the number of kits issued; MaterialIssuedToProduction reports issued and missing per component."""
    reserved = {}
    for row in inventory.reservations_for(db, production_order_id):
        if row["kind"] == "RESERVATION" and row["status"] in ("ACTIVE", "AT_RISK"):
            reserved[row["item_id"]] = reserved.get(row["item_id"], ZERO) + Decimal(row["quantity"]) - \
                Decimal(row["issued"])
    available = {}
    for component in components:
        on_hand = Decimal(inventory.stock_position(db, component["item_id"])["on_hand"])
        available[component["item_id"]] = min(on_hand, reserved.get(component["item_id"], ZERO))
    kits = min([Decimal(math.floor(available[c["item_id"]] / Decimal(str(c["quantity_per"])))) for c in components]
               + [Decimal(quantity)])
    lines = []
    zone = db.get(Zone, MATERIALS, with_for_update=True)
    ledger = LedgerWriter(db, SpaceLedger, source_id, today(db))
    for component in components:
        needed = Decimal(quantity) * Decimal(str(component["quantity_per"]))
        issued = kits * Decimal(str(component["quantity_per"]))
        lines.append({"item_id": component["item_id"], "issued": str(issued), "missing": str(needed - issued)})
        if issued > 0 and zone is not None:
            _zone_change(ledger, zone, -space_for(db, component["item_id"], issued), "ISSUE",
                         production_order=production_order_id)
    channel.publish(db, event_type="MaterialIssuedToProduction", publisher=AGENT, entity_type="production_order",
                    entity_id=production_order_id, entity_version=today(db).toordinal(), correlation_id=correlation_id,
                    payload={"production_order_id": production_order_id, "kits": str(kits), "components": lines})
    return kits


def ship(db: DbSession, order_ref: str, item_id: str, quantity: Decimal, correlation_id: str, source_id: str) -> Decimal:
    """Ship finished goods of an order today within the daily shipping capacity. Returns the quantity shipped."""
    day = today(db)
    capacity = db.get(DailyCapacity, "SHIPPING")
    row = db.get(ShippingDay, day, with_for_update=True)
    if row is None:
        row = ShippingDay(day=day, used_units=ZERO)
        db.add(row)
        db.flush()
    shipped = min(Decimal(quantity), max(ZERO, (capacity.units if capacity else ZERO) - row.used_units))
    if shipped <= 0:
        return ZERO
    row.used_units += shipped
    zone = db.get(Zone, FINISHED_GOODS, with_for_update=True)
    ledger = LedgerWriter(db, SpaceLedger, source_id, day)
    ledger.write("SHIPPING", "SHIPPING_USED", shipped, "SHIPMENT", day=day, order=order_ref)
    _zone_change(ledger, zone, -space_for(db, item_id, shipped), "SHIPMENT", order=order_ref)
    commitment = db.scalar(select(SpaceCommitment).where(SpaceCommitment.for_ref == order_ref,
                                                         SpaceCommitment.kind == "FINISHED_GOODS",
                                                         SpaceCommitment.status == "IN_USE"))
    if commitment is not None and shipped >= commitment.quantity:
        for movement in db.scalars(select(SpaceMovement).where(SpaceMovement.commitment_id == commitment.id,
                                                               SpaceMovement.kind == "DEPARTURE")):
            movement.status = "DONE"
        commitment.status = "FREED"
    channel.publish(db, event_type="ShipmentDispatched", publisher=AGENT, entity_type="order", entity_id=order_ref,
                    entity_version=day.toordinal(),
                    correlation_id=correlation_id,
                    payload={"order_ref": order_ref, "item_id": item_id, "quantity": str(shipped),
                             "date": day.isoformat()})
    return shipped


def expire_holds(db: DbSession, event: Event) -> None:
    day = date.fromisoformat(event.payload["date"])
    for hold in db.scalars(select(Hold).where(Hold.status == "ACTIVE", Hold.expires_day <= day)).all():
        session = db.get(Session, uuid.UUID(hold.negotiation_id))
        _release(db, hold.negotiation_id, str(event.event_id), "HOLD_EXPIRED", "EXPIRED")
        if session is not None and session.status == "AGREEMENT_PROPOSED":
            layer.send(db, Envelope(message_id=str(uuid.uuid4()), session_id=str(session.id), case_id=session.case_id,
                                    sender=AGENT, receiver=session.starter, message_type=M.REJECT,
                                    reason_code=ReasonCode.HOLD_EXPIRED, text="hold expired",
                                    sent_at=datetime.now(timezone.utc)))


def components_of(db: DbSession, item_id: str) -> list[dict]:
    """The kit of one unit of `item_id` from the shared BOM (master data): [{item_id, quantity_per}]."""
    bom = db.scalar(select(Bom).where(Bom.parent_item_id == uuid.UUID(item_id), Bom.is_active.is_(True)))
    if bom is None:
        return []
    return [{"item_id": str(line.component_item_id), "quantity_per": str(line.quantity_required)}
            for line in db.scalars(select(BomItem).where(BomItem.bom_id == bom.id))]


def run_day(db: DbSession, event: Event) -> None:
    """The daily routine (WB-3), in order: expire holds -> (receive: step 6) -> issue kits -> ship."""
    expire_holds(db, event)
    day = date.fromisoformat(event.payload["date"])
    source = str(event.event_id)
    for order in planning.production_orders_starting(db, day):
        components = components_of(db, order["item_id"])
        if components:
            issue_kits(db, order["id"], Decimal(order["quantity"]), components, event.correlation_id,
                       f"{source}:kits:{order['id']}")
    for due in planning.shipments_due(db, day):
        reserved = inventory.reservations_for(db, due["order_ref"])
        ready = sum((Decimal(r["quantity"]) - Decimal(r["issued"]) for r in reserved if r["kind"] == "RESERVATION"
                     and r["item_id"] == due["item_id"] and r["status"] in ("ACTIVE", "AT_RISK")), ZERO)
        if ready > 0:
            ship(db, due["order_ref"], due["item_id"], ready, event.correlation_id, f"{source}:ship:{due['order_ref']}")


# -- setup and registration -------------------------------------------------------------------------------------------


def setup(db: DbSession, config: dict) -> None:
    """{"zones": {zone: {"capacity_units", "occupied_now"}}, "receiving_units_per_day", "shipping_units_per_day"}."""
    for name, values in config.get("zones", {}).items():
        if name not in (MATERIALS, FINISHED_GOODS):
            raise ValueError(f"unknown zone {name}")
        zone = db.get(Zone, name) or Zone(zone=name, occupied_now=ZERO, version=0)
        zone.capacity_units = Decimal(str(values["capacity_units"]))
        zone.occupied_now = Decimal(str(values.get("occupied_now", zone.occupied_now or 0)))
        db.merge(zone)
    for resource, key in (("RECEIVING", "receiving_units_per_day"), ("SHIPPING", "shipping_units_per_day")):
        if key in config:
            db.merge(DailyCapacity(resource=resource, units=Decimal(str(config[key]))))
    db.flush()


def register(runner_register) -> None:
    runner_register(layer.register_inbox(AGENT, handle_message))
    channel.subscribe(AGENT, "ProductionCompleted", store_finished_goods)
    channel.subscribe(AGENT, "SimulatedDayStarted", run_day)
