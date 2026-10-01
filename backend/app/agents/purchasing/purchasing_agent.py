"""Purchasing Agent (Phase 3). Owns procurement for a shortage: supplier evaluation, the purchase requisition and the
negotiation with the supplier interface (the supplier form; there is no Supplier Agent).

Each turn, deterministic services give the facts (the shortage = the session objective, supplier options, planning
date). The LLM proposes the next step (`NegotiationProposal`); `validate_proposal` checks it against the agent's hard
limits; an unusable or invalid proposal is recorded and the agent's own deterministic policy (`policy_decision`)
decides instead. The protocol then checks form and order, and `check_agreement` runs again on AGREEMENT_PROPOSED.

Limits come from supplier data, never from the LLM:
    supplier        among suppliers that cover the shortage alone (fixture rule 5.1): earliest arrival, then larger
                    available quantity, then name
    quantity        [max(shortage, supplier MOQ), supplier available quantity]
    delivery_date   own offers: [planning date + supplier lead time, shortage required_by]
                    supplier terms: [planning date, required_by] (a supplier may commit to faster than its lead time)
    round limit     after the round-3 response an acceptable response is agreed; otherwise the counter ends the
                    session FAILED (round exhaustion is FAILED, not REJECTED)
Split procurement (several suppliers for one shortage) cannot be expressed in one session; Purchasing then REJECTs.
The agent never sends COMMIT (approval workflow, C8) and never touches inventory or plans.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.agents.base import (
    SUMMARY_MAX,
    Agent,
    AgentStateData,
    DialogueEntry,
    Goal,
    NegotiationRules,
    Refs,
    Task,
    build_message,
    llm_client,
    now,
    offer_history,
    plain,
)
from app.llm.client import LLMClient, LLMError
from app.llm.prompts import PURCHASING_TASK, build_messages
from app.llm.reasoning import NegotiationProposal, StructuredOutputError, propose
from app.mrpii.agreement import check_agreement
from app.mrpii.suppliers import arrival_date, covers_alone, is_split_feasible, is_usable
from app.schemas.domain import Shortage, SupplierOption
from app.schemas.negotiation import MAX_ROUNDS, AgentType, MessageType, NegotiationMessage, OfferTerms, SessionStatus
from app.services import negotiation_service, order_service, requisition_service, supplier_service
from app.services.audit_service import AGENT_PURCHASING, DecisionType

M = MessageType
LLM, POLICY = "LLM", "POLICY"


# -- deterministic limits and policy (pure, no database) -----------------------------------------------------------


@dataclass(frozen=True)
class Limits:
    supplier: SupplierOption | None  # None: no supplier covers the shortage alone
    min_quantity: Decimal
    max_quantity: Decimal
    earliest_delivery: date | None
    latest_delivery: date


def choose_supplier(options: tuple[SupplierOption, ...], shortage: Shortage, planning_date: date) -> SupplierOption | None:
    candidates = [
        option
        for option in options
        if covers_alone(option, planning_date, shortage.required_by, shortage.shortage_quantity)
    ]
    return min(
        candidates, key=lambda o: (arrival_date(o, planning_date), -o.available_qty, o.supplier), default=None
    )


def limits_for(shortage: Shortage, options: tuple[SupplierOption, ...], planning_date: date) -> Limits:
    supplier = choose_supplier(options, shortage, planning_date)
    if supplier is None:
        quantity = shortage.shortage_quantity
        return Limits(None, quantity, quantity, None, shortage.required_by)
    return Limits(
        supplier,
        max(shortage.shortage_quantity, supplier.min_order_qty),
        supplier.available_qty,
        arrival_date(supplier, planning_date),
        shortage.required_by,
    )


@dataclass(frozen=True)
class Situation:
    """What Purchasing knows at its turn."""

    shortage: Shortage
    planning_date: date
    options: tuple[SupplierOption, ...]
    round_number: int  # supplier rounds opened so far; 0 before the first OFFER
    supplier_response: MessageType | None = None  # ACCEPT / COUNTER_OFFER of the current round
    on_table: OfferTerms | None = None  # the terms that response puts on the table
    history: tuple[dict, ...] = ()

    @property
    def limits(self) -> Limits:
        return limits_for(self.shortage, self.options, self.planning_date)


@dataclass(frozen=True)
class Decision:
    message_type: MessageType  # OFFER, COUNTER_OFFER, AGREEMENT_PROPOSED or REJECT
    terms: OfferTerms | None
    rationale: str
    source: str = POLICY
    llm_proposal: dict | None = None
    llm_problems: tuple[str, ...] = ()


def _terms(s: Situation, quantity: Decimal, delivery: date | None) -> OfferTerms:
    """Offer terms for this shortage; required_date and priority always come from the shortage."""
    return OfferTerms(
        quantity=quantity, delivery_date=delivery, required_date=s.shortage.required_by, priority=s.shortage.priority
    )


def own_terms_problems(terms: OfferTerms, lim: Limits) -> list[str]:
    """Why terms Purchasing would propose break its limits (empty = within limits)."""
    if lim.supplier is None:
        return ["no supplier can cover the shortage alone"]
    problems = []
    if not lim.min_quantity <= terms.quantity <= lim.max_quantity:
        problems.append(f"quantity {terms.quantity} outside [{lim.min_quantity}, {lim.max_quantity}]")
    if terms.delivery_date is None or not lim.earliest_delivery <= terms.delivery_date <= lim.latest_delivery:
        problems.append(f"delivery_date {terms.delivery_date} outside [{lim.earliest_delivery}, {lim.latest_delivery}]")
    return problems


def acceptance_problems(terms: OfferTerms, s: Situation) -> list[str]:
    """Why supplier terms cannot be agreed (empty = acceptable): shortage covered by required_by, supplier bounds."""
    lim = s.limits
    problems = check_agreement(terms, s.shortage)
    if lim.supplier is None:
        problems.append("no supplier can cover the shortage alone")
    elif terms.quantity >= s.shortage.shortage_quantity and not is_split_feasible(
        [(lim.supplier, terms.quantity)], s.planning_date, s.shortage.required_by, s.shortage.shortage_quantity
    ):
        problems.append(
            f"quantity {terms.quantity} outside {lim.supplier.supplier}'s bounds "
            f"[{lim.supplier.min_order_qty}, {lim.supplier.available_qty}]"
        )
    if terms.delivery_date is not None and terms.delivery_date < s.planning_date:
        problems.append(f"delivery_date {terms.delivery_date} is before the planning date {s.planning_date}")
    return problems


def policy_decision(s: Situation) -> Decision:
    """Purchasing's own deterministic policy: meet the required date first, prefer the earliest delivery."""
    lim, shortage = s.limits, s.shortage
    if s.supplier_response is None:
        if lim.supplier is None:
            return Decision(
                M.REJECT,
                None,
                f"No supplier can deliver {shortage.shortage_quantity} by {shortage.required_by} alone; "
                "split procurement is not handled in one session.",
            )
        return Decision(
            M.OFFER,
            _terms(s, lim.min_quantity, lim.earliest_delivery),
            f"Offer {lim.min_quantity} for {lim.earliest_delivery} to {lim.supplier.supplier}: the earliest usable "
            "supplier that covers the shortage alone.",
        )
    problems = acceptance_problems(s.on_table, s)
    if not problems:
        return Decision(
            M.AGREEMENT_PROPOSED,
            _terms(s, s.on_table.quantity, s.on_table.delivery_date),
            f"Supplier terms {s.on_table.quantity} by {s.on_table.delivery_date} cover the shortage by "
            f"{shortage.required_by} within the supplier's bounds.",
        )
    if lim.supplier is None:
        return Decision(M.REJECT, None, "No supplier can cover the shortage alone any more: " + "; ".join(problems))
    counter = _terms(
        s,
        min(max(s.on_table.quantity, lim.min_quantity), lim.max_quantity),
        min(max(s.on_table.delivery_date, lim.earliest_delivery), lim.latest_delivery),
    )
    if s.round_number >= MAX_ROUNDS:
        return Decision(
            M.COUNTER_OFFER,
            counter,
            f"Round {MAX_ROUNDS} of {MAX_ROUNDS} ended without acceptable terms ({'; '.join(problems)}); "
            "the round limit is reached.",
        )
    return Decision(
        M.COUNTER_OFFER,
        counter,
        f"Counter with {counter.quantity} by {counter.delivery_date}: {'; '.join(problems)}.",
    )


