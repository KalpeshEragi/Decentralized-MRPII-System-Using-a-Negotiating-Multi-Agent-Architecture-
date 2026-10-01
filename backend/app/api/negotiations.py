"""Negotiations API: open a session for a shortage, exchange C4 messages, supplier responses, read state.

The API only routes; the protocol (`app.negotiation`) decides validity and `negotiation_service` persists.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError, ErrorCode
from app.schemas.negotiation import MessageType, NegotiationMessage
from app.services import negotiation_service

router = APIRouter(prefix="/negotiations", tags=["negotiations"])


class NegotiationOpen(BaseModel):
    order_id: uuid.UUID
    item_id: uuid.UUID


class SupplierResponseIn(BaseModel):
    """The supplier form: one response per round. No price/cost field."""

    round_number: Annotated[int, Field(ge=1, le=3)]
    response_type: Literal["ACCEPT", "COUNTER_OFFER", "REJECT"]
    quantity: Annotated[Decimal, Field(gt=0)] | None = None
    delivery_date: date | None = None
    message: str | None = None


def refuse_commit(message: NegotiationMessage) -> None:
    """COMMIT and ABORT belong to the approval workflow (C8), reached only through the plan approve / reject routes;
    no message route or A2A endpoint may send them."""
    if message.message_type in (MessageType.COMMIT, MessageType.ABORT):
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            f"{message.message_type.value} is performed by the approval workflow (approve / reject the plan)",
        )


@router.post("", status_code=201)
def open_negotiation(data: NegotiationOpen, db: Session = Depends(get_db)):
    """Create the one session for a persisted shortage; Inventory then sends REQUEST as the first message."""
    return negotiation_service.open_session(db, data.order_id, data.item_id)


@router.get("/{negotiation_id}")
def get_negotiation(negotiation_id: uuid.UUID, db: Session = Depends(get_db)):
    return negotiation_service.get_session_view(db, negotiation_id)


@router.post("/{negotiation_id}/messages")
def post_message(negotiation_id: uuid.UUID, message: NegotiationMessage, db: Session = Depends(get_db)):
    refuse_commit(message)
    return negotiation_service.submit_message(db, negotiation_id, message)


@router.post("/{negotiation_id}/supplier-responses")
def post_supplier_response(negotiation_id: uuid.UUID, data: SupplierResponseIn, db: Session = Depends(get_db)):
    return negotiation_service.submit_supplier_response(
        db,
        negotiation_id,
        data.round_number,
        MessageType(data.response_type),
        data.quantity,
        data.delivery_date,
        data.message,
    )
