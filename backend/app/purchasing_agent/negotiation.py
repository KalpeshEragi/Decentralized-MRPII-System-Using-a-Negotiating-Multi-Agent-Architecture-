"""A supplier's reply on one Leg: interpret it, validate it, then agree, counter, reallocate, ask again or fail the Leg.
Purchasing always echoes how it read the reply. The decision on one reply is applied in one transaction; only the LLM's
wording of Purchasing's answer comes after it.

Rules (dev_docs/purchasing_agent/purchasing_agent_architecture.md §7):
- ACCEPT of the current offer → Leg AGREED on the offered terms (a counter-back accepted lifts the cap to them).
- COUNTER with the offered quantity and a date no later than required → Leg AGREED on the supplier's terms.
- COUNTER with the offered quantity and a later date, or a date before today → counter with the required date, which
  never changes; with no rounds left → Leg FAILED `round_limit_exceeded`.
- COUNTER with another quantity → it becomes the supplier's cap and the procurement is resolved again (`_resolve`);
  without a stated date it can't be agreed as it is, so the supplier is countered with its quantity by the required
  date.
- COUNTER that leaves the quantity or the date unstated (only the LLM reports these; terms are never invented) and
  isn't settled by the rules above → handled as unclear: a clarification asking for both.
- REJECT → Leg FAILED `supplier_rejected`.
- Unclear → a clarification request, no round used; once the pending offer has had the maximum (2) → Leg FAILED
  `unclear_response`. Clarifications never change the round limit.
A failed Leg no longer fails the request by itself (ADR-003): its supplier is excluded and the request is resolved
again. Resolving (§7.4–7.4.1): reallocate among the open Legs → else re-source over every eligible supplier
(`re_sourcing.py`) → else counter the countering supplier back while it has rounds → else the request FAILS
(`fail_procurement`, §7.5). The agreement is proposed once every open Leg is AGREED and they cover the shortage.
A missed deadline is only recorded on a read (`deadlines.py`); `re_source` resolves it later.

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
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.llm.client import LLMClient
from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent import messages, re_sourcing
from app.purchasing_agent.availability import Availability, effective_availability
from app.purchasing_agent.interpretation import Interpretation, OfferedTerms, SupplierReply, interpret
from app.purchasing_agent.models import (DecisionAudit, LegReason, LegStatus, ProcurementRequest,
                                         PurchaseRequisition, RequestStatus)
from app.purchasing_agent.selection import (Leg, PriceState, Selection, SupplierOption, reallocate,
                                            select_suppliers)
from app.purchasing_agent.service import AGENT_CODE, audit_record, open_leg, selection_date
from app.purchasing_agent.wording import PendingWording, apply_wordings
from app.purchasing_agent.writer import MessageWriter
from app.supplier_service import service as supplier_service

SUPPLIER_MESSAGE_TYPES = {"ACCEPT": "ACCEPT", "COUNTER": "COUNTER_OFFER", "REJECT": "REJECT", None: "UNCLEAR"}


@dataclass(frozen=True)
class Decision:
    # AGREED, COUNTER_OFFER, FAILED, CLARIFICATION_REQUEST; REALLOCATE from `validate` only; NO_LONGER_NEEDED and
    # ABORTED (another Leg failed the procurement) from `_resolve` only
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
    ctx = _Context(message_id, now, today, settings)
    failure = None
    if decision.outcome == "REALLOCATE":
        leg.quantity_cap = reply.quantity
        decision, failure = _resolve(db, request, ctx, counter=_Counter(leg, reply))
    else:
        _apply(db, request, leg, reply, decision, ctx)
        if decision.outcome == "FAILED":
            _, failure = _resolve(db, request, ctx, failed=leg)
    _audit(db, request, leg, message_id, interpretation, offer.terms, state, clarifications, decision, failure)
    db.commit()  # releases the locks before the LLM words Purchasing's messages

    apply_wordings(db, MessageWriter(llm_client, _names(db, request)), ctx.pending)
    return Received(duplicate=False)


def re_sourcing_needed(db: Session, request: ProcurementRequest) -> bool:
    """A NEGOTIATING request whose open Legs no longer cover the shortage, e.g. after a timeout was recorded."""
    if request.status != RequestStatus.NEGOTIATING:
        return False
    allocated = db.scalar(select(func.coalesce(func.sum(PurchaseRequisition.allocated_quantity), 0)).where(
        PurchaseRequisition.procurement_request_id == request.id, PurchaseRequisition.status.in_(LegStatus.OPEN)))
    return allocated < request.shortage_quantity


def re_source(db: Session, request_id: uuid.UUID, now: datetime, settings: Settings, llm_client: LLMClient) -> bool:
    """Resolve a request whose missed deadlines were only recorded (§7.1, ADR-003). Idempotent: returns False and
    changes nothing unless re-sourcing is needed. The trigger is the request's most recently failed Leg."""
    request = db.get(ProcurementRequest, request_id, with_for_update=True, populate_existing=True)
    if request is None:
        raise AppError(ErrorCode.NOT_FOUND, "procurement request not found")
    failed = db.scalar(select(PurchaseRequisition)
                       .where(PurchaseRequisition.procurement_request_id == request.id,
                              PurchaseRequisition.status == LegStatus.FAILED)
                       .order_by(PurchaseRequisition.updated_at.desc(), PurchaseRequisition.id.desc()).limit(1))
    if failed is None or not re_sourcing_needed(db, request):
        db.rollback()
        return False
    ctx = _Context(None, now, selection_date(now, settings.purchasing_timezone), settings)
    _resolve(db, request, ctx, failed=failed)
    db.commit()
    apply_wordings(db, MessageWriter(llm_client, _names(db, request)), ctx.pending)
    return True


