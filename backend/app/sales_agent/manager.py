"""The conversation manager: runs all the steps for one customer message, and for Planning's answers.

    accept_message (fast):  save the message, say "received"
    process_conversation (slow, in the background):
        - a customer message: load what is known -> ask the language model -> check its answer -> save and reply.
          When all three details are collected, send the request to Planning and wait.
        - Planning's answer: explain the options (the model's words are checked, our own words are the fallback)

The model only suggests. This code decides what is accepted, saves it, and writes the reply when the model's answer
cannot be used. Sales never works out dates or quantities: it only passes on and explains what Planning says.
"""

import logging
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.llm.client import LLMClient, LLMError
from app.llm.reasoning import StructuredOutputError
from app.sales_agent import agent, data_access, rules, tools
from app.sales_agent import planning as planning_module
from app.sales_agent.models import Conversation, Inquiry, Message, Option, Product
from app.sales_agent.planning import PlanningConnector, PlanningResult
from app.sales_agent.prompts import build_system_prompt
from app.sales_agent.rules import CollectedDetails

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20  # the small model works better with a short history
RECENT_ORDERS_IN_SUMMARY = 3
OFFER_VALIDITY = timedelta(hours=24)

NEXT_STEP_SEND_REQUEST = "send_request"
NEXT_STEP_PASS_TO_STAFF = "pass_to_staff"
DECISION_STEPS = {"select_option", "confirm_order", "decline"}  # the steps that change what happens to the order
STAGES_WITH_AN_OFFER = ("OPTIONS_PRESENTED", "AWAITING_CONFIRMATION")

# Planning answers that the customer must be told about. A WORKING answer is only noted.
ANSWERS_TO_ANNOUNCE = {"READY", "NOTHING_FEASIBLE", "NEEDS_STAFF"}


@dataclass
class TurnOutcome:
    """What one turn decided: the reply, the details to keep, and how it came about (for the audit note)."""

    reply: str
    collected: CollectedDetails
    next_step: str
    ai_answer: dict | None = None  # the model's answer, if it gave a valid one
    problems: list[str] = field(default_factory=list)  # what was wrong with the answer that was not used
    asked_again: bool = False  # the model was asked a second time
    used_fallback: bool = False  # the reply was written by our code


# -- step 1, fast: accept the message and say "received" ------------------------------------------------------------

# Two copies of the same message can arrive at the same moment. This lock makes the second one wait, so it finds the
# first one and is recognised as a duplicate. (One backend process; see README.)
_accept_lock = threading.Lock()


@dataclass
class AcceptedMessage:
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    duplicate: bool  # the channel delivered this message before


def accept_message(db: Session, channel: str, sender_ref: str, provider_message_id: str, text: str) -> AcceptedMessage:
    """Save a customer message and report it as received. Nothing here waits for the language model.

    A message the channel delivers twice (same id) is not saved twice.
    """
    with _accept_lock:
        conversation = _find_or_start_conversation(db, channel, rules.normalize_phone(sender_ref))
        message = data_access.find_message_by_provider_id(db, conversation.id, provider_message_id)
        duplicate = message is not None
        if message is None:
            message = data_access.save_message(db, conversation.id, "IN", text, provider_message_id=provider_message_id)
        db.commit()
    return AcceptedMessage(conversation_id=conversation.id, message_id=message.id, duplicate=duplicate)


# -- step 1b, fast: store Planning's answer -------------------------------------------------------------------------


@dataclass
class PlanningReceipt:
    status: str  # "received", "duplicate" (we already have the final answer) or "ignored" (the request is no longer waiting)
    conversation_id: uuid.UUID


def handle_planning_result(db: Session, result: PlanningResult) -> PlanningReceipt:
    """Store Planning's answer to a request. The customer is told about it later, by `process_conversation`."""
    inquiry = data_access.find_inquiry_by_request_ref(db, result.request_ref)
    if inquiry is None:
        raise AppError(ErrorCode.NOT_FOUND, "unknown planning request")
    if inquiry.planning_result and inquiry.planning_result["status"] != "WORKING":
        return PlanningReceipt("duplicate", inquiry.conversation_id)  # the first final answer wins
    if inquiry.stage != "WAITING_FOR_PLANNING":
        return PlanningReceipt("ignored", inquiry.conversation_id)  # the customer changed or dropped the request meanwhile

    problems = planning_module.check_result_against_request(result, inquiry.planning_request["order"])
    if problems:
        raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, "the planning answer does not match the request",
                       [{"issue": problem} for problem in problems])

    inquiry.planning_result = {
        "status": result.status,
        "reason_code": result.reason_code,
        "options": [
            {"kind": o.kind, "quantity": tools.json_number(o.quantity), "delivery_date": o.delivery_date.isoformat(),
             "reason_code": o.reason_code}
            for o in result.options
        ],
        "announced": False,
    }
    if result.status == "READY":
        data_access.save_options(db, inquiry.id, [o.model_dump() for o in result.options])
    data_access.save_audit_note(
        db, "PLANNING", "PLANNING_RESULT_RECEIVED", {"status": result.status, "reason_code": result.reason_code},
        conversation_id=inquiry.conversation_id, inquiry_id=inquiry.id,
    )
    db.commit()
    return PlanningReceipt("received", inquiry.conversation_id)


