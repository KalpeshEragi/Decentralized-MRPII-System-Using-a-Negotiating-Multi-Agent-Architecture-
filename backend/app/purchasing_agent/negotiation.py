"""A supplier's reply on one Leg: interpret it, validate it, then agree, counter, reallocate, ask again or fail the Leg.
Purchasing always echoes how it read the reply. The decision on one reply is applied in one transaction; only the LLM's
wording of Purchasing's answer comes after it.

Rules (dev_docs/purchasing_agent/purchasing_agent_architecture.md §7):
- ACCEPT of the current offer → Leg AGREED on the offered terms (a counter-back accepted lifts the cap to them).
- COUNTER with the offered quantity and a date no later than required → Leg AGREED on the supplier's terms.
- COUNTER with the offered quantity and a later date, or a date before today → counter with the required date, which
  never changes; with no rounds left → Leg FAILED `round_limit_exceeded`.
- COUNTER with another quantity → it becomes the supplier's cap and the procurement is reallocated among the
  already-selected suppliers (§7.4, `_reallocate`); without a stated date it can't be agreed as it is, so the supplier
  is countered with its quantity by the required date.
- COUNTER that leaves the quantity or the date unstated (only the LLM reports these; terms are never invented) and
  isn't settled by the rules above → handled as unclear: a clarification asking for both.
- REJECT → Leg FAILED `supplier_rejected`.
- Unclear → a clarification request, no round used; once the pending offer has had the maximum (2) → Leg FAILED
  `unclear_response`. Clarifications never change the round limit.
Every remaining Leg AGREED proposes the agreement. All or nothing (§7.5): a Leg failing fails the request and aborts its
other Legs (`fail_procurement`).

The reply is read by the LLM, else the fallback parser (`interpretation.py`). Offers, counter-offers and clarification
requests are worded by the LLM behind guardrails, else the template (`writer.py`); the echo stays the template's.
No lock is held while the LLM runs (§9): the reply is read before the request and Leg are locked and re-checked, and
Purchasing's answer is stored as the template, committed, then worded (`wording.py`).

Every message awaiting a reply (offer, counter-offer, clarification request) moves the Leg's response deadline to now +
the configured hours; a missed deadline is handled by `deadlines.py`.

Reallocation and the Constrained Quantity use effective availability (`availability.py`): the Supplier Service quantity
less other requests' holds, read under the supplier-item locks.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.llm.client import LLMClient
from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent import messages
from app.purchasing_agent.availability import Availability, effective_availability
from app.purchasing_agent.interpretation import Interpretation, OfferedTerms, SupplierReply, interpret
from app.purchasing_agent.models import (DecisionAudit, LegReason, LegStatus, ProcurementRequest,
                                         PurchaseRequisition, RequestStatus)
from app.purchasing_agent.selection import PriceState, Selection, SupplierOption, reallocate
from app.purchasing_agent.service import AGENT_CODE, audit_record, selection_date
from app.purchasing_agent.wording import PendingWording, apply_wordings
from app.purchasing_agent.writer import MessageWriter
from app.supplier_service import service as supplier_service

SUPPLIER_MESSAGE_TYPES = {"ACCEPT": "ACCEPT", "COUNTER": "COUNTER_OFFER", "REJECT": "REJECT", None: "UNCLEAR"}


@dataclass(frozen=True)
class Decision:
    # AGREED, COUNTER_OFFER, FAILED, CLARIFICATION_REQUEST; REALLOCATE from `validate` only; NO_LONGER_NEEDED and
    # ABORTED (another Leg failed the procurement) from `_reallocate` only
    outcome: str
    quantity: Decimal | None = None
    delivery_date: date | None = None
    reason: str | None = None  # FAILED and ABORTED only
    summary: str = ""


def validate(reply: SupplierReply | None, offered_quantity: Decimal, offered_date: date, required_date: date,
             rounds_left: int, clarifications_left: int, *, today: date) -> Decision:
    """Purchasing's decision on one reply to its current offer. Pure. A delivery date before `today` is handled like
    a late one: never agreed."""
    if reply is None:
        if clarifications_left <= 0:
            return Decision("FAILED", reason=LegReason.UNCLEAR_RESPONSE,
                            summary="the reply could not be read and no clarifications are left for this offer")
        return Decision("CLARIFICATION_REQUEST", summary="the reply could not be read; asked for the reply format")
    if reply.action == "REJECT":
        return Decision("FAILED", reason=LegReason.SUPPLIER_REJECTED, summary="the supplier rejected the offer")
    if reply.action == "ACCEPT":  # our own offers are always the needed quantity by the required date
        return Decision("AGREED", offered_quantity, offered_date, summary="the supplier accepted the current offer")
    if reply.quantity is not None and reply.quantity != offered_quantity:
        return Decision("REALLOCATE", reply.quantity, reply.delivery_date,
                        summary=f"quantity {messages.quantity_text(reply.quantity)} is not the offered "
                                f"{messages.quantity_text(offered_quantity)}: it caps the supplier; reallocated")
    if reply.delivery_date is not None and not on_time(reply.delivery_date, required_date, today):
        problem = (f"delivery {reply.delivery_date} is after the required date {required_date}"
                   if reply.delivery_date > required_date else f"delivery {reply.delivery_date} is in the past")
        if rounds_left <= 0:
            return Decision("FAILED", reason=LegReason.ROUND_LIMIT_EXCEEDED, summary=f"{problem}; no rounds left")
        return Decision("COUNTER_OFFER", offered_quantity, required_date,
                        summary=f"{problem}; countered with the needed quantity by the required date")
    if reply.quantity is None or reply.delivery_date is None:
        missing = "quantity" if reply.quantity is None else "delivery date"
        if clarifications_left <= 0:
            return Decision("FAILED", reason=LegReason.UNCLEAR_RESPONSE,
                            summary=f"the counter-offer gives no {missing} and no clarifications are left for this "
                                    f"offer")
        return Decision("CLARIFICATION_REQUEST",
                        summary=f"the counter-offer gives no {missing}; asked for both the quantity and the date")
    return Decision("AGREED", reply.quantity, reply.delivery_date,
                    summary="the counter-offer has the needed quantity by the required date")


def on_time(delivery_date: date, required_date: date, today: date) -> bool:
    """A delivery date Purchasing can agree to: no later than required and not in the past (§7.3)."""
    return today <= delivery_date <= required_date


@dataclass(frozen=True)
class Received:
    duplicate: bool  # True: this message_id was already stored; nothing changed


def receive_supplier_message(db: Session, leg_id: uuid.UUID, message_id: uuid.UUID, text: str, now: datetime,
                             settings: Settings, llm_client: LLMClient) -> Received:
    """No lock is held while the LLM runs (§9): the reply is read first, then the request and Leg are locked and
    checked again before anything is applied; the LLM words Purchasing's answer after the commit (`wording.py`)."""
    leg = db.get(PurchaseRequisition, leg_id)
    if leg is None:
        raise AppError(ErrorCode.NOT_FOUND, "leg not found")
    session_id = leg.negotiation_session_id
    # A duplicate delivery is skipped before any LLM call; `append_message` checks again under the lock.
    stored_in = negotiation_engine.message_session(db, message_id)
    if stored_in == session_id:
        db.rollback()
        return Received(duplicate=True)
    if stored_in is not None:
        raise AppError(ErrorCode.CONFLICT, "message_id is already used in another negotiation session",
                       [{"field": "message_id", "issue": "already used"}])

    today = selection_date(now, settings.purchasing_timezone)
    request = db.get(ProcurementRequest, leg.procurement_request_id)
    read_offer = negotiation_engine.current_offer(db, session_id)
    # A reply to a closed negotiation is refused below: it is only parsed, never sent to the LLM.
    offered = (OfferedTerms(Decimal(read_offer.terms["quantity"]),
                            date.fromisoformat(read_offer.terms["delivery_date"]), today)
               if _is_open(request, leg, read_offer) else None)
    db.rollback()  # no transaction stays open while the LLM runs
    interpretation = interpret(text, llm_client, offered)
    reply = interpretation.reply

    # Lock the request, then the Leg (re-read under the lock): replies on the same request are handled one at a time.
    request = db.get(ProcurementRequest, leg.procurement_request_id, with_for_update=True, populate_existing=True)
    leg = db.get(PurchaseRequisition, leg_id, with_for_update=True, populate_existing=True)
    if negotiation_engine.message_session(db, message_id) == session_id:  # handled meanwhile: still a duplicate
        db.rollback()
        return Received(duplicate=True)
    offer = negotiation_engine.current_offer(db, session_id)
    if not _is_open(request, leg, offer):
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"the Leg is {leg.status} and the request {request.status}")
    if offered is None or offer.message_id != read_offer.message_id:
        # Stale: Purchasing's offer changed while the reply was read (e.g. a revised offer after a reallocation), so
        # the reply answers an offer that no longer stands. Nothing is stored or applied; the supplier answers the
        # current offer.
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, "the offer changed while the reply was read; reply to the "
                       "current offer", [{"field": "offer", "issue": "superseded"}])
    negotiation_engine.append_message(
        db, session_id, message_id=message_id, sender_type="SUPPLIER", sender_ref=str(leg.supplier_id),
        message_type=SUPPLIER_MESSAGE_TYPES[reply.action if reply else None], text=text,
        terms=messages.reply_terms(reply.quantity, reply.delivery_date) if reply and reply.action == "COUNTER" else None,
        interpretation_source=interpretation.source,
        causation_id=negotiation_engine.awaited_message_id(db, session_id),  # the offer, or a clarification after it
    )

    state = negotiation_engine.session_state(db, session_id)
    clarifications = negotiation_engine.clarifications_since_offer(db, session_id)
    decision = validate(reply, Decimal(offer.terms["quantity"]), date.fromisoformat(offer.terms["delivery_date"]),
                        request.required_date, state.rounds_left,
                        settings.purchasing_max_clarifications - clarifications, today=today)
    names = {s.supplier_id: s.supplier_name for s in supplier_service.supplier_items_for(db, request.item_id)}
    due = now + timedelta(hours=settings.purchasing_response_deadline_hours)  # for any message awaiting a reply
    pending: list[PendingWording] = []
    if decision.outcome == "REALLOCATE":
        decision, failure = _reallocate(db, request, leg, reply, state.rounds_left, message_id, now, today, due,
                                        pending)
    else:
        failure = _apply(db, request, leg, reply, decision, message_id, now, today, due, pending)
    _audit(db, request, leg, message_id, interpretation, offer.terms, state, clarifications, decision, failure)
    db.commit()  # releases the locks before the LLM words Purchasing's messages

    apply_wordings(db, MessageWriter(llm_client, names), pending)
    return Received(duplicate=False)