def re_source_before_reply(db: Session, leg_id: uuid.UUID, now: datetime, settings: Settings,
                           llm_client: LLMClient) -> None:
    """A supplier reply is the next write for its request: pending re-sourcing runs first. If that changed the
    replying Leg's conversation (a revised offer, or the Leg dropped), the reply answers an offer that no longer
    stands: 409 `offer: superseded`, as for any stale reply."""
    leg = db.get(PurchaseRequisition, leg_id)
    if leg is None:
        return  # `receive_supplier_message` answers 404
    session_id = leg.negotiation_session_id
    before = negotiation_engine.latest_message_id(db, session_id)
    request_id = leg.procurement_request_id
    db.rollback()
    if re_source(db, request_id, now, settings, llm_client) and \
            negotiation_engine.latest_message_id(db, session_id) != before:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, "the procurement was re-sourced and your offer changed; "
                       "reply to the current offer", [{"field": "offer", "issue": "superseded"}])


def _names(db: Session, request: ProcurementRequest) -> dict[uuid.UUID, str]:
    return {s.supplier_id: s.supplier_name for s in supplier_service.supplier_items_for(db, request.item_id)}


@dataclass
class _Context:
    """What every change for one write shares."""

    causation_id: uuid.UUID | None  # the supplier message that caused it; None for `re_source`
    now: datetime
    today: date
    settings: Settings
    pending: list[PendingWording] = field(default_factory=list)  # Purchasing's messages the LLM may word

    @property
    def due(self) -> datetime:
        """A message awaiting a reply is due by then."""
        return self.now + timedelta(hours=self.settings.purchasing_response_deadline_hours)


@dataclass(frozen=True)
class _Counter:
    """A supplier's quantity counter: its Leg (now capped) and its reply."""

    leg: PurchaseRequisition
    reply: SupplierReply


def _is_open(request: ProcurementRequest, leg: PurchaseRequisition, offer: negotiation_engine.Offer | None) -> bool:
    return leg.status == LegStatus.PENDING and request.status == RequestStatus.NEGOTIATING and offer is not None


@dataclass(frozen=True)
class ProcurementFailure:
    constrained_quantity: Decimal
    aborted_leg_ids: tuple[uuid.UUID, ...]