# -- step 2, slow: answer the customer ------------------------------------------------------------------------------

SAFE_APOLOGY = "Sorry, I am having a technical problem right now. Please try again in a moment."
FAILURES_BEFORE_STAFF_IS_FLAGGED = 2


def process_conversation(
    db: Session, conversation_id: uuid.UUID, llm_client: LLMClient, today: date, planning: PlanningConnector
) -> None:
    """Answer everything in this conversation that is waiting for an answer: customer messages and Planning's answers.

    Only one worker answers a conversation at a time. Whatever arrives while the model is thinking is answered in the
    next turn. If the model cannot be used for a customer message, the customer gets an apology, the message stays
    unanswered, and we stop (the next customer message tries again).
    """
    while _needs_turn(db, conversation_id):
        if not data_access.try_claim_conversation(db, conversation_id):
            return  # another worker has it; it looks again when it is done
        try:
            answered = _run_turn(db, conversation_id, llm_client, today, planning)
        finally:
            data_access.release_conversation(db, conversation_id)
        if not answered:
            return


def _has_unannounced_answer(inquiry: Inquiry | None) -> bool:
    result = inquiry.planning_result if inquiry else None
    return bool(result) and result["status"] in ANSWERS_TO_ANNOUNCE and not result["announced"]


def _needs_turn(db: Session, conversation_id: uuid.UUID) -> bool:
    if data_access.list_unprocessed_incoming(db, conversation_id):
        return True
    return _has_unannounced_answer(data_access.find_active_inquiry(db, conversation_id))


def _run_turn(
    db: Session, conversation_id: uuid.UUID, llm_client: LLMClient, today: date, planning: PlanningConnector
) -> bool:
    """One turn. False if the model could not be used for a customer message."""
    db.expire_all()  # another worker may have stored a message or Planning's answer since this session last looked
    conversation = data_access.get_conversation(db, conversation_id)
    seen = data_access.list_unprocessed_incoming(db, conversation_id)  # exactly the messages this turn answers
    inquiry = data_access.find_active_inquiry(db, conversation_id)
    if _has_unannounced_answer(inquiry):
        return _run_answer_turn(db, conversation, inquiry, seen, llm_client, today)
    if not seen:
        return True
    if inquiry is None:
        inquiry = data_access.create_inquiry(db, conversation)
    db.commit()  # no database lock may be held while the slow model call runs
    return _run_customer_turn(db, conversation, inquiry, seen, llm_client, today, planning)


# -- a customer message ---------------------------------------------------------------------------------------------


def _run_customer_turn(
    db: Session, conversation: Conversation, inquiry: Inquiry, seen: list[Message], llm_client: LLMClient, today: date,
    planning: PlanningConnector,
) -> bool:
    stage = inquiry.stage
    if stage in STAGES_WITH_AN_OFFER and _offer_has_expired(inquiry):
        return _renew_expired_inquiry(db, conversation, inquiry, seen, today, planning)
    products = data_access.list_active_products(db)
    collected = _collected_details(db, inquiry)
    offered = _open_options(db, inquiry)
    messages, situation = _build_model_messages(db, conversation, inquiry, collected, products, today, offered)
    try:
        outcome = _think(llm_client, messages, situation, stage, products, collected, today, offered)
    except LLMError as error:
        _handle_model_failure(db, conversation, inquiry, error)
        return False

    # If the customer changes the request while we wait for Planning or after options were shown, the old request is
    # dropped and a new one is made.
    changed_request = stage != "GATHERING" and _details_changed(collected, outcome.collected)
    if changed_request:
        inquiry = _replace_inquiry(db, conversation, inquiry)
        if outcome.next_step in DECISION_STEPS:  # a change cancels any choice or "yes" in the same message
            outcome = replace(outcome, reply=planning_module.request_changed_reply(), next_step="ask_more")
    elif outcome.next_step in DECISION_STEPS and not outcome.used_fallback:
        reply, notice = _decide(db, conversation, inquiry, seen, outcome, offered)
        _save_turn(db, conversation, inquiry, seen, replace(outcome, reply=reply, next_step="ask_more"))
        if notice:
            _send_confirmation(db, conversation, inquiry, notice, planning)
        return True
    should_send = (
        outcome.collected.is_complete and not outcome.used_fallback
        and (changed_request or (stage == "GATHERING" and outcome.next_step == NEXT_STEP_SEND_REQUEST))
    )

    _save_turn(db, conversation, inquiry, seen, outcome)
    if should_send:
        _send_to_planning(db, conversation, inquiry, outcome.collected, today, planning)
    return True