def _is_open(request: ProcurementRequest, leg: PurchaseRequisition, offer: negotiation_engine.Offer | None) -> bool:
    return leg.status == LegStatus.PENDING and request.status == RequestStatus.NEGOTIATING and offer is not None


@dataclass(frozen=True)
class ProcurementFailure:
    constrained_quantity: Decimal
    aborted_leg_ids: tuple[uuid.UUID, ...]


def _apply(db: Session, request: ProcurementRequest, leg: PurchaseRequisition, reply: SupplierReply | None,
           decision: Decision, causation_id: uuid.UUID, now: datetime, today: date, due: datetime,
           pending: list[PendingWording]) -> ProcurementFailure | None:
    echo = messages.understood_text(reply.action, reply.quantity, reply.delivery_date) if reply else ""
    if decision.outcome == "CLARIFICATION_REQUEST":
        _send(db, leg, causation_id, "CLARIFICATION_REQUEST", messages.clarification_text(echo), due=due,
              pending=pending, prefix=echo)
    elif decision.outcome == "COUNTER_OFFER":
        terms = messages.offer_terms(decision.quantity, decision.delivery_date)
        text = messages.counter_text(echo, decision.quantity, decision.delivery_date, request.required_date)
        _send(db, leg, causation_id, "COUNTER_OFFER", text, terms, due=due, pending=pending, prefix=echo)
    elif decision.outcome == "AGREED":
        _send(db, leg, causation_id, "CONFIRMATION", messages.agreed_text(echo, decision.quantity, decision.delivery_date),
              messages.offer_terms(decision.quantity, decision.delivery_date))
        negotiation_engine.close_session(db, leg.negotiation_session_id, "AGREED", None, now)
        leg.status, leg.agreed_quantity, leg.agreed_delivery_date = LegStatus.AGREED, decision.quantity, decision.delivery_date
        if leg.quantity_cap is not None and leg.quantity_cap < decision.quantity:
            leg.quantity_cap = decision.quantity  # a counter-back accepted lifts the cap (§7.4)
        _propose_if_all_agreed(db, request)
    elif decision.outcome == "NO_LONGER_NEEDED":
        _drop(db, leg, causation_id, f"{echo} {messages.NO_LONGER_NEEDED_TEXT}", now)
        _propose_if_all_agreed(db, request)
    else:
        _send(db, leg, causation_id, "CONFIRMATION", messages.closed_text(echo, decision.reason))
        negotiation_engine.close_session(db, leg.negotiation_session_id, "REJECTED", decision.reason, now)
        leg.status, leg.status_reason = LegStatus.FAILED, decision.reason
        return fail_procurement(db, request, leg, causation_id, now, today)
    db.flush()
    return None


