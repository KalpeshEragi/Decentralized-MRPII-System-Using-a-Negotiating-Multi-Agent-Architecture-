"""The structured customer path (DM-7): a simulated customer's request, choice and "yes" reach Sales as data instead of
chat text. Only the language-reading step is skipped; everything after it is Sales' normal code (`manager`):
the inquiry, the request to Planning, the options Planning gives, the order on a clear "yes", the notice to Planning.

Used by the simulator's customer driver for large runs. The chat path (`manager.process_conversation`) is unchanged.
Conversations of this path use the channel `SIMULATED`; Sales does not write chat replies for them.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.sales_agent import data_access, manager
from app.sales_agent.planning import PlanningConnector

CHANNEL = "SIMULATED"


def request(db: Session, phone: str, product_id: str, quantity: Decimal, requested_date: date, today: date,
            planning: PlanningConnector) -> dict:
    """A simulated customer asks for `quantity` of a product by a date: a new inquiry, sent to Planning."""
    product = data_access.get_product(db, uuid.UUID(str(product_id)))
    if product is None or not product.active:
        raise AppError(ErrorCode.VALIDATION_ERROR, "unknown product", [{"field": "product_id", "issue": "unknown"}])
    if quantity <= 0 or requested_date <= today:
        raise AppError(ErrorCode.VALIDATION_ERROR, "quantity must be positive and the date in the future")
    conversation = manager._find_or_start_conversation(db, CHANNEL, phone)
    if conversation.current_inquiry_id is not None:
        current = data_access.get_inquiry(db, conversation.current_inquiry_id)
        if current is not None and current.stage not in ("CONFIRMED", "CLOSED"):
            current.stage, current.closed_reason = "CLOSED", "REPLACED"
            db.flush()
    data_access.save_message(db, conversation.id, "IN", f"[simulated] {quantity} x {product.name} by {requested_date}")
    inquiry = data_access.create_inquiry(db, conversation)
    inquiry.product_id, inquiry.quantity, inquiry.requested_date = product.id, quantity, requested_date
    collected = manager._collected_details(db, inquiry)
    manager._send_to_planning(db, conversation, inquiry, collected, today, planning)  # commits, then sends
    return {"inquiry_id": str(inquiry.id), "request_ref": inquiry.planning_request_ref}


def options(db: Session, inquiry_id: str) -> dict:
    """The inquiry as the simulated customer sees it: stage and the open options (structured, not chat text)."""
    inquiry = data_access.get_inquiry(db, uuid.UUID(str(inquiry_id)))
    if inquiry is None:
        raise AppError(ErrorCode.NOT_FOUND, "no such inquiry")
    return {"inquiry_id": str(inquiry.id), "stage": inquiry.stage,
            "options": [{"option_id": str(o.id), "kind": o.kind, "quantity": str(o.quantity),
                         "delivery_date": o.delivery_date.isoformat()} for o in manager._open_options(db, inquiry)]}


def accept(db: Session, inquiry_id: str, option_id: str, planning: PlanningConnector) -> dict:
    """The simulated customer chooses one option and says yes: the order exists (customer acceptance); Planning is
    told and commits (or not) on its own — acceptance is not commitment."""
    inquiry = data_access.get_inquiry(db, uuid.UUID(str(inquiry_id)))
    if inquiry is None:
        raise AppError(ErrorCode.NOT_FOUND, "no such inquiry")
    offered = manager._open_options(db, inquiry)
    chosen = next((o for o in offered if str(o.id) == str(option_id)), None)
    if chosen is None or inquiry.stage == "CONFIRMED":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, "that option is not open")
    if inquiry.offer_valid_until is not None and inquiry.offer_valid_until < datetime.now(timezone.utc):
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, "the offer has expired")
    conversation = data_access.get_conversation(db, inquiry.conversation_id)
    for option in offered:
        option.status = "SELECTED" if option is chosen else "OFFERED"
    inquiry.selected_option_id = chosen.id
    yes = data_access.save_message(db, conversation.id, "IN", "[simulated] yes")
    product = data_access.get_product(db, inquiry.product_id)
    _reply, notice = manager._make_order(db, conversation, inquiry, chosen, yes, product.name)
    db.commit()
    manager._send_confirmation(db, conversation, inquiry, notice, planning)
    return {"order_number": notice["order_number"], "quantity": notice["quantity"],
            "delivery_date": notice["delivery_date"]}


def decline(db: Session, inquiry_id: str) -> dict:
    inquiry = data_access.get_inquiry(db, uuid.UUID(str(inquiry_id)))
    if inquiry is None:
        raise AppError(ErrorCode.NOT_FOUND, "no such inquiry")
    for option in manager._open_options(db, inquiry):
        option.status = "RELEASED"
    inquiry.stage, inquiry.closed_reason = "CLOSED", "DECLINED"
    db.commit()
    return {"inquiry_id": str(inquiry.id), "stage": inquiry.stage}