def _offer_has_expired(inquiry: Inquiry) -> bool:
    return inquiry.offer_valid_until is not None and datetime.now(timezone.utc) > inquiry.offer_valid_until


def _renew_expired_inquiry(
    db: Session, conversation: Conversation, old: Inquiry, seen: list[Message], today: date, planning: PlanningConnector
) -> bool:
    """The customer wrote after the offer ran out (there are no timers, so we notice now). Whatever they said is not
    accepted. The old inquiry is closed, and the same request goes to Planning again for fresh options."""
    for option in data_access.list_options(db, old.id):
        if option.status in ("OFFERED", "SELECTED"):
            option.status = "EXPIRED"
    old.stage, old.closed_reason = "CLOSED", "EXPIRED"
    db.flush()
    new = data_access.create_inquiry(db, conversation)
    new.product_id, new.quantity, new.requested_date = old.product_id, old.quantity, old.requested_date
    data_access.save_audit_note(
        db, "SYSTEM", "OFFER_EXPIRED", {"old_inquiry_id": str(old.id), "new_inquiry_id": str(new.id)},
        conversation_id=conversation.id, inquiry_id=new.id,
    )
    collected = _collected_details(db, new)
    outcome = TurnOutcome(planning_module.offer_expired_reply(), collected, "ask_more", used_fallback=True)
    _save_turn(db, conversation, new, seen, outcome)
    _send_to_planning(db, conversation, new, collected, today, planning)
    return True


def _details_changed(before: CollectedDetails, after: CollectedDetails) -> bool:
    return (before.product_id, before.quantity, before.requested_date) != (after.product_id, after.quantity, after.requested_date)


def _replace_inquiry(db: Session, conversation: Conversation, old: Inquiry) -> Inquiry:
    """The customer changed the request: drop the old inquiry (and its options) and start a new one."""
    data_access.release_options(db, old.id)
    old.stage, old.closed_reason = "CLOSED", "REPLACED"
    db.flush()  # the old one must be finished before the new one is added (one active inquiry per conversation)
    new = data_access.create_inquiry(db, conversation)
    data_access.save_audit_note(
        db, "SYSTEM", "INQUIRY_REPLACED", {"old_inquiry_id": str(old.id), "new_inquiry_id": str(new.id)},
        conversation_id=conversation.id, inquiry_id=new.id,
    )
    return new


def _send_to_planning(
    db: Session, conversation: Conversation, inquiry: Inquiry, collected: CollectedDetails, today: date,
    planning: PlanningConnector,
) -> None:
    """Send the request (the order and a small customer summary) to Planning, and wait for its answer."""
    known = conversation.customer_id is not None
    customer_info = tools.get_customer_info(db, conversation.sender_ref) if known else {"found": False}
    recent_orders = (
        tools.get_order_history(db, conversation.customer_id, planning_module.MAX_RECENT_ORDERS_IN_CONTEXT)["orders"]
        if known else []
    )
    request = planning_module.build_request(
        planning_module.new_request_ref(), str(inquiry.id), conversation.sender_ref, customer_info, recent_orders,
        collected.product_id, collected.product_name, collected.quantity, collected.requested_date, today,
    )
    inquiry.planning_request_ref = request["request_ref"]
    inquiry.planning_request = request
    inquiry.stage = "WAITING_FOR_PLANNING"
    data_access.save_audit_note(
        db, "SYSTEM", "PLANNING_REQUEST_SENT", {"request_ref": request["request_ref"], "order": request["order"]},
        conversation_id=conversation.id, inquiry_id=inquiry.id,
    )
    db.commit()  # Planning may answer at once, so the request must be saved before it is sent
    planning.send_request(request)


# -- choosing, confirming, declining --------------------------------------------------------------------------------


