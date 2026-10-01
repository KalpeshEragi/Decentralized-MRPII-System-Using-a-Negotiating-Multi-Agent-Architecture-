"""C4 negotiation shapes: message envelope, offer terms, message types and session statuses.

`OfferTerms` is fixed to `quantity`, `required_date`, `delivery_date` and `priority`. Lead time comes from supplier
data, `delivery_date` is the negotiated commitment, and inventory impact is calculated by deterministic application
logic, so none of them is an offer term. Models forbid unknown fields, so price/cost or any other extra field is
rejected by construction.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.domain import PositiveQuantity

PROTOCOL_VERSION = "1.0"
MAX_ROUNDS = 3  # supplier rounds per session (P1-07)


class MessageType(StrEnum):
    REQUEST = "REQUEST"
    OFFER = "OFFER"
    COUNTER_OFFER = "COUNTER_OFFER"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    AGREEMENT_PROPOSED = "AGREEMENT_PROPOSED"
    COMMIT = "COMMIT"
    ABORT = "ABORT"  # C8: the approval workflow closes an uncommitted agreement when the human rejects the plan


class SessionStatus(StrEnum):
    INITIATED = "INITIATED"
    NEGOTIATING = "NEGOTIATING"
    AGREEMENT_PROPOSED = "AGREEMENT_PROPOSED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    ABORTED = "ABORTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


END_STATUSES = frozenset(
    {
        SessionStatus.COMMITTED,
        SessionStatus.REJECTED,
        SessionStatus.ABORTED,
        SessionStatus.EXPIRED,
        SessionStatus.FAILED,
    }
)


class AgentType(StrEnum):
    INVENTORY = "INVENTORY"
    PURCHASING = "PURCHASING"
    # The supplier form/service only. Supplier = data/service/interface; there is no Supplier Agent in the 25%.
    SUPPLIER_INTERFACE = "SUPPLIER_INTERFACE"
    # The application/approval workflow (C8, later phase); not an agent. It alone sends COMMIT.
    APPROVAL_WORKFLOW = "APPROVAL_WORKFLOW"


class Shape(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OfferTerms(Shape):
    quantity: PositiveQuantity
    required_date: date | None = None
    delivery_date: date | None = None
    priority: Annotated[int, Field(ge=1, le=5)] | None = None  # 1 = highest


class AgentRef(Shape):
    agent_id: Annotated[str, Field(min_length=1)]
    agent_type: AgentType


class MessagePayload(Shape):
    terms: OfferTerms | None = None
    message: str | None = None


class NegotiationMessage(Shape):
    protocol_version: Literal["1.0"] = PROTOCOL_VERSION
    message_id: Annotated[str, Field(min_length=1)]
    negotiation_id: Annotated[str, Field(min_length=1)]
    sender: AgentRef
    receiver: AgentRef
    message_type: MessageType
    sequence_number: Annotated[int, Field(ge=1)]
    timestamp: datetime
    correlation_id: str | None = None
    payload: MessagePayload = MessagePayload()