def _apply(db: Session, request: ProcurementRequest, leg: PurchaseRequisition, reply: SupplierReply | None,
           decision: Decision, ctx: _Context) -> None:
    """One Leg's decision. FAILED only fails the Leg: the caller resolves the request (`_resolve`)."""
    echo = messages.understood_text(reply.action, reply.quantity, reply.delivery_date) if reply else ""
    cause = ctx.causation_id
    if decision.outcome == "CLARIFICATION_REQUEST":
        _send(db, leg, cause, "CLARIFICATION_REQUEST", messages.clarification_text(echo), due=ctx.due,
              pending=ctx.pending, prefix=echo)
    elif decision.outcome == "COUNTER_OFFER":
        terms = messages.offer_terms(decision.quantity, decision.delivery_date)
        text = messages.counter_text(echo, decision.quantity, decision.delivery_date, request.required_date)
        _send(db, leg, cause, "COUNTER_OFFER", text, terms, due=ctx.due, pending=ctx.pending, prefix=echo)
    elif decision.outcome == "AGREED":
        _send(db, leg, cause, "CONFIRMATION", messages.agreed_text(echo, decision.quantity, decision.delivery_date),
              messages.offer_terms(decision.quantity, decision.delivery_date))
        negotiation_engine.close_session(db, leg.negotiation_session_id, "AGREED", None, ctx.now)
        leg.status, leg.agreed_quantity, leg.agreed_delivery_date = LegStatus.AGREED, decision.quantity, decision.delivery_date
        if leg.quantity_cap is not None and leg.quantity_cap < decision.quantity:
            leg.quantity_cap = decision.quantity  # a counter-back accepted lifts the cap (§7.4)
        _propose_if_all_agreed(db, request)
    elif decision.outcome == "NO_LONGER_NEEDED":
        _drop(db, leg, cause, f"{echo} {messages.NO_LONGER_NEEDED_TEXT}", ctx.now)
    else:
        _send(db, leg, cause, "CONFIRMATION", messages.closed_text(echo, decision.reason))
        negotiation_engine.close_session(db, leg.negotiation_session_id, "REJECTED", decision.reason, ctx.now)
        leg.status, leg.status_reason = LegStatus.FAILED, decision.reason
    db.flush()


def _propose_if_all_agreed(db: Session, request: ProcurementRequest) -> None:
    """The combined agreement is proposed once every open Leg is AGREED and together they cover the shortage (§7.6).
    FAILED and ABORTED Legs are history, not part of it."""
    db.flush()
    legs = db.execute(select(PurchaseRequisition.status, PurchaseRequisition.agreed_quantity).where(
        PurchaseRequisition.procurement_request_id == request.id,
        PurchaseRequisition.status.in_(LegStatus.OPEN))).all()
    if (legs and all(status == LegStatus.AGREED for status, _ in legs)
            and sum(quantity for _, quantity in legs) >= request.shortage_quantity):
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