def validate_proposal(p: NegotiationProposal, s: Situation) -> list[str]:
    """Deterministic check of an LLM proposal against the limits, the table and the round limit (empty = valid)."""
    lim = s.limits
    if s.supplier_response is None:
        if p.action == "ACCEPT":
            return ["there is no supplier response to accept before round 1"]
        if p.action == "REJECT":
            return [] if lim.supplier is None else [f"{lim.supplier.supplier} can cover the shortage; REJECT not allowed"]
        return own_terms_problems(_terms(s, p.terms.quantity, p.terms.delivery_date), lim)

    table_problems = acceptance_problems(s.on_table, s)
    last_round = s.round_number >= MAX_ROUNDS
    if p.action == "ACCEPT":
        return [f"supplier terms are not acceptable: {'; '.join(table_problems)}"] if table_problems else []
    if p.action == "REJECT":
        if not table_problems:
            return ["supplier terms are acceptable; REJECT would discard a feasible agreement"]
        return ["the round limit is reached: the session ends FAILED, not REJECTED"] if last_round else []
    terms = _terms(s, p.terms.quantity, p.terms.delivery_date)
    problems = own_terms_problems(terms, lim)
    if not table_problems and last_round:
        problems.append("countering acceptable terms in the last round would end the session FAILED")
    if (terms.quantity, terms.delivery_date) == (s.on_table.quantity, s.on_table.delivery_date):
        problems.append("the counter repeats the terms on the table")
    return problems


