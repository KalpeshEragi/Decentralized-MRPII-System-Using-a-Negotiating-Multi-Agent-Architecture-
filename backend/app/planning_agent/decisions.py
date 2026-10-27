"""Planning's decision point D7 (`architecture/quotes_and_agent_decisions.md` §5, QD-6, QD-7).

While Planning secures an option for a new customer request, an owner may answer with a COUNTER_OFFER (less, or
later) or a REJECT (STALE, INSUFFICIENT, …). Before, any such answer failed the whole option. Now Planning thinks:

    RE_ASK            ask the same owner again for the same terms (after STALE / HOLD_EXPIRED / UNAVAILABLE, ≤ 2 times)
    ACCEPT_COUNTER    take the counter as it is — only when it still gives the full quantity in time (customer date holds)
    PARTIAL_AND_BUY   take Inventory's smaller quantity and ask Purchasing for the rest by the same date
    NEXT_OPTION       give up this option and secure the next one (today's rule; replan once when none is left, S8-1)
    REPLAN            give up this option and the remaining ones: plan again from today's facts (once per order)

The agent chooses with the shared think loop; `validate` keeps every choice inside the hard rules, and `fallback` is
the deterministic policy (QD-6: re-ask a stale answer while tries are left, otherwise today's rule). With AI on the
model runs in a long-mode work item (no lock held); with AI off the fallback is applied at once.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.agent_decisions import Decision, Situation, decision_client, record, think
from app.agent_decisions.think import AI_OFF
from app.core.work_runner import enqueue
from app.models.core import Item
from app.negotiation import layer
from app.negotiation.envelope import Envelope, MessageType as M, ReasonCode, ResourceType, Terms
from app.planning_agent.models import AuditLog, Case, CustomerDemand, Option, WorkItem

POINT = "D7"
MAX_REASKS = 2  # QD-6
RETRYABLE = {ReasonCode.STALE.value, ReasonCode.HOLD_EXPIRED.value, ReasonCode.UNAVAILABLE.value}
DECIDE = "DECIDE"  # work item kind (long mode)

GOAL = ("Get this customer order secured with as little disruption as possible: keep what the other owners already "
        "agreed, keep the customer's date when you can, and give up an option only when it cannot work any more.")

ACTIONS = {
    "RE_ASK": "Ask the same owner again for the same terms. Only after a STALE, HOLD_EXPIRED or UNAVAILABLE reject "
              "(someone took the resource first), at most 2 times per need. params: {}",
    "ACCEPT_COUNTER": "Accept the owner's counter-offer as it is. Only if it still gives the full quantity no later "
                      "than you need it (then the plan and the customer's date hold). params: {}",
    "PARTIAL_AND_BUY": "Accept the smaller quantity Inventory offered now and ask Purchasing to supply the rest by the "
                       "same date. Only for bought materials needed by a production order. params: {}",
    "NEXT_OPTION": "Give up this option: release what it holds and secure the next option; when none is left, plan "
                   "once more from today's facts. params: {}",
    "REPLAN": "Give up this option and the remaining ones and plan again from today's facts (usually a later date "
              "for the customer). Only once per order. params: {}",
}


@dataclass
class Setback:
    """What happened to one negotiation of the case, and what Planning knows about it (all from its own records)."""

    owner: str
    need: str
    reply: str                    # COUNTER_OFFER or REJECT
    reason: str | None
    asked: Terms
    counter: Terms | None
    tries: int
    sourcing: str | None          # BUY or MAKE for an item, None for hours or space
    options_left: int
    replanned: bool


# -- the checks and the deterministic policy (pure, no database) ---------------------------------------------------------


def validate(s: Setback, action: str, params: dict[str, Any]) -> str | None:
    """None when `action` is allowed now, else the reason (given back to the agent for one revision)."""
    if action == "RE_ASK":
        if s.reply != M.REJECT.value or s.reason not in RETRYABLE:
            return f"re-asking only helps after a STALE, HOLD_EXPIRED or UNAVAILABLE reject; this was {s.reply} {s.reason}"
        if s.tries >= MAX_REASKS:
            return f"this need was already re-asked {s.tries} times (limit {MAX_REASKS})"
        return None
    if action == "ACCEPT_COUNTER":
        if s.reply != M.COUNTER_OFFER.value or s.counter is None:
            return "there is no counter-offer to accept"
        if s.counter.quantity < s.asked.quantity:
            return f"the counter gives {s.counter.quantity}, the plan needs {s.asked.quantity}"
        if _latest_day(s.counter) > _latest_day(s.asked):
            return (f"the counter comes on {_latest_day(s.counter)}, after the plan needs it ({_latest_day(s.asked)}); "
                    "the customer's date would not hold — use REPLAN for a later date")
        return None
    if action == "PARTIAL_AND_BUY":
        if s.reply != M.COUNTER_OFFER.value or s.counter is None:
            return "there is no counter-offer with a smaller quantity"
        if s.owner != "INVENTORY" or s.asked.resource_type != ResourceType.STOCK:
            return "only a stock counter-offer from Inventory can be split with Purchasing"
        if not (0 < s.counter.quantity < s.asked.quantity):
            return "the counter is not a smaller quantity"
        if _latest_day(s.counter) > _latest_day(s.asked):
            return "the smaller quantity also comes too late"
        if s.sourcing != "BUY" or s.asked.extra.get("for_kind") != "PRODUCTION_ORDER":
            return "Purchasing can only supply bought materials for a production order"
        return None
    if action == "NEXT_OPTION":
        return None
    if action == "REPLAN":
        return "this order was already replanned once" if s.replanned else None
    return f"unknown action {action}"


def fallback(s: Setback) -> tuple[str, dict]:
    """The deterministic policy: re-ask a stale answer while tries are left (QD-6), otherwise today's rule."""
    return ("RE_ASK", {}) if validate(s, "RE_ASK", {}) is None else ("NEXT_OPTION", {})