def _decide(
    db: Session, conversation: Conversation, inquiry: Inquiry, seen: list[Message], outcome: TurnOutcome,
    options: list[Option],
) -> tuple[str, dict | None]:
    """Act on a choice, a "yes" or a "no" that the model reported. Returns the reply (always our own words, so the model
    can never say an order exists) and, if an order was made, the notice to send to Planning after the commit."""
    note = {"conversation_id": conversation.id, "inquiry_id": inquiry.id}
    step = outcome.next_step
    product_name = outcome.collected.product_name

    if step == "decline":
        for option in options:
            option.status = "RELEASED"
        inquiry.stage, inquiry.closed_reason = "CLOSED", "DECLINED"
        data_access.save_audit_note(db, "SALES_AI", "CUSTOMER_DECLINED", {}, **note)
        return planning_module.declined_reply(), None

    if step == "select_option":
        letters = planning_module.OPTION_LETTERS[:len(options)]
        chosen = options[letters.index(outcome.ai_answer["chosen_option"].strip().upper())]
        for option in options:
            option.status = "SELECTED" if option is chosen else "OFFERED"
        inquiry.selected_option_id, inquiry.stage = chosen.id, "AWAITING_CONFIRMATION"
        data_access.save_audit_note(db, "SALES_AI", "OPTION_SELECTED", {"option_id": str(chosen.id)}, **note)
        return planning_module.confirmation_question(chosen.quantity, chosen.delivery_date, product_name), None

    # confirm_order: the model heard a "yes". Our own rules decide whether that is enough to make an order.
    chosen = next((option for option in options if option.id == inquiry.selected_option_id), None)
    question = planning_module.confirmation_question(chosen.quantity, chosen.delivery_date, product_name) if chosen else ""
    last_reply = data_access.find_last_outgoing_before(db, conversation.id, seen[-1])
    problem = rules.confirmation_problem(
        inquiry.stage, chosen is not None, inquiry.offer_valid_until, datetime.now(timezone.utc), len(seen),
        last_reply.text if last_reply else None, question,
    )
    if problem:
        data_access.save_audit_note(db, "SYSTEM", "CONFIRMATION_REFUSED", {"reason": problem}, **note)
        return question or planning_module.request_changed_reply(), None  # ask again; nothing changes
    return _make_order(db, conversation, inquiry, chosen, seen[-1], product_name)


def _make_order(
    db: Session, conversation: Conversation, inquiry: Inquiry, option: Option, yes_message: Message, product_name: str
) -> tuple[str, dict]:
    """The customer clearly said yes to one option: the order exists from this moment."""
    now = datetime.now(timezone.utc)
    if conversation.customer_id is None:  # a first-time customer becomes a customer now
        customer = data_access.find_customer_by_phone(db, conversation.sender_ref) or data_access.create_customer(
            db, conversation.sender_ref)
        conversation.customer_id = inquiry.customer_id = customer.id
    order = data_access.create_order(db, f"SA-{uuid.uuid4().hex[:8].upper()}", inquiry, option, conversation.customer_id, now)
    inquiry.stage, inquiry.confirmed_at, inquiry.confirmation_message_id = "CONFIRMED", now, yes_message.id
    _refresh_insights(db, conversation.customer_id, conversation.id, inquiry.id)
    for other in data_access.list_options(db, inquiry.id):
        if other.id != option.id and other.status in ("OFFERED", "SELECTED"):
            other.status = "RELEASED"
    data_access.save_audit_note(db, "SYSTEM", "CONFIRMATION_ACCEPTED", {
        "order_number": order.order_number, "option_id": str(option.id), "confirming_message_id": str(yes_message.id),
    }, conversation_id=conversation.id, inquiry_id=inquiry.id)
    notice = {
        "inquiry_id": str(inquiry.id), "option_id": str(option.id), "customer_id": str(conversation.customer_id),
        "order_number": order.order_number, "product_id": str(inquiry.product_id),
        "quantity": tools.json_number(option.quantity), "delivery_date": option.delivery_date.isoformat(),
        "confirming_message_id": str(yes_message.id), "confirmed_at": now.isoformat(), "payment": "ASSUMED_PAID",
    }
    reply = planning_module.order_confirmed_reply(order.order_number, option.quantity, option.delivery_date, product_name)
    return reply, notice


def _send_confirmation(
    db: Session, conversation: Conversation, inquiry: Inquiry, notice: dict, planning: PlanningConnector
) -> None:
    """Tell Planning about the confirmed order. The order is already saved, so a failure here is only noted."""
    try:
        planning.send_confirmation(notice)
    except Exception as error:
        logger.exception("could not send the confirmation notice for %s", notice["order_number"])
        data_access.save_audit_note(
            db, "SYSTEM", "CONFIRMATION_NOTICE_FAILED", {"order_number": notice["order_number"], "error": str(error)},
            conversation_id=conversation.id, inquiry_id=inquiry.id,
        )
        db.commit()


# -- Planning's answer ----------------------------------------------------------------------------------------------


def _run_answer_turn(
    db: Session, conversation: Conversation, inquiry: Inquiry, seen: list[Message], llm_client: LLMClient, today: date
) -> bool:
    """Tell the customer what Planning answered. Always succeeds: our own words are used if the model's cannot be."""
    status = inquiry.planning_result["status"]
    collected = _collected_details(db, inquiry)
    note = {"conversation_id": conversation.id, "inquiry_id": inquiry.id}
    answered = []  # the customer messages this reply also covers

    if status == "NOTHING_FEASIBLE":
        reply = planning_module.nothing_feasible_reply(collected.product_name)
        inquiry.stage, inquiry.closed_reason = "CLOSED", "NO_OPTION"
    elif status == "NEEDS_STAFF":
        reply = planning_module.needs_staff_reply()
        inquiry.stage = "NEEDS_STAFF"
        data_access.save_audit_note(db, "SYSTEM", "STAFF_FLAGGED", {"reason": "Planning asked for a team member"}, **note)
    else:
        reply, answered = _explain_options(db, conversation, inquiry, collected, seen, llm_client, today)

    inquiry.planning_result = {**inquiry.planning_result, "announced": True}
    data_access.save_message(db, conversation.id, "OUT", reply, delivery_status="SENT")
    data_access.mark_messages_processed(db, [message.id for message in answered])
    conversation.last_message_at = datetime.now(timezone.utc)
    data_access.save_audit_note(db, "SYSTEM", "PLANNING_ANSWER_ANNOUNCED", {"status": status}, **note)
    db.commit()
    return True