def _propose_if_all_agreed(db: Session, request: ProcurementRequest) -> None:
    """The combined agreement is proposed once every Leg still part of the procurement is AGREED."""
    db.flush()
    legs = db.execute(select(PurchaseRequisition.status, PurchaseRequisition.status_reason).where(
        PurchaseRequisition.procurement_request_id == request.id)).all()
    if all(status == LegStatus.AGREED for status, reason in legs if reason != LegReason.NO_LONGER_NEEDED):
        request.status = RequestStatus.AGREEMENT_PROPOSED


def _drop(db: Session, leg: PurchaseRequisition, causation_id: uuid.UUID, text: str, now: datetime) -> None:
    """A Leg no longer needed after reallocation: the supplier is told, the Engine session CANCELLED (also from
    AGREED: nothing is committed yet) and the Leg ABORTED, which releases its hold."""
    cancel_leg(db, leg, text, LegReason.NO_LONGER_NEEDED, now, causation_id)


def cancel_leg(db: Session, leg: PurchaseRequisition, text: str, reason: str, now: datetime,
               causation_id: uuid.UUID | None = None) -> None:
    """The supplier is told (CANCEL with `text`), the Engine session CANCELLED (also from AGREED: nothing is committed
    yet) and the Leg ABORTED with `reason`, which releases its hold. The caller holds the Leg's lock. Without a
    `causation_id`, the CANCEL points at the Leg's latest message: the offer or agreement it cancels."""
    cause = causation_id or negotiation_engine.latest_message_id(db, leg.negotiation_session_id)
    _send(db, leg, cause, "CANCEL", text)
    negotiation_engine.cancel_session(db, leg.negotiation_session_id, reason, now)
    leg.status, leg.status_reason = LegStatus.ABORTED, reason