def _resolve(db: Session, request: ProcurementRequest, ctx: _Context, failed: PurchaseRequisition | None = None,
             counter: _Counter | None = None) -> tuple[Decision | None, ProcurementFailure | None]:
    """§7.4–7.4.1. The open Legs no longer fit the procurement: `counter`'s Leg was capped by a quantity counter, or
    `failed` (already FAILED) dropped out. The caller holds the request lock.
    1. Reallocate among the open Legs, each limited by its cap (threshold not re-checked; `REALLOCATION` audit).
    2. Nothing fits → re-source: the selection rules over the open Legs and every eligible supplier without one
       (threshold re-checked; `RE_SOURCING` audit).
    3. Apply the result: open Legs not in it → ABORTED `no_longer_needed` (even if agreed); a changed quantity → a
       revised offer (a round; AGREED reopened); new and returning suppliers → a new Leg and offer. The countering Leg
       is AGREED when its new quantity is its counter with an on-time date, else countered with its new quantity.
       A Leg needing a round with none left FAILS `round_limit_exceeded` and the request is resolved again without it.
    4. Nothing feasible → the countering supplier is countered back with its current quantity while it has rounds
       (only if no Leg failed in this resolution); else the request FAILS (`fail_procurement`).
    Returns the countering Leg's decision (for the response audit; None without `counter`) and the failure, if any."""
    own: Decision | None = None
    countering = counter.leg if counter else None  # None once its Leg is no longer open
    any_failed = failed is not None
    while True:
        open_legs = list(db.scalars(select(PurchaseRequisition)
                                    .where(PurchaseRequisition.procurement_request_id == request.id,
                                           PurchaseRequisition.status.in_(LegStatus.OPEN))
                                    .order_by(PurchaseRequisition.created_at, PurchaseRequisition.id)
                                    .with_for_update()))
        availability = effective_availability(db, request.item_id, excluding_request_id=request.id)
        names = {supplier_id: a.supplier.supplier_name for supplier_id, a in availability.items()}
        options = [_selected_option(leg, availability[leg.supplier_id], ctx.today)
                   for leg in open_legs if leg.supplier_id in availability]
        trigger = countering or failed
        result = reallocate(request.shortage_quantity, request.required_date, options, ctx.today)
        found = None
        if result.outcome == "FAILED":
            if open_legs:
                _audit_reallocation(db, request, trigger, open_legs, options, result, names,
                                    {"next_step": "RE_SOURCING"}, "Re-sourcing over every eligible supplier.")
            found = re_sourcing.candidates(db, request, open_legs, availability, ctx.today,
                                           ctx.settings.purchasing_max_rounds)
            options = options + [c.option for c in found.candidates]
            result = select_suppliers(request.shortage_quantity, request.required_date, options, ctx.today,
                                      saving_threshold=ctx.settings.purchasing_cost_saving_split_threshold)

        if result.outcome == "FAILED":
            ended_by = failed
            if countering is not None:
                rounds_left = negotiation_engine.session_state(db, countering.negotiation_session_id).rounds_left
                if not any_failed and rounds_left > 0:
                    own = Decision("COUNTER_OFFER", countering.allocated_quantity, request.required_date,
                                   summary="no allocation fits, even re-sourced; countered back with the quantity "
                                           "needed")
                elif not any_failed:
                    own = Decision("FAILED", reason=LegReason.ROUND_LIMIT_EXCEEDED,
                                   summary="no allocation fits, even re-sourced, and no rounds are left")
                    ended_by = countering
                else:
                    own = Decision("ABORTED", reason=LegReason.SPLIT_FAILED,
                                   summary=f"{names.get(failed.supplier_id)}'s Leg failed and no allocation fits, "
                                           f"even re-sourced: the procurement failed")
            _audit_re_sourcing(db, request, trigger, open_legs, options, found, result, names, ctx, own, {})
            if own is not None and own.outcome == "COUNTER_OFFER":
                _apply(db, request, countering, counter.reply, own, ctx)
                return own, None
            if own is not None and own.outcome == "FAILED":
                _apply(db, request, countering, counter.reply, own, ctx)
            return own, fail_procurement(db, request, ended_by, ctx.causation_id, ctx.now, ctx.today)

        new = {leg.supplier_id: leg for leg in result.legs}
        if countering is not None:
            own = _countering_decision(countering, counter.reply, new, request.required_date, ctx.today)
        others = [leg for leg in open_legs if leg is not countering]
        dropped = [leg for leg in others if leg.supplier_id not in new]
        revised = [leg for leg in others
                   if leg.supplier_id in new and new[leg.supplier_id].quantity != leg.allocated_quantity]
        needs_round = revised + ([countering] if own is not None and own.outcome == "COUNTER_OFFER" else [])
        stuck = next((leg for leg in needs_round
                      if negotiation_engine.session_state(db, leg.negotiation_session_id).rounds_left <= 0), None)
        if stuck is not None:  # it FAILS, its supplier is excluded, and the request is resolved again
            if stuck is countering:
                own = Decision("FAILED", reason=LegReason.ROUND_LIMIT_EXCEEDED,
                               summary=f"{own.summary}, but no rounds are left")
                _apply(db, request, stuck, counter.reply, own, ctx)
                countering = None
            else:
                _fail_revision(db, stuck, ctx)
            failed, any_failed = stuck, True
            continue

        open_suppliers = {leg.supplier_id for leg in open_legs}
        added = [leg for leg in result.legs if leg.supplier_id not in open_suppliers]
        changes = {"dropped_suppliers": [names.get(leg.supplier_id) for leg in open_legs  # the countering Leg too
                                         if leg.supplier_id not in new],
                   "revised_suppliers": [names.get(leg.supplier_id) for leg in revised],
                   "added_suppliers": [leg.supplier_name for leg in added]}
        if found is None:
            _audit_reallocation(db, request, trigger, open_legs, options, result, names,
                                {**changes, "trigger_leg_outcome": own.outcome if own else None},
                                own.summary + "." if own else "")
        else:
            changes["returning_suppliers"] = [leg.supplier_name for leg in added
                                              if found.by_supplier(leg.supplier_id).returning]
            _audit_re_sourcing(db, request, trigger, open_legs, options, found, result, names, ctx, own, changes)

        for leg in dropped:
            _drop(db, leg, ctx.causation_id, messages.NO_LONGER_NEEDED_TEXT, ctx.now)
        for leg in revised:
            if leg.status == LegStatus.AGREED:
                negotiation_engine.reopen_session(db, leg.negotiation_session_id)
                leg.status, leg.agreed_quantity, leg.agreed_delivery_date = LegStatus.PENDING, None, None
            leg.allocated_quantity = new[leg.supplier_id].quantity
            terms = messages.offer_terms(leg.allocated_quantity, request.required_date)
            text = messages.revised_offer_text(leg.allocated_quantity, request.required_date)
            _send(db, leg, ctx.causation_id, "COUNTER_OFFER", text, terms, due=ctx.due, pending=ctx.pending)
        if added:
            item = supplier_service.get_item(db, request.item_id)
            for leg in added:
                candidate = found.by_supplier(leg.supplier_id)
                ctx.pending.append(open_leg(db, request, item, leg, ctx.now, ctx.settings,
                                            max_rounds=candidate.rounds_left, quantity_cap=candidate.quantity_cap))
        request.split_type, request.cost_ranking_available = result.outcome, result.cost_ranking_available
        if countering is not None:
            if countering.supplier_id in new:
                countering.allocated_quantity = new[countering.supplier_id].quantity
            _apply(db, request, countering, counter.reply, own, ctx)
        _propose_if_all_agreed(db, request)
        return own, None