def _explain_options(
    db: Session, conversation: Conversation, inquiry: Inquiry, collected: CollectedDetails, seen: list[Message],
    llm_client: LLMClient, today: date,
) -> tuple[str, list[Message]]:
    """The reply that presents the options. The model words it; every date and number it uses must be one of Planning's.
    If its wording cannot be used, or the model is down, our own text is used. Returns the reply and the customer
    messages the model saw (so they count as answered)."""
    options = _open_options(db, inquiry)
    products = data_access.list_active_products(db)
    messages, situation = _build_model_messages(db, conversation, inquiry, collected, products, today, options, announcing=True)
    try:
        outcome = _think(llm_client, messages, situation, "OPTIONS_PRESENTED", products, collected, today, options,
                         use_details=False, must_present=True)
        used_model, failed = not outcome.used_fallback, False
    except LLMError as error:
        data_access.save_audit_note(db, "SYSTEM", "AI_FAILED", {"error": str(error)},
                                    conversation_id=conversation.id, inquiry_id=inquiry.id)
        outcome, used_model, failed = None, False, True

    reply = outcome.reply if used_model else planning_module.options_reply(
        [(o.kind, o.quantity, o.delivery_date) for o in options], collected.product_name)
    valid_until = datetime.now(timezone.utc) + OFFER_VALIDITY
    inquiry.stage, inquiry.offer_valid_until = "OPTIONS_PRESENTED", valid_until
    for option in options:
        option.valid_until = valid_until
    data_access.save_audit_note(db, "SALES_AI", "OPTIONS_PRESENTED", {
        "options": [{"kind": o.kind, "quantity": tools.json_number(o.quantity), "delivery_date": o.delivery_date.isoformat()}
                    for o in options],
        "used_own_text": not used_model, "model_failed": failed, "problems": outcome.problems if outcome else [],
    }, conversation_id=conversation.id, inquiry_id=inquiry.id)
    return reply, (seen if used_model else [])


def _handle_model_failure(db: Session, conversation: Conversation, inquiry: Inquiry, error: LLMError) -> None:
    """Tell the customer, note it, and flag staff when it keeps happening. The customer's messages stay unanswered."""
    note = {"conversation_id": conversation.id, "inquiry_id": inquiry.id}
    data_access.save_audit_note(db, "SYSTEM", "AI_FAILED", {"error": str(error)}, **note)
    data_access.save_message(db, conversation.id, "OUT", SAFE_APOLOGY, delivery_status="SENT")
    if data_access.count_consecutive_ai_failures(db, conversation.id) == FAILURES_BEFORE_STAFF_IS_FLAGGED:
        data_access.save_audit_note(
            db, "SYSTEM", "STAFF_FLAGGED", {"reason": "the language model failed repeatedly"}, **note
        )
    db.commit()


# -- finding the conversation and what is already collected ---------------------------------------------------------


def _find_or_start_conversation(db: Session, channel: str, sender_ref: str) -> Conversation:
    conversation = data_access.find_open_conversation(db, channel, sender_ref)
    if conversation is None:
        conversation = data_access.create_conversation(db, channel, sender_ref, customer_id=None)
    if conversation.customer_id is None:  # an unknown number may belong to a customer by now
        customer = data_access.find_customer_by_phone(db, sender_ref)
        conversation.customer_id = customer.id if customer else None
    return conversation


def _collected_details(db: Session, inquiry: Inquiry) -> CollectedDetails:
    product = data_access.get_product(db, inquiry.product_id) if inquiry.product_id else None
    return CollectedDetails(
        product_id=str(product.id) if product else None,
        product_name=product.name if product else None,
        quantity=inquiry.quantity,
        requested_date=inquiry.requested_date,
    )


def _open_options(db: Session, inquiry: Inquiry) -> list[Option]:
    """The options Planning gave for this inquiry that are still open (offered, or chosen and waiting for the customer's
    confirmation), in the order Planning gave them."""
    return [option for option in data_access.list_options(db, inquiry.id) if option.status in ("OFFERED", "SELECTED")]


# -- building what the model reads ----------------------------------------------------------------------------------


