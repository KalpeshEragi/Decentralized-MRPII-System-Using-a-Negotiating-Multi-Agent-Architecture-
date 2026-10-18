"""Inventory Agent (inventory_agent/1-3). Responder only (IN-3); every decision is deterministic code (IN-4); wording is
a template until the AI steps are switched on (IMP-2).

- `handle_message`: inbox handler for stock negotiations (IF-1 answer rule, RD-6 safety-stock release, holds,
  commits, aborts).
- event handlers: day start (hold expiry), material issued, finished goods stored, shipment, plan revised (releases).
- `setup`: starting stock and safety stock (simulator configuration, demo.md §4).

Every quantity change = ledger row(s) + balance update in the caller's transaction (QA-1), under a row lock on the
item's balance (quantity_accounting.md §9).
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.owner_tables import LedgerWriter
from app.events import channel
from app.events.models import Event
from app.inventory_agent.models import AuditLog, EventVersion, Hold, IncomingReceipt, Reservation, StockBalance, StockLedger
from app.mrpii.atp import Dated, atp, earliest_full_date
from app.negotiation import layer
from app.negotiation.envelope import Envelope, Hold as HoldTerms, MessageType as M, ReasonCode, Terms
from app.negotiation.models import Session
from app.simulation.clock import today
from app.simulation.settings import setting

AGENT = "INVENTORY"
ZERO = Decimal(0)


# -- balances, ledger and the promise profile --------------------------------------------------------------------------


def balance(db: DbSession, item_id: str, lock: bool = True) -> StockBalance:
    row = db.get(StockBalance, item_id, with_for_update=lock)
    if row is None:
        row = StockBalance(item_id=item_id, on_hand=ZERO, reserved=ZERO, held=ZERO, incoming_total=ZERO,
                           safety_stock=ZERO, safety_stock_released=ZERO, version=0)
        db.add(row)
        db.flush()
    return row


def change(ledger: LedgerWriter, row: StockBalance, bucket: str, delta: Decimal, reason: str, **refs) -> None:
    """One quantity change: ledger row + balance column, in the same transaction."""
    if Decimal(delta) == 0:
        return
    column = {"ON_HAND": "on_hand", "RESERVED": "reserved", "HELD": "held", "INCOMING": "incoming_total",
              "SAFETY_STOCK": "safety_stock", "SAFETY_STOCK_USE": "safety_stock_released"}[bucket]
    new_value = getattr(row, column) + Decimal(delta)
    if new_value < 0:
        raise ValueError(f"{column} of item {row.item_id} would go below 0")
    setattr(row, column, new_value)
    row.version += 1
    ledger.write(row.item_id, bucket, Decimal(delta), reason, **refs)


def profile(db: DbSession, item_id: str) -> tuple[list[Dated], list[Dated]]:
    """(incoming receipts, promises) of an item, for ATP (QA-4)."""
    incoming = [Dated(r.expected_day, r.quantity - r.quantity_received, str(r.id))
                for r in db.scalars(select(IncomingReceipt).where(IncomingReceipt.item_id == item_id,
                                                                  IncomingReceipt.status.in_(("EXPECTED", "PARTLY_RECEIVED")),
                                                                  IncomingReceipt.for_ref.is_(None)))]  # pegged: not free
    promises = [Dated(h.due_day, h.quantity, str(h.id))
                for h in db.scalars(select(Hold).where(Hold.item_id == item_id, Hold.status == "ACTIVE"))]
    promises += [Dated(r.due_day, r.quantity - r.quantity_issued, str(r.id))
                 for r in db.scalars(select(Reservation).where(Reservation.item_id == item_id,
                                                               Reservation.status.in_(("ACTIVE", "AT_RISK"))))]
    return incoming, promises


def atp_on(db: DbSession, row: StockBalance, day: date) -> Decimal:
    incoming, promises = profile(db, row.item_id)
    return atp(day, row.on_hand, incoming, promises, row.safety_stock)


def _audit(db: DbSession, event_type: str, case_id: str | None, **details) -> None:
    db.add(AuditLog(actor="SYSTEM", event_type=event_type, case_id=case_id,
                    details={k: str(v) if isinstance(v, (Decimal, date)) else v for k, v in details.items()}))


# -- the answer rule (IF-1 with RD-6) -------------------------------------------------------------------------------------


def safety_release_allowed(db: DbSession, row: StockBalance, shortfall: Decimal, needed_by: date) -> Decimal:
    """RD-6: the minimum shortfall, only for urgent requests, within the configured share, never uncovering another
    promise (S(t) - C(t) >= 0 after the release). 0 if not allowed."""
    slack = (needed_by - today(db)).days
    limit = Decimal(str(setting(db, "safety_stock_release_share"))) * row.safety_stock - row.safety_stock_released
    if shortfall <= 0 or slack > int(setting(db, "safety_stock_max_slack_days")) or shortfall > limit:
        return ZERO
    incoming, promises = profile(db, row.item_id)
    if atp(needed_by, row.on_hand, incoming, promises, ZERO) < shortfall + atp_on(db, row, needed_by):
        return ZERO
    return shortfall


def answer(db: DbSession, terms: Terms) -> tuple[M, Terms | None, ReasonCode | None]:
    """IF-1: offer, counter (full quantity later, else the most by the needed day) or reject."""
    row = balance(db, terms.resource_ref)
    needed_by = terms.needed_by or today(db)
    available = atp_on(db, row, needed_by)
    facts = row.version
    if terms.quantity <= available:
        return M.OFFER, terms.model_copy(update={"available_from": needed_by, "facts_version": facts}), None
    release = safety_release_allowed(db, row, terms.quantity - available, needed_by)
    if release > 0:
        extra = {**terms.extra, "safety_stock_used": str(release)}
        return M.OFFER, terms.model_copy(update={"available_from": needed_by, "facts_version": facts,
                                                 "extra": extra}), None
    incoming, promises = profile(db, row.item_id)
    later = earliest_full_date(terms.quantity, needed_by, int(setting(db, "later_date_horizon_days")), row.on_hand,
                               incoming, promises, row.safety_stock)
    if later is not None:
        return M.COUNTER_OFFER, terms.model_copy(update={"available_from": later, "facts_version": facts}), \
            ReasonCode.TOO_LATE
    if available > 0:
        return M.COUNTER_OFFER, terms.model_copy(update={"quantity": available, "available_from": needed_by,
                                                         "facts_version": facts}), ReasonCode.INSUFFICIENT
    return M.REJECT, None, ReasonCode.INSUFFICIENT


def _wording(kind: M, terms: Terms | None, reason: ReasonCode | None) -> str:
    if terms is None:
        return f"{kind.value.lower()}: {reason.value.lower() if reason else ''}".strip()
    return (f"{kind.value.lower()}: {terms.quantity} {terms.unit} of {terms.resource_ref} "
            f"from {terms.available_from or terms.needed_by}" + (f" ({reason.value.lower()})" if reason else ""))


def _reply(db: DbSession, message: Envelope, kind: M, terms: Terms | None = None, reason: ReasonCode | None = None,
           hold: HoldTerms | None = None) -> None:
    layer.send(db, layer.reply_to(message, kind, terms=terms, reason_code=reason, hold=hold,
                                  text=_wording(kind, terms, reason)))


# -- inbox ---------------------------------------------------------------------------------------------------------------------


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
        _release_hold(db, session.id, message.message_id, "HOLD_ABORTED", "ABORTED")
    # REJECT from the starter, or messages after the end: nothing to do


def _place_hold(db: DbSession, message: Envelope, session: Session) -> None:
    offer = Terms.model_validate(session.last_offer)
    row = balance(db, offer.resource_ref)
    day = offer.available_from or offer.needed_by
    safety_used = Decimal(str(offer.extra.get("safety_stock_used", "0")))
    if offer.quantity > atp_on(db, row, day) + safety_used:  # facts changed since the offer
        _reply(db, message, M.REJECT, reason=ReasonCode.STALE)
        return
    expires_day = today(db) + timedelta(days=int(setting(db, "hold_validity_days")))
    hold = Hold(item_id=row.item_id, quantity=offer.quantity, due_day=day,
                for_kind=offer.extra.get("for_kind", "CUSTOMER_DEMAND"), for_ref=offer.order_id or session.case_id,
                case_id=session.case_id, negotiation_id=str(session.id), expires_day=expires_day,
                safety_stock_used=safety_used, status="ACTIVE")
    db.add(hold)
    db.flush()
    ledger = LedgerWriter(db, StockLedger, message.message_id, today(db))
    change(ledger, row, "HELD", offer.quantity, "HOLD", hold=hold.id, case=session.case_id)
    if safety_used > 0:
        change(ledger, row, "SAFETY_STOCK_USE", safety_used, "SAFETY_STOCK_USE", hold=hold.id)
        channel.publish(db, event_type="SafetyStockBreached", publisher=AGENT, entity_type="item",
                        entity_id=row.item_id, entity_version=row.version, correlation_id=session.case_id,
                        payload={"item_id": row.item_id, "safety_stock": str(row.safety_stock),
                                 "released": str(safety_used)})
    expires_at = datetime.combine(expires_day, time.min, tzinfo=timezone.utc)
    _reply(db, message, M.AGREEMENT_PROPOSED, offer, hold=HoldTerms(hold_id=str(hold.id), expires_at=expires_at))


def _commit(db: DbSession, message: Envelope, session: Session) -> None:
    hold = db.scalar(select(Hold).where(Hold.negotiation_id == str(session.id)).with_for_update())
    if hold is None or hold.status != "ACTIVE":
        _reply(db, message, M.REJECT, reason=ReasonCode.UNAVAILABLE if hold is None else ReasonCode.HOLD_EXPIRED)
        return
    row = balance(db, hold.item_id)
    ledger = LedgerWriter(db, StockLedger, message.message_id, today(db))
    reservation = Reservation(item_id=hold.item_id, quantity=hold.quantity, due_day=hold.due_day,
                              for_kind=hold.for_kind, for_ref=hold.for_ref, case_id=hold.case_id, hold_id=hold.id,
                              status="ACTIVE", quantity_issued=ZERO, missing_quantity=ZERO, version=1)
    db.add(reservation)
    db.flush()
    change(ledger, row, "HELD", -hold.quantity, "COMMIT", hold=hold.id, reservation=reservation.id)
    change(ledger, row, "RESERVED", hold.quantity, "COMMIT", hold=hold.id, reservation=reservation.id)
    hold.status = "COMMITTED"
    channel.publish(db, event_type="ReservationCommitted", publisher=AGENT, entity_type="reservation",
                    entity_id=str(reservation.id), entity_version=1, correlation_id=hold.case_id,
                    payload={"reservation_id": str(reservation.id), "item_id": hold.item_id,
                             "quantity": str(hold.quantity), "for_kind": hold.for_kind, "for_ref": hold.for_ref})
    _reply(db, message, M.ACCEPT)


def _release_hold(db: DbSession, negotiation_id, source_id: str, reason: str, new_status: str) -> Hold | None:
    hold = db.scalar(select(Hold).where(Hold.negotiation_id == str(negotiation_id)).with_for_update())
    if hold is None or hold.status != "ACTIVE":
        return None
    row = balance(db, hold.item_id)
    ledger = LedgerWriter(db, StockLedger, f"{source_id}:{hold.id}", today(db))
    change(ledger, row, "HELD", -hold.quantity, reason, hold=hold.id)
    if hold.safety_stock_used > 0:
        change(ledger, row, "SAFETY_STOCK_USE", -hold.safety_stock_used, reason, hold=hold.id)
    hold.status = new_status
    return hold


# -- events ---------------------------------------------------------------------------------------------------------------------


def on_day_started(db: DbSession, event: Event) -> None:
    """Expire holds whose validity has passed; tell the starter (REJECT HOLD_EXPIRED -> session EXPIRED)."""
    day = date.fromisoformat(event.payload["date"])
    for hold in db.scalars(select(Hold).where(Hold.status == "ACTIVE", Hold.expires_day <= day)).all():
        session = db.get(Session, uuid.UUID(hold.negotiation_id))
        _release_hold(db, hold.negotiation_id, str(event.event_id), "HOLD_EXPIRED", "EXPIRED")
        if session is not None and session.status == "AGREEMENT_PROPOSED":
            layer.send(db, Envelope(message_id=str(uuid.uuid4()), session_id=str(session.id), case_id=session.case_id,
                                    sender=AGENT, receiver=session.starter, message_type=M.REJECT,
                                    reason_code=ReasonCode.HOLD_EXPIRED, text="hold expired",
                                    sent_at=datetime.now(timezone.utc)))


def on_material_issued(db: DbSession, event: Event) -> None:
    """Warehouse issued complete kits: on_hand and the production order's reservations go down (invariant 6)."""
    if not channel.is_newer(db, EventVersion, event):
        return
    ledger = LedgerWriter(db, StockLedger, str(event.event_id), today(db))
    for component in event.payload["components"]:
        issued = Decimal(component["issued"])
        if issued <= 0:
            continue
        # an order may hold several reservations of one item (from stock, bought for it, made for it): oldest first
        reservations = db.scalars(select(Reservation).where(
            Reservation.for_ref == event.payload["production_order_id"], Reservation.item_id == component["item_id"],
            Reservation.status.in_(("ACTIVE", "AT_RISK"))).order_by(Reservation.created_at, Reservation.id)
            .with_for_update()).all()
        if issued > sum((r.quantity - r.quantity_issued for r in reservations), ZERO):
            raise ValueError(f"issue of {issued} {component['item_id']} exceeds the reservations")  # invariant 6
        row = balance(db, component["item_id"])
        left = issued
        for reservation in reservations:
            take = min(left, reservation.quantity - reservation.quantity_issued)
            if take <= 0:
                continue
            change(ledger, row, "ON_HAND", -take, "ISSUE", reservation=reservation.id)
            change(ledger, row, "RESERVED", -take, "ISSUE", reservation=reservation.id)
            reservation.quantity_issued += take
            if reservation.quantity_issued == reservation.quantity:
                reservation.status = "ISSUED"
            left -= take