def _from_proposal(p: NegotiationProposal, s: Situation) -> Decision:
    rationale = p.rationale.strip()[:SUMMARY_MAX] or "LLM proposal"
    if p.action == "ACCEPT":
        return Decision(M.AGREEMENT_PROPOSED, _terms(s, s.on_table.quantity, s.on_table.delivery_date), rationale, LLM)
    if p.action == "REJECT":
        return Decision(M.REJECT, None, rationale, LLM)
    kind = M.OFFER if s.supplier_response is None else M.COUNTER_OFFER
    return Decision(kind, _terms(s, p.terms.quantity, p.terms.delivery_date), rationale, LLM)


def prompt_context(s: Situation) -> dict:
    lim, shortage = s.limits, s.shortage
    return {
        "round": f"{s.round_number} of {MAX_ROUNDS}" if s.round_number else f"before round 1 of {MAX_ROUNDS}",
        "shortage": {
            "quantity": shortage.shortage_quantity,
            "required_by": shortage.required_by,
            "priority": shortage.priority,
            "available_quantity": shortage.available_quantity,
        },
        "planning_date": s.planning_date,
        "supplier_options": [
            {
                "supplier": o.supplier,
                "lead_time_days": o.lead_time_days,
                "min_order_qty": o.min_order_qty,
                "available_qty": o.available_qty,
                "arrival_date": arrival_date(o, s.planning_date),
                "usable": is_usable(o, s.planning_date, shortage.required_by),
                "covers_alone": covers_alone(o, s.planning_date, shortage.required_by, shortage.shortage_quantity),
            }
            for o in s.options
        ],
        "selected_supplier": lim.supplier.supplier if lim.supplier else None,
        "limits": {
            "min_quantity": lim.min_quantity,
            "max_quantity": lim.max_quantity,
            "earliest_delivery": lim.earliest_delivery,
            "latest_delivery": lim.latest_delivery,
        },
        "supplier_response": s.supplier_response,
        "terms_on_table": s.on_table.model_dump(mode="json") if s.on_table else None,
        "history": list(s.history),
    }