def _describe_collected(collected: CollectedDetails) -> str:
    quantity = "not yet known" if collected.quantity is None else tools.json_number(collected.quantity)
    requested_date = "not yet known" if collected.requested_date is None else collected.requested_date.isoformat()
    return (
        f"product = {collected.product_name or 'not yet known'}; quantity = {quantity}; "
        f"requested delivery date = {requested_date}"
    )


def _describe_customer(db: Session, conversation: Conversation) -> str:
    """What we know about this customer, in a few lines. Only saved facts, never guesses."""
    info = tools.get_customer_info(db, conversation.sender_ref) if conversation.customer_id else {"found": False}
    if not info["found"]:
        return "New customer: nothing is known about them."

    lines = [f"Name: {info['customer']['name']}"] if info["customer"]["name"] else []
    orders = tools.get_order_history(db, conversation.customer_id, RECENT_ORDERS_IN_SUMMARY)["orders"]
    if orders:
        lines.append("Past orders, newest first:")
        lines += [
            f"- {o['quantity']} x {o['product']}, asked for {o['requested_date'] or 'an unknown date'}, delivery {o['delivery_date']}"
            for o in orders
        ]
    said = [m for m in info["memory"] if m["source"] == "STATED"]
    inferred = [m for m in info["memory"] if m["source"] == "INFERRED"]
    if said:
        lines.append("Saved preferences (the customer said these):")
        lines += [f"- {m['type'].replace('_', ' ').lower()} ({m['scope'].replace('_', ' ').lower()})" for m in said]
    if inferred:
        lines.append("Insights (found by our rules, not certain):")
        lines += [f"- {m['type'].replace('_', ' ').lower()}" for m in inferred]
    return "\n".join(lines) if lines else "Known customer, but no past orders or saved notes."


def _describe_options(options: list[Option], product_name: str | None) -> str:
    return "\n".join(
        f"{planning_module.OPTION_LETTERS[i]}) {planning_module.describe_option(o.kind, o.quantity, o.delivery_date, product_name)}"
        for i, o in enumerate(options)
    )


def _describe_planning(inquiry: Inquiry, options: list[Option], product_name: str | None, announcing: bool) -> str:
    """What the model is told about the request that is with Planning, or the options already shown."""
    if announcing:
        return (
            "The planning team has answered. These are the only options you may offer, in this order:\n"
            f"{_describe_options(options, product_name)}\n"
            "Explain them in your own friendly words, using exactly these quantities and dates, and ask which option "
            "the customer prefers. Label them A, B, C as above. Do not add any other date or quantity, do not calculate "
            "anything, and never say the order is confirmed."
        )
    if inquiry.stage == "WAITING_FOR_PLANNING":
        return (
            "This request is with the planning team and we are waiting for their answer. If the customer asks, say you "
            "are still checking. Do not promise any date or quantity."
        )
    if inquiry.stage == "OPTIONS_PRESENTED" and options:
        return (
            f"You already showed these options (the only ones you may mention):\n{_describe_options(options, product_name)}\n"
            "Answer the customer's questions about them. If the customer chooses one (or says yes when there is only "
            "one option), use the next step select_option and set chosen_option to its letter; our system then asks "
            "the customer to confirm. If the customer does not want any option, use decline. Never say the order is "
            "confirmed."
        )
    if inquiry.stage == "AWAITING_CONFIRMATION" and options:
        chosen = next((o for o in options if o.status == "SELECTED"), options[0])
        return (
            f"The customer chose this option:\n{_describe_options([chosen], product_name)}\n"
            "We asked them to confirm it with a question that repeats the product, quantity and date. If the "
            "customer clearly says yes, use the next step confirm_order. If they say no or do not want it, use "
            "decline. If they want a different option, use select_option with its letter. All the options:\n"
            f"{_describe_options(options, product_name)}\n"
            "If they ask a question or are not clear (for example maybe, or yes but later), answer briefly, use "
            "ask_more and ask them to say yes or no. Never say the order is confirmed: our system does that."
        )
    if inquiry.stage == "NEEDS_STAFF":
        return (
            "A team member will contact this customer about this request. Answer politely and briefly. Do not "
            "promise any date or quantity."
        )
    return ""


def _describe_situation(
    db: Session, conversation: Conversation, inquiry: Inquiry, collected: CollectedDetails, products: list[Product],
    today: date, options: list[Option], announcing: bool,
) -> str:
    missing = ", ".join(rules.FIELD_LABELS[name] for name in collected.missing_fields()) or "nothing"
    product_names = "; ".join(p.name for p in products) or "none"
    situation = (
        f"Today's date: {today.isoformat()}.\n"
        f"Products we sell: {product_names}.\n"
        f"Already collected for this order: {_describe_collected(collected)}.\n"
        f"Still missing: {missing}.\n"
        f"About this customer:\n{_describe_customer(db, conversation)}"
    )
    planning_part = _describe_planning(inquiry, options, collected.product_name, announcing)
    return f"{situation}\n{planning_part}" if planning_part else situation