def on_finished_goods_stored(db: DbSession, event: Event) -> None:
    """Produced goods are stored: on_hand goes up, and the same quantity is reserved for what it was made for (the
    customer demand, or the parent production order of a sub-assembly), so no other request can take it."""
    if not channel.is_newer(db, EventVersion, event):
        return
    payload = event.payload
    quantity = Decimal(payload["quantity"])
    row = balance(db, payload["item_id"])
    ledger = LedgerWriter(db, StockLedger, str(event.event_id), today(db))
    change(ledger, row, "ON_HAND", quantity, "FG_STORED", order=payload.get("order_ref"))
    if not payload.get("for_ref"):
        return
    reservation = Reservation(item_id=row.item_id, quantity=quantity, due_day=today(db),
                              for_kind=payload.get("for_kind", "CUSTOMER_DEMAND"), for_ref=payload["for_ref"],
                              case_id=payload.get("production_order_id") or str(event.event_id), status="ACTIVE", quantity_issued=ZERO,
                              missing_quantity=ZERO, version=1)
    db.add(reservation)
    db.flush()
    change(ledger, row, "RESERVED", quantity, "PRODUCED_FOR_ORDER", reservation=reservation.id)


def on_shipment(db: DbSession, event: Event) -> None:
    if not channel.is_newer(db, EventVersion, event):
        return
    payload = event.payload
    shipped = Decimal(payload["quantity"])
    ledger = LedgerWriter(db, StockLedger, str(event.event_id), today(db))
    row = balance(db, payload["item_id"])
    remaining = shipped
    for reservation in db.scalars(select(Reservation).where(
            Reservation.for_ref == payload["order_ref"], Reservation.item_id == payload["item_id"],
            Reservation.status.in_(("ACTIVE", "AT_RISK"))).order_by(Reservation.created_at).with_for_update()):
        take = min(remaining, reservation.quantity - reservation.quantity_issued)
        if take <= 0:
            continue
        change(ledger, row, "RESERVED", -take, "SHIPMENT", reservation=reservation.id)
        reservation.quantity_issued += take
        if reservation.quantity_issued == reservation.quantity:
            reservation.status = "ISSUED"
        remaining -= take
    if remaining > 0:
        raise ValueError("shipment exceeds the order's finished-goods reservations")
    change(ledger, row, "ON_HAND", -shipped, "SHIPMENT", order=payload["order_ref"])