def _reallocate(db: Session, request: ProcurementRequest, leg: PurchaseRequisition, reply: SupplierReply,
                rounds_left: int, causation_id: uuid.UUID, now: datetime, today: date, due: datetime,
                pending: list[PendingWording]) -> tuple[Decision, ProcurementFailure | None]:
    """§7.4 Flexible Legs. The countered quantity caps `leg`'s supplier; the selection rules then re-run over only the
    suppliers still selected (PENDING or AGREED Legs), each limited by its cap. New suppliers are never added.
    - A better-ranked subset, even a single supplier, replaces the current allocation (threshold not re-checked).
    - A selected supplier no longer needed → Leg ABORTED `no_longer_needed`, Engine session CANCELLED.
    - Another Leg whose quantity changes → reopened (Engine AGREED → OPEN) with a revised offer: a new round.
    - `leg` itself: AGREED when its new quantity is its counter and its stated date is on time; else countered with
      its new quantity by the required date.
    - A Leg needing a new round with none left → it FAILS `round_limit_exceeded`, and so does the procurement.
    - No allocation fits the caps → `leg`'s supplier is countered back with its current quantity while rounds remain.
    Returns `leg`'s decision (for the response audit) and the procurement failure, if any."""
    leg.quantity_cap = reply.quantity
    selected = list(db.scalars(select(PurchaseRequisition)
                               .where(PurchaseRequisition.procurement_request_id == request.id,
                                      PurchaseRequisition.status.in_(LegStatus.OPEN))
                               .order_by(PurchaseRequisition.created_at, PurchaseRequisition.id)
                               .with_for_update()))
    availability = effective_availability(db, request.item_id, excluding_request_id=request.id)
    options = [_selected_option(other, availability[other.supplier_id], today)
               for other in selected if other.supplier_id in availability]
    result = reallocate(request.shortage_quantity, request.required_date, options, today)
    names = {supplier_id: a.supplier.supplier_name for supplier_id, a in availability.items()}

    if result.outcome == "FAILED":
        if rounds_left > 0:
            own = Decision("COUNTER_OFFER", leg.allocated_quantity, request.required_date,
                           summary="no allocation fits the caps; countered back with the quantity needed")
        else:
            own = Decision("FAILED", reason=LegReason.ROUND_LIMIT_EXCEEDED,
                           summary="no allocation fits the caps and no rounds are left")
        _audit_reallocation(db, request, leg, selected, options, result, names, own)
        return own, _apply(db, request, leg, reply, own, causation_id, now, today, due, pending)

    new = {winner.supplier_id: winner.quantity for winner in result.legs}
    if leg.supplier_id not in new:
        own = Decision("NO_LONGER_NEEDED", summary="the reallocation no longer needs this supplier")
    elif (new[leg.supplier_id] == reply.quantity and reply.delivery_date is not None
          and on_time(reply.delivery_date, request.required_date, today)):
        own = Decision("AGREED", reply.quantity, reply.delivery_date,
                       summary="the reallocation takes the countered quantity by an on-time date")
    else:
        own = Decision("COUNTER_OFFER", new[leg.supplier_id], request.required_date,
                       summary="countered with the reallocated quantity by the required date")
    others = [other for other in selected if other is not leg]
    dropped = [other for other in others if other.supplier_id not in new]
    reopened = [other for other in others
                if other.supplier_id in new and new[other.supplier_id] != other.allocated_quantity]
    if own.outcome == "COUNTER_OFFER" and rounds_left <= 0:
        own = Decision("FAILED", reason=LegReason.ROUND_LIMIT_EXCEEDED, summary=f"{own.summary}, but no rounds are left")
    stuck = next((other for other in reopened
                  if negotiation_engine.session_state(db, other.negotiation_session_id).rounds_left <= 0), None)
    if stuck is not None and own.outcome != "FAILED":
        own = Decision("ABORTED", reason=LegReason.SPLIT_FAILED,
                       summary=f"the reallocation needs a revised offer to {names.get(stuck.supplier_id)}, which has "
                               f"no rounds left: the procurement failed")
    _audit_reallocation(db, request, leg, selected, options, result, names, own)
    if own.outcome == "FAILED":
        return own, _apply(db, request, leg, reply, own, causation_id, now, today, due, pending)
    if stuck is not None:
        return own, _fail_revision(db, request, stuck, causation_id, now, today)

    for other in dropped:
        _drop(db, other, causation_id, messages.NO_LONGER_NEEDED_TEXT, now)
    for other in reopened:
        if other.status == LegStatus.AGREED:
            negotiation_engine.reopen_session(db, other.negotiation_session_id)
            other.status, other.agreed_quantity, other.agreed_delivery_date = LegStatus.PENDING, None, None
        other.allocated_quantity = new[other.supplier_id]
        terms = messages.offer_terms(other.allocated_quantity, request.required_date)
        text = messages.revised_offer_text(other.allocated_quantity, request.required_date)
        _send(db, other, causation_id, "COUNTER_OFFER", text, terms, due=due, pending=pending)
    if leg.supplier_id in new:
        leg.allocated_quantity = new[leg.supplier_id]
    request.split_type, request.cost_ranking_available = result.outcome, result.cost_ranking_available
    return own, _apply(db, request, leg, reply, own, causation_id, now, today, due, pending)