def _latest_day(terms: Terms) -> date:
    days = [date.fromisoformat(d) for d in terms.extra.get("hours_by_day", {})]
    if days:
        return max(days)
    return terms.available_from or terms.needed_by or terms.date_to or date.max


# -- reading the situation -------------------------------------------------------------------------------------------------


def setback(db: DbSession, case: Case, session_id: str) -> Setback:
    entry = case.sessions[session_id]
    message = Envelope.model_validate(entry["setback"])
    asked = Terms.model_validate(entry["terms"])
    item = db.get(Item, uuid.UUID(asked.resource_ref)) if asked.resource_type in (ResourceType.STOCK,
                                                                                    ResourceType.SUPPLY) else None
    from app.planning_agent import manager  # the same counting the fixed rule uses

    demand = db.get(CustomerDemand, case.demand_id)
    options_left = sum(1 for o in manager._options(db, demand) if o.status == "OFFERED" and o.id != case.option_id)
    return Setback(owner=entry["owner"], need=entry["need"], reply=message.message_type.value,
                   reason=message.reason_code.value if message.reason_code else None, asked=asked,
                   counter=message.terms if message.message_type == M.COUNTER_OFFER else None,
                   tries=int(entry.get("tries", 0)), sourcing=item.sourcing if item else None,
                   options_left=options_left, replanned=manager._replanned(db, demand))


def situation(db: DbSession, case: Case, session_id: str, s: Setback) -> Situation:
    demand = db.get(CustomerDemand, case.demand_id)
    option = db.get(Option, case.option_id)
    others = [v["status"] for k, v in case.sessions.items() if k != session_id and v["status"] != "REPLACED"]
    facts = {
        "customer_order": {"quantity": demand.quantity, "wanted_by": demand.requested_day,
                           "option_being_secured": option.kind, "option_delivery_day": option.delivery_day},
        "what_happened": {"owner": s.owner, "about": s.need, "answer": s.reply, "reason": s.reason,
                          "you_asked": _terms_view(s.asked), "they_counter": _terms_view(s.counter) if s.counter else None},
        "item_is": {"BUY": "bought from suppliers", "MAKE": "made in the factory"}.get(s.sourcing or "", "not an item"),
        "need_is_for": s.asked.extra.get("for_kind"),
        "re_asks_used": s.tries, "re_asks_allowed": MAX_REASKS,
        "other_options_left": s.options_left, "already_replanned": s.replanned,
        "other_negotiations_of_this_option": {status: others.count(status) for status in sorted(set(others))},
    }
    return Situation(agent="PLANNING", point=POINT, goal=GOAL, facts=facts, actions=ACTIONS,
                     hints=[{"todays_rule": fallback(s)[0]}], case_id=case.id, order_id=str(case.demand_id))


def _terms_view(terms: Terms) -> dict[str, Any]:
    view = {"resource": terms.resource_type.value, "quantity": terms.quantity, "unit": terms.unit,
            "needed_by": terms.needed_by, "available_from": terms.available_from}
    if terms.extra.get("hours_by_day"):
        view["hours_by_day"] = terms.extra["hours_by_day"]
    return {k: v for k, v in view.items() if v is not None}