def on_plan_revised(db: DbSession, event: Event) -> None:
    """Planning no longer needs some reserved quantities (change or cancellation, QA-3): release exactly those."""
    ledger = LedgerWriter(db, StockLedger, str(event.event_id), today(db))
    if ledger.already_applied():
        return
    for release in event.payload.get("releases", []):
        if release.get("owner") != AGENT:
            continue
        reservation = db.get(Reservation, uuid.UUID(release["reservation_id"]), with_for_update=True)
        quantity = Decimal(release["quantity"])
        open_quantity = reservation.quantity - reservation.quantity_issued
        quantity = min(quantity, open_quantity)
        if quantity <= 0:
            continue
        row = balance(db, reservation.item_id)
        change(ledger, row, "RESERVED", -quantity, "RELEASE", reservation=reservation.id)
        reservation.quantity -= quantity
        reservation.version += 1
        if reservation.quantity == reservation.quantity_issued:
            reservation.status = "RELEASED" if reservation.quantity_issued == 0 else "ISSUED"
        channel.publish(db, event_type="ReservationReleased", publisher=AGENT, entity_type="reservation",
                        entity_id=str(reservation.id), entity_version=reservation.version,
                        correlation_id=event.correlation_id, causation_id=event.event_id,
                        payload={"reservation_id": str(reservation.id), "item_id": reservation.item_id,
                                 "quantity": str(quantity), "for_ref": reservation.for_ref})


