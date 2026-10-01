"""Supplier interface (a service, not an agent; there is no Supplier Agent in the 25%).

Turns one supplier-form response (the tester plays the supplier) into a C4 message from sender type
`SUPPLIER_INTERFACE` and delivers it to the Purchasing Agent over A2A. It decides nothing: whether the response is
acceptable is the Purchasing Agent's decision. No price/cost field.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core import a2a_client
from app.core.errors import AppError, ErrorCode
from app.schemas.negotiation import MessageType
from app.services import negotiation_service


def respond(
    db: Session,
    negotiation_id: uuid.UUID,
    round_number: int,
    response_type: MessageType,
    quantity: Decimal | None = None,
    delivery_date: date | None = None,
    note: str | None = None,
) -> dict:
    """Deliver the response; returns the session view after the agents have reacted. A refused response changes nothing."""
    message = negotiation_service.build_supplier_message(
        db, negotiation_id, round_number, response_type, quantity, delivery_date, note
    )
    db.commit()  # hold no open transaction while the agents react in other sessions
    ack = a2a_client.send(message)
    if not ack.get("accepted"):
        error = ack.get("error") or {}
        code = error.get("code", ErrorCode.INTERNAL_ERROR.value)
        raise AppError(ErrorCode(code), error.get("message", "the supplier response was refused"), error.get("details"))
    db.expire_all()  # the agents changed rows through their own sessions
    view = negotiation_service.get_session_view(db, negotiation_id)
    if "reaction_error" in ack:
        view["reaction_error"] = ack["reaction_error"]
    return view