# -- entry point from Planning's inbox, the long-mode work item, and applying a choice ---------------------------------------


def on_setback(db: DbSession, case: Case, session: Any, message: Envelope) -> None:
    """Called under the case lock when an owner counters or rejects while the option is being secured."""
    sid = str(session.id)
    case.sessions = {**case.sessions, sid: {**case.sessions[sid], "status": "DECIDING",
                                            "setback": message.model_dump(mode="json")}}
    if decision_client(db) is None:  # AI off or a load run: the deterministic policy, at once
        s = setback(db, case, sid)
        action, params = fallback(s)
        decision = Decision(action, params, "FALLBACK", reason="deterministic policy", fallback=(action, params),
                            fallback_reason=AI_OFF)
        apply(db, case, sid, s, decision.action)
        record(db, AuditLog, situation(db, case, sid, s), decision)
        return
    enqueue(db, WorkItem, scope_key=case.id, kind=DECIDE, payload={"case_id": case.id, "session_id": sid})


def run_decision(session_factory, item, renew) -> None:
    """Long-mode work item DECIDE: think without any lock, then re-check and apply under the case lock."""
    case_id, sid = item.payload["case_id"], item.payload["session_id"]
    with session_factory() as db:
        case = db.get(Case, case_id)
        if not _still_deciding(case, sid):
            return
        s = setback(db, case, sid)
        seen = situation(db, case, sid, s)
        client = decision_client(db)
        db.rollback()  # no transaction while the model thinks
    decision = think(seen, lambda action, params: validate(s, action, params), fallback(s), client)
    with session_factory() as db:
        case = db.get(Case, case_id, with_for_update=True)
        if not _still_deciding(case, sid):
            return
        fresh = setback(db, case, sid)  # facts may have changed while the agent thought
        if validate(fresh, decision.action, decision.params) is not None:
            action, params = fallback(fresh)
            decision = Decision(action, params, "FALLBACK", reason="facts changed while thinking",
                                thinking=decision.thinking, fallback=(action, params), fallback_reason="STALE",
                                refusals=decision.refusals, calls=decision.calls)
        apply(db, case, sid, fresh, decision.action)
        record(db, AuditLog, seen, decision)
        db.commit()


def _still_deciding(case: Case | None, sid: str) -> bool:
    return case is not None and case.status == "OPEN" and case.sessions.get(sid, {}).get("status") == "DECIDING"


def apply(db: DbSession, case: Case, sid: str, s: Setback, action: str) -> None:
    """Carry out a checked choice through the normal protocol (caller holds the case lock and commits)."""
    from app.planning_agent import manager

    message = Envelope.model_validate(case.sessions[sid]["setback"])
    if action == "RE_ASK":
        _set_status(case, sid, "REPLACED")
        manager._request(db, case, s.owner, s.asked, s.need, tries=s.tries + 1)
    elif action in ("ACCEPT_COUNTER", "PARTIAL_AND_BUY"):
        _set_status(case, sid, "OPEN")  # the owner now places a hold on the counter terms
        layer.send(db, layer.reply_to(message, M.ACCEPT, text="accept the counter-offer"))
        if action == "PARTIAL_AND_BUY":
            rest = s.asked.quantity - s.counter.quantity
            manager._request(db, case, "PURCHASING", Terms(
                resource_type=ResourceType.SUPPLY, resource_ref=s.asked.resource_ref, quantity=rest,
                needed_by=s.asked.needed_by, order_id=s.asked.order_id, extra={"for_kind": "PRODUCTION_ORDER"}),
                f"supply {s.asked.resource_ref} (rest)")
    else:  # NEXT_OPTION or REPLAN: today's handling of a failed option
        _set_status(case, sid, "REJECTED")
        if s.reply == M.COUNTER_OFFER.value:
            layer.send(db, layer.reply_to(message, M.REJECT, reason_code=message.reason_code, text="cannot use that"))
            reason = f"COUNTER_{message.reason_code}"
        else:
            reason = message.reason_code.value if message.reason_code else "REJECTED"
        manager._fail_case(db, case, reason, skip_options=action == "REPLAN")


def _set_status(case: Case, sid: str, status: str) -> None:
    case.sessions = {**case.sessions, sid: {**case.sessions[sid], "status": status}}


def decisions_of(db: DbSession, case_id: str) -> list[dict]:
    """D7 records of one case (tests and views)."""
    return [row.details for row in db.scalars(select(AuditLog).where(AuditLog.case_id == case_id,
                                                                      AuditLog.event_type == "DECISION"))]
