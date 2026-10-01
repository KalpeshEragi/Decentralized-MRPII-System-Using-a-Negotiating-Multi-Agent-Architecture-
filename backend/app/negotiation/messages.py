"""Stateless message validation: envelope parsing, sender/receiver routes and required terms per message type."""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.negotiation.protocol import ProtocolError, ProtocolErrorCode
from app.schemas.negotiation import AgentType, MessageType, NegotiationMessage

INV, PUR, SUP, APP = (
    AgentType.INVENTORY,
    AgentType.PURCHASING,
    AgentType.SUPPLIER_INTERFACE,
    AgentType.APPROVAL_WORKFLOW,
)

# Allowed (sender, receiver) types per message type (C4 sections 6-7).
ROUTES: dict[MessageType, frozenset[tuple[AgentType, AgentType]]] = {
    MessageType.REQUEST: frozenset({(INV, PUR)}),
    MessageType.OFFER: frozenset({(PUR, SUP)}),
    MessageType.COUNTER_OFFER: frozenset({(PUR, SUP), (SUP, PUR)}),
    MessageType.ACCEPT: frozenset({(SUP, PUR)}),
    # Either the supplier interface or Purchasing (early, before round 3) may reject.
    MessageType.REJECT: frozenset({(SUP, PUR), (PUR, SUP), (PUR, INV)}),
    MessageType.AGREEMENT_PROPOSED: frozenset({(PUR, INV)}),
    # COMMIT is an approval/lifecycle action, never sent by Inventory or Purchasing.
    MessageType.COMMIT: frozenset({(APP, INV)}),
    # ABORT (C8): the approval workflow closes an uncommitted agreement after the human rejects the plan.
    MessageType.ABORT: frozenset({(APP, INV)}),
}

# Terms are required by these types; all other types must not carry terms.
TERMS_REQUIRED = frozenset(
    {MessageType.REQUEST, MessageType.OFFER, MessageType.COUNTER_OFFER, MessageType.AGREEMENT_PROPOSED}
)


def parse_message(data: Mapping[str, Any]) -> NegotiationMessage:
    """Build a message from raw data; a malformed envelope becomes INVALID_MESSAGE."""
    try:
        message = NegotiationMessage.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ProtocolError(ProtocolErrorCode.INVALID_MESSAGE, f"invalid envelope: {problems}") from exc
    validate_message(message)
    return message


def validate_message(message: NegotiationMessage) -> None:
    def invalid(text: str) -> ProtocolError:
        return ProtocolError(ProtocolErrorCode.INVALID_MESSAGE, text)

    route = (message.sender.agent_type, message.receiver.agent_type)
    if route not in ROUTES[message.message_type]:
        raise invalid(f"{message.message_type} cannot be sent from {route[0]} to {route[1]}")

    terms = message.payload.terms
    if message.message_type in TERMS_REQUIRED:
        if terms is None:
            raise invalid(f"{message.message_type} requires terms")
        if message.message_type == MessageType.REQUEST and terms.required_date is None:
            raise invalid("REQUEST terms require required_date")
        if message.message_type != MessageType.REQUEST and terms.delivery_date is None:
            raise invalid(f"{message.message_type} terms require delivery_date")
    elif terms is not None:
        raise invalid(f"{message.message_type} must not carry terms")