def _build_model_messages(
    db: Session, conversation: Conversation, inquiry: Inquiry, collected: CollectedDetails, products: list[Product],
    today: date, options: list[Option], announcing: bool = False,
) -> tuple[list[dict[str, str]], str]:
    """The instructions (with the situation), then the recent conversation. Also returns the situation text."""
    situation = _describe_situation(db, conversation, inquiry, collected, products, today, options, announcing)
    history = data_access.list_recent_messages(db, conversation.id, MAX_HISTORY_MESSAGES)
    messages = [
        {"role": "system", "content": build_system_prompt(situation)},
        *({"role": "user" if m.direction == "IN" else "assistant", "content": m.text} for m in history),
    ]
    return messages, situation


# -- asking the model and checking its answer -----------------------------------------------------------------------


def _correction_messages(previous_answer, problems: list[str]) -> list[dict[str, str]]:
    """What the model is told when its answer had problems and it is asked once more."""
    listed = "\n".join(f"- {problem}" for problem in problems)
    return [
        {"role": "assistant", "content": previous_answer.model_dump_json()},
        {"role": "system", "content": f"Your answer had these problems:\n{listed}\nAnswer again in the same JSON form."},
    ]


def _think(
    llm_client: LLMClient, messages: list[dict[str, str]], situation: str, stage: str, products: list[Product],
    collected: CollectedDetails, today: date, options: list[Option], use_details: bool = True,
    must_present: bool = False,
) -> TurnOutcome:
    """Ask the model; if its answer has problems ask once more; if it cannot be used, write a safe reply ourselves.

    Raises LLMError if the model cannot be reached at all. A wrong detail (a date in the past, a quantity of 0, an
    unknown product) goes straight to our own reply. Asking the model again would not help, and it could hide the
    problem by simply leaving the detail out of its answer. With `use_details=False` (explaining options) the details
    in the model's answer are ignored, and with `must_present=True` the reply has to present every option.

    Every date and number in the reply must be one the customer wrote, one in the situation, or one of Planning's.
    """
    allowed = rules.allowed_values(
        [m["content"] for m in messages if m["role"] == "user"] + [situation], collected,
        [(option.quantity, option.delivery_date) for option in options],
    )
    merged, problems, turn, asked_again = None, [], None, False
    for attempt in (1, 2):
        try:
            turn = agent.ai_understand_and_reply(llm_client, messages)
        except StructuredOutputError:
            problems = ["The model did not answer in the required JSON form."]
            break  # it was already asked twice for a valid form: go straight to the safe reply

        merged = (
            rules.merge_details(products, collected, turn.details, today) if use_details
            else rules.MergeResult(collected=collected, problems=[])
        )
        problems = rules.check_ai_output(
            turn, stage, merged, allowed,
            must_present=[(o.quantity, o.delivery_date) for o in options] if must_present else (),
            option_letters=planning_module.OPTION_LETTERS[:len(options)],
        )
        if merged.problems:
            break  # a wrong detail came from the customer: the model cannot fix it, so our own reply tells them
        if not problems:
            return TurnOutcome(
                reply=turn.reply, collected=merged.collected, next_step=turn.next_step,
                ai_answer=turn.model_dump(mode="json"), asked_again=asked_again,
            )
        if attempt == 1:
            messages = messages + _correction_messages(turn, problems)
            asked_again = True

    wrong_fields = [problem.field for problem in merged.problems] if merged else []
    kept = merged.collected if merged else collected  # valid details are kept even if the reply could not be used
    reply = rules.fallback_reply(wrong_fields, kept.missing_fields(), [p.name for p in products])
    return TurnOutcome(
        reply=reply, collected=kept, next_step="ask_more", ai_answer=turn.model_dump(mode="json") if turn else None,
        problems=problems, asked_again=asked_again, used_fallback=True,
    )


# -- saving the result ----------------------------------------------------------------------------------------------


def _jsonable_details(collected: CollectedDetails) -> dict:
    return {
        "product": collected.product_name,
        "quantity": tools.json_number(collected.quantity) if collected.quantity is not None else None,
        "requested_date": collected.requested_date.isoformat() if collected.requested_date else None,
    }


