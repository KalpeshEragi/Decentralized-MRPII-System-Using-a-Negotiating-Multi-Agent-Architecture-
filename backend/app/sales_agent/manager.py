"""The conversation manager: runs all the steps for one customer message, in two parts.

    accept_message (fast):  save the message, say "received"
    process_conversation (slow, in the background):
        load what is known -> ask the language model -> check its answer -> save and reply

The model only suggests. This code decides what is accepted, saves it, and writes the reply when the model's answer
cannot be used. Planning is not connected yet: when all three details are collected, the manager only records that the
inquiry is ready to be sent (a READY_FOR_PLANNING audit note).
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.llm.client import LLMClient, LLMError
from app.llm.reasoning import StructuredOutputError
from app.sales_agent import agent, data_access, rules, tools
from app.sales_agent.models import Conversation, Inquiry, Message, Product
from app.sales_agent.prompts import build_system_prompt
from app.sales_agent.rules import CollectedDetails

MAX_HISTORY_MESSAGES = 20  # the small model works better with a short history
RECENT_ORDERS_IN_SUMMARY = 3

NEXT_STEP_SEND_REQUEST = "send_request"
NEXT_STEP_PASS_TO_STAFF = "pass_to_staff"


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


# -- step 2, slow: answer the customer ------------------------------------------------------------------------------

SAFE_APOLOGY = "Sorry, I am having a technical problem right now. Please try again in a moment."
FAILURES_BEFORE_STAFF_IS_FLAGGED = 2


def process_conversation(db: Session, conversation_id: uuid.UUID, llm_client: LLMClient, today: date) -> None:
    """Answer every customer message of this conversation that has not been answered yet.

    Only one worker answers a conversation at a time. Messages that arrive while the model is thinking are answered
    together in the next turn. If the model cannot be used, the customer gets an apology, the messages stay unanswered,
    and we stop (the next customer message tries again).
    """
    while data_access.list_unprocessed_incoming(db, conversation_id):
        if not data_access.try_claim_conversation(db, conversation_id):
            return  # another worker has it; it looks for new messages again when it is done
        try:
            answered = _run_turn(db, conversation_id, llm_client, today)
        finally:
            data_access.release_conversation(db, conversation_id)
        if not answered:
            return


def _run_turn(db: Session, conversation_id: uuid.UUID, llm_client: LLMClient, today: date) -> bool:
    """One turn: the model reads the conversation and we reply. False if the model could not be used."""
    conversation = data_access.get_conversation(db, conversation_id)
    seen = data_access.list_unprocessed_incoming(db, conversation_id)  # exactly the messages this turn answers
    if not seen:
        return True
    inquiry = data_access.find_active_inquiry(db, conversation_id) or data_access.create_inquiry(db, conversation)
    db.commit()  # no database lock may be held while the slow model call runs

    products = data_access.list_active_products(db)
    collected = _collected_details(db, inquiry)
    messages = _build_model_messages(db, conversation, collected, products, today)
    try:
        outcome = _think(llm_client, messages, inquiry.stage, products, collected, today)
    except LLMError as error:
        _handle_model_failure(db, conversation, inquiry, error)
        return False
    _save_turn(db, conversation, inquiry, seen, outcome)
    return True


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


def _describe_situation(db, conversation, collected: CollectedDetails, products: list[Product], today: date) -> str:
    missing = ", ".join(rules.FIELD_LABELS[name] for name in collected.missing_fields()) or "nothing"
    product_names = "; ".join(p.name for p in products) or "none"
    return (
        f"Today's date: {today.isoformat()}.\n"
        f"Products we sell: {product_names}.\n"
        f"Already collected for this order: {_describe_collected(collected)}.\n"
        f"Still missing: {missing}.\n"
        f"About this customer:\n{_describe_customer(db, conversation)}"
    )


def _build_model_messages(db, conversation, collected, products, today) -> list[dict[str, str]]:
    """The instructions (with the situation), then the recent conversation."""
    situation = _describe_situation(db, conversation, collected, products, today)
    history = data_access.list_recent_messages(db, conversation.id, MAX_HISTORY_MESSAGES)
    return [
        {"role": "system", "content": build_system_prompt(situation)},
        *({"role": "user" if m.direction == "IN" else "assistant", "content": m.text} for m in history),
    ]


# -- asking the model and checking its answer -----------------------------------------------------------------------


def _correction_messages(previous_answer, problems: list[str]) -> list[dict[str, str]]:
    """What the model is told when its answer had problems and it is asked once more."""
    listed = "\n".join(f"- {problem}" for problem in problems)
    return [
        {"role": "assistant", "content": previous_answer.model_dump_json()},
        {"role": "system", "content": f"Your answer had these problems:\n{listed}\nAnswer again in the same JSON form."},
    ]


def _think(
    llm_client: LLMClient, messages: list[dict[str, str]], stage: str, products: list[Product],
    collected: CollectedDetails, today: date,
) -> TurnOutcome:
    """Ask the model; if its answer has problems ask once more; if it cannot be used, write a safe reply ourselves.

    Raises LLMError if the model cannot be reached at all. A wrong detail (a date in the past, a quantity of 0, an unknown product) goes straight to our own reply. Asking the
    model again would not help, and it could hide the problem by simply leaving the detail out of its answer.
    """
    merged, problems, turn, asked_again = None, [], None, False
    for attempt in (1, 2):
        try:
            turn = agent.ai_understand_and_reply(llm_client, messages)
        except StructuredOutputError:
            problems = ["The model did not answer in the required JSON form."]
            break  # it was already asked twice for a valid form: go straight to the safe reply

        merged = rules.merge_details(products, collected, turn.details, today)
        problems = rules.check_ai_output(turn, stage, merged)
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
    if outcome.next_step == NEXT_STEP_SEND_REQUEST and collected.is_complete:
        data_access.save_audit_note(db, "SYSTEM", "READY_FOR_PLANNING", _jsonable_details(collected), **note)
    db.commit()


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