def on_procurement_committed(db: DbSession, event: Event) -> None:
    """Purchasing committed supply: one expected receipt per supplier Leg. Bought for one order, it is pegged to it."""
    payload = event.payload
    for leg in payload["legs"]:
        if db.scalar(select(IncomingReceipt.id).where(IncomingReceipt.purchasing_commitment_ref == leg["leg_id"])):
            continue  # already known (repeated delivery)
        db.add(IncomingReceipt(purchasing_commitment_ref=leg["leg_id"], item_id=payload["item_id"],
                               quantity=Decimal(leg["quantity"]), quantity_received=ZERO,
                               expected_day=date.fromisoformat(leg["delivery_date"]), status="EXPECTED",
                               for_kind=payload.get("for_kind"), for_ref=payload.get("for_ref")))


def on_supplier_delayed(db: DbSession, event: Event) -> None:
    """The expected receipt moves to the new date (ATP of the item follows; a pegged receipt stays pegged)."""
    if not channel.is_newer(db, EventVersion, event):
        return
    receipt = db.scalar(select(IncomingReceipt).where(
        IncomingReceipt.purchasing_commitment_ref == event.payload["leg_id"]).with_for_update())
    if receipt is not None and receipt.status in ("EXPECTED", "PARTLY_RECEIVED"):
        receipt.expected_day = date.fromisoformat(event.payload["new_date"])
        receipt.source_version += 1