def _save_turn(
    db: Session, conversation: Conversation, inquiry: Inquiry, answered: list[Message], outcome: TurnOutcome
) -> None:
    """Keep the collected details, the reply and the audit notes, in one commit. `answered` are the customer's messages
    this turn replied to; a message that arrived meanwhile is not among them and is answered in the next turn."""
    collected = outcome.collected
    inquiry.product_id = uuid.UUID(collected.product_id) if collected.product_id else None
    inquiry.quantity = collected.quantity
    inquiry.requested_date = collected.requested_date

    data_access.save_message(db, conversation.id, "OUT", outcome.reply, delivery_status="SENT")
    data_access.mark_messages_processed(db, [message.id for message in answered])
    conversation.last_message_at = datetime.now(timezone.utc)

    note = {"conversation_id": conversation.id, "inquiry_id": inquiry.id}
    data_access.save_audit_note(db, "SALES_AI", "AI_TURN", {
        "ai_answer": outcome.ai_answer, "problems": outcome.problems, "asked_again": outcome.asked_again,
        "used_fallback": outcome.used_fallback, "collected": _jsonable_details(collected),
    }, **note)
    if outcome.next_step == NEXT_STEP_PASS_TO_STAFF:
        data_access.save_audit_note(db, "SALES_AI", "PASSED_TO_STAFF", {"message": answered[-1].text}, **note)
    _remember_preference(db, conversation, inquiry, answered, outcome)
    db.commit()


# -- memory: preferences the customer asked for, insights found by our rules ----------------------------------------


def _remember_preference(
    db: Session, conversation: Conversation, inquiry: Inquiry, answered: list[Message], outcome: TurnOutcome
) -> None:
    """Save a preference the model reported, if it is on the allowed list and we know the customer. The model only
    suggests: a type that is not allowed is refused, and nothing else about the customer is ever saved by the model."""
    suggestion = (outcome.ai_answer or {}).get("preference")
    if not suggestion or outcome.used_fallback or not answered:
        return
    note = {"conversation_id": conversation.id, "inquiry_id": inquiry.id}
    read = rules.read_preference(agent.PreferenceSuggestion.model_validate(suggestion))
    if read is None:
        data_access.save_audit_note(db, "SYSTEM", "PREFERENCE_REFUSED", {"suggested": suggestion}, **note)
        return
    kind, scope = read
    if conversation.customer_id is None:  # there is no customer record to attach it to until the first order
        data_access.save_audit_note(db, "SYSTEM", "PREFERENCE_NOT_SAVED", {"type": kind, "reason": "new customer"}, **note)
        return
    same = [m for m in data_access.find_active_memory(db, conversation.customer_id, "PREFERENCE", kind)
            if m.scope == scope and (scope == "GENERAL" or m.inquiry_id == inquiry.id)]
    if same:
        return  # already saved
    data_access.save_memory(
        db, conversation.customer_id, "PREFERENCE", kind, {}, [{"message_id": str(answered[-1].id)}], scope=scope,
        inquiry_id=inquiry.id if scope == "THIS_ORDER" else None,
    )
    data_access.save_audit_note(db, "SALES_AI", "PREFERENCE_SAVED", {"type": kind, "scope": scope}, **note)


def _refresh_insights(db: Session, customer_id: uuid.UUID, conversation_id: uuid.UUID, inquiry_id: uuid.UUID) -> None:
    """After a confirmed order, apply the fixed insight rule again. An insight that no longer holds, or whose strength
    changed, is retired or superseded, so nothing stays on a customer's record without current evidence."""
    orders = data_access.list_recent_order_rows(db, customer_id, rules.FREQUENT_PRODUCT_WINDOW)
    found = rules.frequent_product([str(order.product_id) for order in orders])
    current = data_access.find_active_memory(db, customer_id, "INSIGHT", "FREQUENT_PRODUCT")
    up_to_date = False
    for old in current:
        if found and old.value.get("product_id") == found[0] and old.strength == found[2]:
            up_to_date = True
        else:
            old.status = "SUPERSEDED" if found else "RETIRED"
    if found and not up_to_date:
        product_id, count, strength = found
        data_access.save_memory(
            db, customer_id, "INSIGHT", "FREQUENT_PRODUCT",
            {"product_id": product_id, "product": data_access.get_product(db, uuid.UUID(product_id)).name, "orders": count},
            [{"order_id": str(order.id)} for order in orders if str(order.product_id) == product_id], strength=strength,
        )
    data_access.save_audit_note(
        db, "SYSTEM", "INSIGHTS_REFRESHED", {"frequent_product": found[0] if found else None},
        conversation_id=conversation_id, inquiry_id=inquiry_id,
    )


# -- clearing test chats --------------------------------------------------------------------------------------------


def clear_chat(db: Session, channel: str, sender_ref: str) -> None:
    """Close this sender's open conversation (and give up its unfinished inquiry). The next message starts a new one."""
    conversation = data_access.find_open_conversation(db, channel, rules.normalize_phone(sender_ref))
    if conversation is not None:
        data_access.close_conversation(db, conversation)
        db.commit()


def reset_test_channel(db: Session) -> int:
    """Close every open conversation of the test channel. Nothing is deleted. Returns how many were closed."""
    conversations = data_access.list_open_conversations(db, "TEST")
    for conversation in conversations:
        data_access.close_conversation(db, conversation)
    db.commit()
    return len(conversations)


def release_stuck_conversations(db: Session) -> None:
    """At startup: a conversation still marked busy was being answered when the previous run stopped."""
    data_access.release_all_conversations(db)