def _countering_decision(leg: PurchaseRequisition, reply: SupplierReply, new: dict[uuid.UUID, Leg],
                         required_date: date, today: date) -> Decision:
    """§7.4: the countering Leg under the new allocation."""
    if leg.supplier_id not in new:
        return Decision("NO_LONGER_NEEDED", summary="the new allocation no longer needs this supplier")
    quantity = new[leg.supplier_id].quantity
    if quantity == reply.quantity and reply.delivery_date is not None and on_time(reply.delivery_date, required_date,
                                                                                  today):
        return Decision("AGREED", reply.quantity, reply.delivery_date,
                        summary="the new allocation takes the countered quantity by an on-time date")
    return Decision("COUNTER_OFFER", quantity, required_date,
                    summary="countered with the newly allocated quantity by the required date")


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


def _fail_revision(db: Session, leg: PurchaseRequisition, ctx: _Context) -> None:
    """A Leg the new allocation must revise has no rounds left: it FAILS `round_limit_exceeded` (an agreed one is first
    reopened, so its session can end REJECTED)."""
    if leg.status == LegStatus.AGREED:
        negotiation_engine.reopen_session(db, leg.negotiation_session_id)
    _send(db, leg, ctx.causation_id, "CONFIRMATION", messages.REVISION_ROUND_LIMIT_TEXT)
    negotiation_engine.close_session(db, leg.negotiation_session_id, "REJECTED", LegReason.ROUND_LIMIT_EXCEEDED,
                                     ctx.now)
    leg.status, leg.status_reason = LegStatus.FAILED, LegReason.ROUND_LIMIT_EXCEEDED
    db.flush()