def on_material_received(db: DbSession, event: Event) -> None:
    """Warehouse received a delivery: on hand goes up; a delivery bought for an order is reserved for it."""
    payload = event.payload
    ledger = LedgerWriter(db, StockLedger, str(event.event_id), today(db))
    if ledger.already_applied():
        return
    quantity = Decimal(payload["quantity"])
    row = balance(db, payload["item_id"])
    change(ledger, row, "ON_HAND", quantity, "RECEIPT", receipt=payload["leg_id"])
    receipt = db.scalar(select(IncomingReceipt).where(IncomingReceipt.purchasing_commitment_ref == payload["leg_id"])
                        .with_for_update())
    if receipt is None:
        return
    receipt.quantity_received += quantity
    receipt.status = "RECEIVED" if receipt.quantity_received >= receipt.quantity else "PARTLY_RECEIVED"
    if receipt.for_ref:
        reservation = Reservation(item_id=row.item_id, quantity=quantity, due_day=today(db),
                                  for_kind=receipt.for_kind or "PRODUCTION_ORDER", for_ref=receipt.for_ref,
                                  case_id=payload.get("procurement_request_id") or str(event.event_id),
                                  status="ACTIVE", quantity_issued=ZERO, missing_quantity=ZERO, version=1)
        db.add(reservation)
        db.flush()
        change(ledger, row, "RESERVED", quantity, "BOUGHT_FOR_ORDER", reservation=reservation.id)


# -- setup (simulator configuration) ------------------------------------------------------------------------------------


def setup(db: DbSession, rows: list[dict]) -> None:
    """Starting stock: [{item_id, on_hand, safety_stock}]. Recorded as ADJUSTMENT ledger rows."""
    ledger = LedgerWriter(db, StockLedger, f"setup:{uuid.uuid4()}", today(db))
    for item in rows:
        row = balance(db, str(item["item_id"]))
        on_hand, safety = Decimal(str(item.get("on_hand", 0))), Decimal(str(item.get("safety_stock", 0)))
        if on_hand < 0 or safety < 0:
            raise ValueError("stock and safety stock must not be negative")
        change(ledger, row, "ON_HAND", on_hand - row.on_hand, "ADJUSTMENT")
        change(ledger, row, "SAFETY_STOCK", safety - row.safety_stock, "ADJUSTMENT")


def register(runner_register) -> None:
    """Inbox and event subscriptions of the Inventory Agent."""
    runner_register(layer.register_inbox(AGENT, handle_message))
    channel.subscribe(AGENT, "SimulatedDayStarted", on_day_started)
    channel.subscribe(AGENT, "MaterialIssuedToProduction", on_material_issued)
    channel.subscribe(AGENT, "FinishedGoodsStored", on_finished_goods_stored)
    channel.subscribe(AGENT, "ShipmentDispatched", on_shipment)
    channel.subscribe(AGENT, "PlanRevised", on_plan_revised)
    channel.subscribe(AGENT, "ProcurementCommitted", on_procurement_committed)
    channel.subscribe(AGENT, "MaterialReceived", on_material_received)
    channel.subscribe(AGENT, "SupplierDeliveryDelayed", on_supplier_delayed)