def _selected_option(leg: PurchaseRequisition, availability: Availability, today: date) -> SupplierOption:
    """A selected supplier as reallocation sees it: priced by the Leg's snapshot at selection, its effective
    availability limited by its cap, arriving on its agreed date when AGREED (as in the Constrained Quantity), else
    today + lead time."""
    supplier = availability.supplier
    lead_time_days = ((leg.agreed_delivery_date - today).days if leg.agreed_delivery_date is not None
                      else supplier.lead_time_days)
    price = (PriceState("PRICED", leg.unit_price_at_selection, leg.purchasing_contract_id)
             if leg.unit_price_at_selection is not None else PriceState("NOT_REGISTERED"))
    return SupplierOption(
        supplier_id=supplier.supplier_id, supplier_name=supplier.supplier_name, is_active=supplier.supplier_is_active,
        lead_time_days=lead_time_days, min_order_qty=supplier.min_order_qty,
        available_qty=availability.capped(leg.quantity_cap),
        price=price,
    )


def _fail_revision(db: Session, request: ProcurementRequest, leg: PurchaseRequisition, causation_id: uuid.UUID,
                   now: datetime, today: date) -> ProcurementFailure:
    """A Leg the reallocation must revise has no rounds left: it FAILS `round_limit_exceeded` (an agreed one is first
    reopened, so its session can end REJECTED), and with it the procurement."""
    if leg.status == LegStatus.AGREED:
        negotiation_engine.reopen_session(db, leg.negotiation_session_id)
    _send(db, leg, causation_id, "CONFIRMATION", messages.REVISION_ROUND_LIMIT_TEXT)
    negotiation_engine.close_session(db, leg.negotiation_session_id, "REJECTED", LegReason.ROUND_LIMIT_EXCEEDED, now)
    leg.status, leg.status_reason = LegStatus.FAILED, LegReason.ROUND_LIMIT_EXCEEDED
    return fail_procurement(db, request, leg, causation_id, now, today)