def fail_procurement(db: Session, request: ProcurementRequest, failed_leg: PurchaseRequisition,
                     causation_id: uuid.UUID | None, now: datetime, today: date) -> ProcurementFailure:
    """All or nothing (§7.5), once reallocation and re-sourcing found nothing (`_resolve`): `failed_leg` (already FAILED
    by the caller, who holds the request lock) is the Leg whose failure ended the procurement. Every other PENDING or
    AGREED Leg is told, ABORTED `split_failed` and its Engine session CANCELLED, which releases its hold. Nothing is
    committed; the failure is final: the requester decides whether to resubmit."""
    others = list(db.scalars(select(PurchaseRequisition)
                             .where(PurchaseRequisition.procurement_request_id == request.id,
                                    PurchaseRequisition.id != failed_leg.id)
                             .order_by(PurchaseRequisition.created_at, PurchaseRequisition.id)
                             .with_for_update()))
    constrained = _constrained_quantity(db, request, failed_leg, others, today)
    aborted = [leg for leg in others if leg.status in LegStatus.OPEN]
    for leg in aborted:
        cancel_leg(db, leg, messages.CANCELLED_TEXT, LegReason.SPLIT_FAILED, now, causation_id)
    request.status, request.status_reason = RequestStatus.FAILED, (f"a Leg failed: {failed_leg.status_reason}; "
                                                         f"no feasible allocation remains")
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


def _audit_reallocation(db: Session, request: ProcurementRequest, trigger: PurchaseRequisition,
                        selected: list[PurchaseRequisition], options: list[SupplierOption], result: Selection,
                        names: dict[uuid.UUID, str], outcome: dict, summary: str) -> None:
    """The revised allocation among the open Legs (or why none fits), and the actual saving against the latest best
    priced single supplier (of the original selection or the last re-sourcing; the threshold is not re-checked).
    `outcome`: what the result changes, or the next step when nothing fits."""
    before = {names.get(s.supplier_id): messages.quantity_text(s.allocated_quantity) for s in selected}
    prices = [s.unit_price_at_selection for s in selected]
    before_cost = (sum((s.unit_price_at_selection * s.allocated_quantity for s in selected), Decimal(0))
                   if None not in prices else None)
    latest = db.scalar(select(DecisionAudit.decision).where(
        DecisionAudit.procurement_request_id == request.id,
        DecisionAudit.decision_type.in_(("SUPPLIER_SELECTION", "RE_SOURCING")),
    ).order_by(DecisionAudit.created_at.desc(), DecisionAudit.id.desc()).limit(1)) or {}
    reference = latest.get("best_priced_single")
    saving = None
    if reference and result.total_cost is not None:
        reference_cost = Decimal(reference["total_cost"])
        saving = ((reference_cost - result.total_cost) / reference_cost * 100).quantize(Decimal("0.01"))
    db.add(DecisionAudit(
        procurement_request_id=request.id, decision_type="REALLOCATION",
        context=audit_record({
            "trigger_leg_id": trigger.id,
            "supplier_id": trigger.supplier_id,
            "trigger": trigger.status_reason if trigger.status == LegStatus.FAILED else "quantity_counter",
            "quantity_cap": messages.quantity_text(trigger.quantity_cap) if trigger.quantity_cap is not None else None,
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
            **outcome,
        }),
        reasoning_summary=f"{result.reasoning_summary} {summary}".strip(),
    ))


def _audit_re_sourcing(db: Session, request: ProcurementRequest, trigger: PurchaseRequisition,
                       open_legs: list[PurchaseRequisition], options: list[SupplierOption],
                       found: re_sourcing.Candidates, result: Selection, names: dict[uuid.UUID, str], ctx: _Context,
                       own: Decision | None, changes: dict) -> None:
    summary = result.reasoning_summary + (f" {own.summary}." if own else "")
    re_sourcing.audit(db, request, trigger, open_legs, options, found, result, names,
                      ctx.settings.purchasing_cost_saving_split_threshold,
                      {**changes, "trigger_leg_outcome": own.outcome if own else None}, summary)


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