def decide(s: Situation, llm: LLMClient) -> Decision:
    """The LLM proposes; deterministic validation decides whether the proposal is used or the own policy applies."""
    messages = build_messages(PURCHASING_TASK, prompt_context(s), NegotiationProposal.model_json_schema())
    try:
        proposal = propose(llm, messages, NegotiationProposal)
    except (LLMError, StructuredOutputError) as exc:
        return replace(policy_decision(s), llm_problems=(f"no usable LLM proposal: {str(exc)[:200]}",))
    problems = validate_proposal(proposal, s)
    if problems:
        return replace(policy_decision(s), llm_proposal=proposal.model_dump(mode="json"), llm_problems=tuple(problems))
    return _from_proposal(proposal, s)


# -- the agent (services, A2A, state, audit) -------------------------------------------------------------------------

REQUISITION_STATUS = {"AGREEMENT_PROPOSED", "REJECTED", "FAILED"}


class PurchasingAgent(Agent):
    agent_code = AGENT_PURCHASING

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm

    def on_message(self, db: Session, message: NegotiationMessage) -> None:
        """React to an accepted message addressed to Purchasing: Inventory's REQUEST or a supplier response."""
        negotiation_id = uuid.UUID(message.negotiation_id)
        view = negotiation_service.get_session_view(db, negotiation_id)
        s = self._situation(db, view)
        if view["status"] != SessionStatus.NEGOTIATING.value:  # the supplier interface rejected: nothing to decide
            self._record(db, view, s, "SUPPLIER_INTERFACE", f"The supplier interface ended the session {view['status']}.")
            return
        if view["awaiting_supplier"]:
            return  # not Purchasing's turn
        if message.message_type == M.REQUEST:
            requisition_service.create(db, negotiation_id, s.shortage, self.agent_code)

        decision = decide(s, self.llm or llm_client())
        context = {"order_id": s.shortage.order_id, "item_id": s.shortage.item_id, "negotiation_id": view["id"]}
        if decision.llm_problems:
            self.audit(
                db, DecisionType.LLM_PROPOSAL_REJECTED, context,
                {"round": s.round_number, "proposal": decision.llm_proposal, "problems": list(decision.llm_problems)},
                "LLM proposal not used; the agent's deterministic policy decided: " + "; ".join(decision.llm_problems),
            )
        to_supplier = decision.message_type in (M.OFFER, M.COUNTER_OFFER)
        receiver = AgentType.SUPPLIER_INTERFACE if to_supplier else AgentType.INVENTORY
        note = self._note(decision, s) if to_supplier else decision.rationale
        ack = self.send(db, build_message(view, AgentType.PURCHASING, receiver, decision.message_type, decision.terms, note))

        view = negotiation_service.get_session_view(db, negotiation_id)
        self.audit(
            db, DecisionType.NEGOTIATION_DECISION, context,
            {"message_type": decision.message_type, "terms": decision.terms, "source": decision.source,
             "round": view["round_number"], "accepted": ack["accepted"], "error": ack.get("error"),
             "session_status": view["status"]},
            decision.rationale,
        )
        summary = decision.rationale if ack["accepted"] else (
            f"{decision.message_type.value} refused by the protocol: {ack['error']['message']}"
        )
        self._record(db, view, s, receiver.value, summary)

    def _situation(self, db: Session, view: dict) -> Situation:
        shortage = Shortage.model_validate(view["objective"])
        planning_date = order_service.get_order(db, uuid.UUID(shortage.order_id)).order_date  # as in planning_service
        messages = view["messages"]
        response, on_table = None, None
        last = messages[-1] if messages else None
        if last and last["sender"] == "SUPPLIER_INTERFACE" and last["message_type"] in ("ACCEPT", "COUNTER_OFFER"):
            response = MessageType(last["message_type"])
            if response == M.COUNTER_OFFER:
                on_table = OfferTerms.model_validate(last["payload"]["terms"])
            else:
                own = next(m for m in reversed(messages)
                           if m["sender"] == "PURCHASING" and m["message_type"] in ("OFFER", "COUNTER_OFFER"))
                on_table = OfferTerms.model_validate(own["payload"]["terms"])
        history = tuple(
            {"sequence": m["sequence_number"], "type": m["message_type"], "from": m["sender"],
             "terms": m["payload"].get("terms")}
            for m in messages
        )
        options = tuple(supplier_service.supplier_options(db, shortage.item_id))
        return Situation(shortage, planning_date, options, view["round_number"], response, on_table, history)

    @staticmethod
    def _note(decision: Decision, s: Situation) -> str:
        next_round = s.round_number + 1
        if next_round > MAX_ROUNDS:
            return "Round limit reached; no further round."
        supplier = s.limits.supplier.supplier if s.limits.supplier else "supplier"
        return (f"Round {next_round} of {MAX_ROUNDS} - {supplier}: {decision.terms.quantity} units, delivery by "
                f"{decision.terms.delivery_date} (required by {s.shortage.required_by}).")

    def _record(self, db: Session, view: dict, s: Situation, counterpart: str, summary: str) -> None:
        """Requisition status and C6 state for this negotiation, then commit."""
        negotiation_id = uuid.UUID(view["id"])
        if view["status"] in REQUISITION_STATUS:
            requisition_service.set_status(db, negotiation_id, view["status"], self.agent_code)
        lim, shortage, history = s.limits, s.shortage, offer_history(view)
        if view["awaiting_supplier"]:
            task = Task(task_type="AWAIT_SUPPLIER_RESPONSE", status="WAITING")
        elif view["status"] == SessionStatus.NEGOTIATING.value:
            task = Task(task_type="EVALUATE_SUPPLIER_RESPONSE", status="IN_PROGRESS")
        else:
            task = Task(task_type="NEGOTIATION_CLOSED", status="DONE")
        state = self.load_state(db)
        entry = DialogueEntry(round=view["round_number"] or None, counterpart=counterpart, summary=summary[:SUMMARY_MAX], at=now())
        supplier_name = lim.supplier.supplier if lim.supplier else None
        self.save_state(db, AgentStateData(
            current_goal=Goal(
                goal_type="SECURE_MATERIAL",
                description=f"Procure {shortage.shortage_quantity} of item {shortage.item_id} by {shortage.required_by}"
                + (f" ({supplier_name})" if supplier_name else ""),
                refs=Refs(order_id=shortage.order_id, item_id=shortage.item_id, negotiation_id=view["id"]),
            ),
            current_task=task.model_copy(update={"refs": Refs(negotiation_id=view["id"]), "started_at": view["started_at"]}),
            preferred_terms=_terms(s, lim.min_quantity, lim.earliest_delivery or lim.latest_delivery),
            reserved_limits=plain({"latest_acceptable_delivery": lim.latest_delivery,
                                   "min_quantity": lim.min_quantity, "max_quantity": lim.max_quantity}),
            initial_proposal=history["PURCHASING"][0].terms if history["PURCHASING"] else None,
            own_offer_history=history["PURCHASING"],
            opponent_offer_history=history["SUPPLIER_INTERFACE"],
            dialogue_history=self.dialogue(state, "negotiation_id", view["id"], entry),
            negotiation_rules=NegotiationRules(policy=plain({
                "procurement_strategy": "meet required date first",
                "delivery_preferences": {"prefer_earliest": True, "earliest_feasible_delivery": lim.earliest_delivery},
                "supplier_evaluation_policy": "covers the shortage alone; earliest arrival, then available quantity",
                "selected_supplier": supplier_name,
                "acceptable_quantity_range": {"min": lim.min_quantity, "max": lim.max_quantity},
                "latest_acceptable_delivery": lim.latest_delivery,
            })),
        ))
        db.commit()