def fail_procurement(db: Session, request: ProcurementRequest, failed_leg: PurchaseRequisition,
                     causation_id: uuid.UUID | None, now: datetime, today: date) -> ProcurementFailure:
    """All or nothing (§7.5): `failed_leg` (already FAILED by the caller, who holds the request lock) fails the request.
    Every other PENDING or AGREED Leg is told, ABORTED `split_failed` and its Engine session CANCELLED, which releases
    its hold. Nothing is committed and no replacement supplier is chosen: the requester decides whether to resubmit."""
    others = list(db.scalars(select(PurchaseRequisition)
                             .where(PurchaseRequisition.procurement_request_id == request.id,
                                    PurchaseRequisition.id != failed_leg.id)
                             .order_by(PurchaseRequisition.created_at, PurchaseRequisition.id)
                             .with_for_update()))
    constrained = _constrained_quantity(db, request, failed_leg, others, today)
    aborted = [leg for leg in others if leg.status in LegStatus.OPEN]
    for leg in aborted:
        cancel_leg(db, leg, messages.CANCELLED_TEXT, LegReason.SPLIT_FAILED, now, causation_id)
    request.status, request.status_reason = RequestStatus.FAILED, f"a Leg failed: {failed_leg.status_reason}"
    request.constrained_quantity = constrained
    db.flush()
    return ProcurementFailure(constrained, tuple(leg.id for leg in aborted))


def _constrained_quantity(db: Session, request: ProcurementRequest, failed_leg: PurchaseRequisition,
                          others: list[PurchaseRequisition], today: date) -> Decimal:
    """The most the selected suppliers could still deliver by the required date (§7.5), at most the shortage:
    - the failed Leg's supplier: the quantity of its last counter-offer deliverable by the required date, within its
      availability and cap; 0 if it never offered one;
    - every other selected supplier (not one dropped on reallocation): its availability (less other requests' holds),
      limited by its cap, if that is at least its MOQ and it still delivers by the required date (agreed date, else
      today + lead time)."""
    availability = effective_availability(db, request.item_id, excluding_request_id=request.id)

    def limit(leg: PurchaseRequisition) -> Decimal:
        a = availability.get(leg.supplier_id)
        return a.capped(leg.quantity_cap) if a else Decimal(0)

    on_time_offers = [Decimal(o.terms["quantity"])  # a counter-offer missing either term proves nothing deliverable
                      for o in negotiation_engine.respondent_counter_offers(db, failed_leg.negotiation_session_id)
                      if o.terms.get("quantity") and o.terms.get("delivery_date")
                      and on_time(date.fromisoformat(o.terms["delivery_date"]), request.required_date, today)]
    total = min(on_time_offers[-1], limit(failed_leg)) if on_time_offers else Decimal(0)
    for leg in others:
        supplier = availability[leg.supplier_id].supplier if leg.supplier_id in availability else None
        if supplier is None or leg.status not in LegStatus.OPEN:
            continue
        arrival = leg.agreed_delivery_date or today + timedelta(days=supplier.lead_time_days)
        if arrival <= request.required_date and limit(leg) >= supplier.min_order_qty:
            total += limit(leg)
    return min(total, request.shortage_quantity)


def _send(db: Session, leg: PurchaseRequisition, causation_id: uuid.UUID | None, message_type: str, text: str,
          terms: dict | None = None, due: datetime | None = None, pending: list[PendingWording] | None = None,
          prefix: str = "") -> None:
    """`due`: the message awaits a reply by then (the Leg's new response deadline). `pending`: the LLM may word `text`
    after the commit (`wording.py`), keeping `prefix` (the echo) as written."""
    message_id = uuid.uuid4()
    negotiation_engine.append_message(
        db, leg.negotiation_session_id, message_id=message_id, sender_type="AGENT", sender_ref=AGENT_CODE,
        message_type=message_type, text=text, terms=terms, causation_id=causation_id, response_deadline=due,
    )
    if pending is not None:
        pending.append(PendingWording(leg.id, leg.negotiation_session_id, message_id, leg.supplier_id, text, terms,
                                      prefix))


