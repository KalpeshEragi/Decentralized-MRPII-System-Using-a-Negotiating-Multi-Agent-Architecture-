"""The negotiation message of the six-agent design (dev_docs/architecture/negotiation.md §4, §5, §5.1).

A starter (the agent with the problem) negotiates with an owner (the agent that owns the resource). Messages carry
multi-factor terms, never price or cost. The old 25% envelope (`app/schemas/negotiation.py`) is retired in step 5.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AGENTS = ("SALES", "PLANNING", "INVENTORY", "PURCHASING", "WAREHOUSE", "HR")
FORBIDDEN_KEYS = ("price", "cost", "priority")  # never terms (no price/cost; urgency is computed by the owner)


class MessageType(StrEnum):
    REQUEST = "REQUEST"
    OFFER = "OFFER"
    COUNTER_OFFER = "COUNTER_OFFER"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    AGREEMENT_PROPOSED = "AGREEMENT_PROPOSED"
    COMMIT = "COMMIT"
    ABORT = "ABORT"


class ResourceType(StrEnum):
    STOCK = "STOCK"
    SUPPLY = "SUPPLY"
    RECEIVING_SLOT = "RECEIVING_SLOT"
    STORAGE_SPACE = "STORAGE_SPACE"
    WORKFORCE = "WORKFORCE"
    PRODUCTION_CAPACITY = "PRODUCTION_CAPACITY"


class ReasonCode(StrEnum):
    """NG-6: exactly one on every REJECT and COUNTER_OFFER. Purchasing may add its own later."""

    INSUFFICIENT = "INSUFFICIENT"
    TOO_LATE = "TOO_LATE"
    NO_SPACE = "NO_SPACE"
    NO_RECEIVING_CAPACITY = "NO_RECEIVING_CAPACITY"
    NO_WORKFORCE = "NO_WORKFORCE"
    POLICY_LIMIT = "POLICY_LIMIT"
    OUTSIDE_HORIZON = "OUTSIDE_HORIZON"
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    HOLD_EXPIRED = "HOLD_EXPIRED"
    INVALID_REQUEST = "INVALID_REQUEST"


def _no_forbidden_keys(value: Any, where: str) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if any(word in str(key).lower() for word in FORBIDDEN_KEYS):
                raise ValueError(f"{where} must not contain '{key}' (no price, cost or claimed priority)")
            _no_forbidden_keys(inner, where)


class Terms(BaseModel):
    """Common terms (negotiation.md §5). Resource-specific fields go into `extra` (e.g. hours per day, allow_overtime)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: ResourceType
    resource_ref: str = Field(min_length=1)
    quantity: Decimal = Field(ge=0)
    unit: str = "pcs"
    needed_by: date | None = None
    available_from: date | None = None
    date_from: date | None = None
    date_to: date | None = None
    order_id: str | None = None
    facts_version: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extra")
    @classmethod
    def _extra_has_no_price(cls, value: dict) -> dict:
        _no_forbidden_keys(value, "extra")
        return value

    def same_deal(self, other: "Terms") -> bool:
        """Equal in everything that is agreed (facts_version may differ)."""
        return self.model_dump(exclude={"facts_version"}) == other.model_dump(exclude={"facts_version"})


class Hold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hold_id: str = Field(min_length=1)
    expires_at: datetime


class Envelope(BaseModel):
    """One negotiation message. Sequence numbers are assigned by the receiving side when it stores the message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    sender: str
    receiver: str
    message_type: MessageType
    terms: Terms | None = None
    reason_code: ReasonCode | None = None
    hold: Hold | None = None
    text: str | None = Field(default=None, max_length=500)  # wording (template now, AI later); never business data
    sent_at: datetime

    @model_validator(mode="after")
    def _shape(self) -> "Envelope":
        if self.sender not in AGENTS or self.receiver not in AGENTS or self.sender == self.receiver:
            raise ValueError("sender and receiver must be two different agents")
        kind = self.message_type
        if kind in (MessageType.REQUEST, MessageType.OFFER, MessageType.COUNTER_OFFER, MessageType.AGREEMENT_PROPOSED):
            if self.terms is None:
                raise ValueError(f"{kind} requires terms")
        elif self.terms is not None:
            raise ValueError(f"{kind} must not carry terms")
        if kind in (MessageType.REJECT, MessageType.COUNTER_OFFER) and self.reason_code is None:
            raise ValueError(f"{kind} requires a reason_code (NG-6)")
        if (kind == MessageType.AGREEMENT_PROPOSED) != (self.hold is not None):
            raise ValueError("a hold is carried by AGREEMENT_PROPOSED and only by it")
        return self
