"""What the read-only doors show: plain data built from the data access layer and the tools. Nothing is changed here."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.sales_agent import data_access, rules, tools
from app.sales_agent.models import Conversation, Inquiry, Message


def _day(value) -> str | None:
    return value.isoformat() if value else None


def _message(message: Message) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "direction": message.direction,
        "role": "user" if message.direction == "IN" else "assistant",  # how a chat window shows it
        "text": message.text,
        "created_at": message.created_at.isoformat(),
    }


def _conversation_or_404(db: Session, conversation_id: uuid.UUID) -> Conversation:
    conversation = data_access.get_conversation(db, conversation_id)
    if conversation is None:
        raise AppError(ErrorCode.NOT_FOUND, "conversation not found")
    return conversation


def _collected(db: Session, inquiry: Inquiry) -> dict[str, Any]:
    product = data_access.get_product(db, inquiry.product_id) if inquiry.product_id else None
    return {
        "product": product.name if product else None,
        "quantity": tools.json_number(inquiry.quantity) if inquiry.quantity is not None else None,
        "requested_date": _day(inquiry.requested_date),
    }


# -- door 2 and the test chat page: messages ------------------------------------------------------------------------


def new_messages(db: Session, conversation_id: uuid.UUID, after_message_id: uuid.UUID | None) -> dict[str, Any]:
    """The messages of the conversation, only those after `after_message_id` if it is given."""
    conversation = _conversation_or_404(db, conversation_id)
    after = None
    if after_message_id is not None:
        after = data_access.get_message(db, after_message_id)
        if after is None or after.conversation_id != conversation.id:
            raise AppError(ErrorCode.NOT_FOUND, "message not found in this conversation")
    messages = data_access.list_messages_after(db, conversation.id, after)
    return {"conversation_id": str(conversation.id), "busy": conversation.busy, "messages": [_message(m) for m in messages]}


def chat_of_sender(db: Session, channel: str, sender_ref: str) -> dict[str, Any]:
    """The open conversation of this sender, for the test chat page. Empty if there is none."""
    conversation = data_access.find_open_conversation(db, channel, rules.normalize_phone(sender_ref))
    if conversation is None:
        return {"conversation_id": None, "busy": False, "messages": []}
    return new_messages(db, conversation.id, None)


# -- door 4, 5, 6: what the team can look at ------------------------------------------------------------------------


def conversation_view(db: Session, conversation_id: uuid.UUID) -> dict[str, Any]:
    conversation = _conversation_or_404(db, conversation_id)
    inquiry = data_access.get_inquiry(db, conversation.current_inquiry_id) if conversation.current_inquiry_id else None
    return {
        "id": str(conversation.id),
        "channel": conversation.channel,
        "sender": conversation.sender_ref,
        "status": conversation.status,
        "busy": conversation.busy,
        "customer_id": str(conversation.customer_id) if conversation.customer_id else None,
        "last_message_at": _day(conversation.last_message_at),
        "inquiry": {"id": str(inquiry.id), "stage": inquiry.stage, "collected": _collected(db, inquiry)} if inquiry else None,
        "messages": [_message(m) for m in data_access.list_messages_after(db, conversation.id, None)],
    }


def inquiry_view(db: Session, inquiry_id: uuid.UUID) -> dict[str, Any]:
    inquiry = data_access.get_inquiry(db, inquiry_id)
    if inquiry is None:
        raise AppError(ErrorCode.NOT_FOUND, "inquiry not found")
    options = data_access.list_options(db, inquiry.id)
    return {
        "id": str(inquiry.id),
        "conversation_id": str(inquiry.conversation_id),
        "customer_id": str(inquiry.customer_id) if inquiry.customer_id else None,
        "stage": inquiry.stage,
        "closed_reason": inquiry.closed_reason,
        "collected": _collected(db, inquiry),
        "offer_valid_until": _day(inquiry.offer_valid_until),
        "selected_option_id": str(inquiry.selected_option_id) if inquiry.selected_option_id else None,
        "confirmed_at": _day(inquiry.confirmed_at),
        "planning_request": inquiry.planning_request,
        "planning_result": inquiry.planning_result,
        "options": [
            {"id": str(o.id), "kind": o.kind, "quantity": tools.json_number(o.quantity),
             "delivery_date": _day(o.delivery_date), "valid_until": _day(o.valid_until), "status": o.status}
            for o in options
        ],
    }


def customer_view(db: Session, customer_id: uuid.UUID) -> dict[str, Any]:
    customer = data_access.get_customer(db, customer_id)
    if customer is None:
        raise AppError(ErrorCode.NOT_FOUND, "customer not found")
    return _customer_details(db, customer.phone)


def customer_view_by_phone(db: Session, phone: str) -> dict[str, Any]:
    info = _customer_details(db, phone)
    if not info["found"]:
        raise AppError(ErrorCode.NOT_FOUND, "customer not found")
    return info


def _customer_details(db: Session, phone: str) -> dict[str, Any]:
    info = tools.get_customer_info(db, phone)
    if info["found"]:
        info["orders"] = tools.get_order_history(db, uuid.UUID(info["customer"]["id"]))["orders"]
    return info