def _audit_reallocation(db: Session, request: ProcurementRequest, leg: PurchaseRequisition,
                        selected: list[PurchaseRequisition], options: list[SupplierOption], result: Selection,
                        names: dict[uuid.UUID, str], own: Decision) -> None:
    """The revised allocation (or why none fits), and the actual saving against the best priced single supplier of
    the original selection, which the saving threshold was measured against (not re-checked)."""
    before = {names.get(s.supplier_id): messages.quantity_text(s.allocated_quantity) for s in selected}
    prices = [s.unit_price_at_selection for s in selected]
    before_cost = (sum((s.unit_price_at_selection * s.allocated_quantity for s in selected), Decimal(0))
                   if None not in prices else None)
    original = db.scalar(select(DecisionAudit.decision).where(
        DecisionAudit.procurement_request_id == request.id, DecisionAudit.decision_type == "SUPPLIER_SELECTION",
    ).order_by(DecisionAudit.created_at.desc()).limit(1)) or {}
    reference = original.get("best_priced_single")
    saving = None
    if reference and result.total_cost is not None:
        reference_cost = Decimal(reference["total_cost"])
        saving = ((reference_cost - result.total_cost) / reference_cost * 100).quantize(Decimal("0.01"))
    new = {winner.supplier_id for winner in result.legs}
    db.add(DecisionAudit(
        procurement_request_id=request.id, decision_type="REALLOCATION",
        context=audit_record({
            "trigger_leg_id": leg.id,
            "supplier_id": leg.supplier_id,
            "quantity_cap": messages.quantity_text(leg.quantity_cap),
            "allocation_before": before,
            "total_cost_before": before_cost,
            "selected_suppliers": options,  # available_qty: effective availability limited by the cap
            "options": result.options,
            "combinations": result.combinations,
        }),
        decision=audit_record({
            "outcome": result.outcome,
            "legs": result.legs,
            "total_cost": result.total_cost,
            "cost_ranking_available": result.cost_ranking_available,
            "constrained_quantity": result.constrained_quantity,
            "reference_single": ({"supplier_name": reference["supplier_name"], "total_cost": reference["total_cost"]}
                                 if reference else None),
            "saving_percent": saving,
            "dropped_suppliers": [names.get(s.supplier_id) for s in selected if result.legs and s.supplier_id not in new],
            "trigger_leg_outcome": own.outcome,
        }),
        reasoning_summary=f"{result.reasoning_summary} {own.summary}.",
    ))


def _audit(db: Session, request: ProcurementRequest, leg: PurchaseRequisition, message_id: uuid.UUID,
           interpretation: Interpretation, offer_terms: dict, state: negotiation_engine.SessionState,
           clarifications: int, decision: Decision, failure: ProcurementFailure | None) -> None:
    reply = interpretation.reply
    db.add(DecisionAudit(
        procurement_request_id=request.id, decision_type="RESPONSE_VALIDATION",
        context={
            "leg_id": str(leg.id),
            "supplier_id": str(leg.supplier_id),
            "message_id": str(message_id),
            "interpretation": {
                "action": reply.action if reply else None,
                "quantity": messages.quantity_text(reply.quantity) if reply and reply.quantity else None,
                "delivery_date": reply.delivery_date.isoformat() if reply and reply.delivery_date else None,
                "source": interpretation.source,
            },
            "current_offer": offer_terms,
            "required_date": request.required_date.isoformat(),
            "round_count": state.round_count,
            "max_rounds": state.max_rounds,
            "clarifications_since_offer": clarifications,
        },
        decision={
            "outcome": decision.outcome,
            "terms": messages.offer_terms(decision.quantity, decision.delivery_date) if decision.quantity else None,
            "reason": decision.reason,
            **({"request_status": request.status,
                "constrained_quantity": messages.quantity_text(failure.constrained_quantity),
                "aborted_legs": [str(leg_id) for leg_id in failure.aborted_leg_ids]} if failure else {}),
        },
        reasoning_summary=decision.summary,
    ))
