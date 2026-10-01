"""A2A endpoints: three A2A HTTP endpoints in this same FastAPI app that carry the C4 envelope (Phase 2 transport).

    /a2a/inventory           receiver type INVENTORY           -> Inventory Agent
    /a2a/purchasing          receiver type PURCHASING          -> Purchasing Agent
    /a2a/supplier-interface  receiver type SUPPLIER_INTERFACE  (the supplier form/service, not an agent)

Each is a JSON-RPC endpoint of the official A2A SDK. The client (`app/core/a2a_client.py`) sends an A2A `SendMessage`
whose message has one data part holding the C4 `NegotiationMessage`; the executor validates it with the protocol,
persists it through `negotiation_service` and answers with one data part (the acknowledgement). A message the protocol
refuses is acknowledged with `accepted: false` and the error, and nothing changes. An accepted message is then routed
to the receiving agent (`app/agents/workflow.py`, Phase 3) before the acknowledgement is returned, so the whole
exchange stays synchronous (no event bus, no background jobs). The transport decides nothing. No auth; COMMIT is
refused until the approval workflow exists (C8).
"""

import asyncio
import logging
import uuid

from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import add_a2a_routes_to_fastapi, create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from fastapi import FastAPI

from app.agents import workflow
from app.api.negotiations import refuse_commit
from app.core.a2a_client import PATHS
from app.core.config import get_settings
from app.core.database import new_session
from app.core.errors import AppError, ErrorCode
from app.negotiation.messages import parse_message
from app.negotiation.protocol import ProtocolError
from app.schemas.negotiation import AgentType, NegotiationMessage
from app.services import negotiation_service

logger = logging.getLogger(__name__)

DESCRIPTIONS = {
    AgentType.INVENTORY: "Inventory Agent endpoint",
    AgentType.PURCHASING: "Purchasing Agent endpoint",
    AgentType.SUPPLIER_INTERFACE: "Supplier interface endpoint (the supplier form/service, not an agent)",
}
ENDPOINTS = {path: (receiver_type, DESCRIPTIONS[receiver_type]) for receiver_type, path in PATHS.items()}


def _refusal(code: str, message: str, details: list[dict] | None = None) -> dict:
    return {"accepted": False, "error": {"code": code, "message": message, "details": details or []}}


def deliver(receiver_type: AgentType, data: object) -> dict:
    """Validate and persist one C4 envelope addressed to `receiver_type`; always returns an acknowledgement."""
    if not isinstance(data, dict):
        return _refusal(ErrorCode.VALIDATION_ERROR.value, "the A2A message must carry one data part with the C4 envelope")
    try:
        message = parse_message(data)
        if message.receiver.agent_type != receiver_type:
            return _refusal(ErrorCode.VALIDATION_ERROR.value, f"this endpoint receives {receiver_type.value} messages")
        refuse_commit(message)
        negotiation_id = uuid.UUID(message.negotiation_id)
    except ProtocolError as exc:
        return _refusal(ErrorCode.VALIDATION_ERROR.value, exc.message, [{"issue": exc.code.value}])
    except AppError as exc:
        return _refusal(exc.code.value, exc.message, exc.details)
    except ValueError:
        return _refusal(ErrorCode.VALIDATION_ERROR.value, "negotiation_id must be a UUID")

    db = None
    try:
        db = new_session()
        view = negotiation_service.submit_message(db, negotiation_id, message)
    except AppError as exc:
        return _refusal(exc.code.value, exc.message, exc.details)
    finally:
        if db is not None:
            db.close()
    return {
        "accepted": True,
        "negotiation_id": view["id"],
        "sequence_number": message.sequence_number,
        "session_status": view["status"],
        "round_number": view["round_number"],
        "outcome": view["outcome"],
    }


def receive(receiver_type: AgentType, data: object) -> dict:
    """Deliver the envelope; if it was accepted, let the receiving agent react before acknowledging (Phase 3)."""
    ack = deliver(receiver_type, data)
    if not ack["accepted"]:
        return ack
    db = new_session()
    try:
        workflow.after_delivery(db, receiver_type, NegotiationMessage.model_validate(data), ack)
    except Exception:  # the message itself is stored; report that the reaction did not complete, without internals
        logger.exception("agent reaction to an accepted A2A message failed")
        db.rollback()
        ack = {**ack, "reaction_error": "the receiving agent could not complete its reaction; see the server log"}
    finally:
        db.close()
    return ack


class EnvelopeExecutor(AgentExecutor):
    """Receives the C4 envelope for one receiver type. Contains no negotiation logic."""

    def __init__(self, receiver_type: AgentType):
        self.receiver_type = receiver_type

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        parts = get_data_parts(context.message.parts) if context.message else []
        ack = await asyncio.to_thread(receive, self.receiver_type, parts[0] if parts else None)
        await event_queue.enqueue_event(new_data_message(ack))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return None  # each request completes immediately; nothing to cancel


def _agent_card(path: str, receiver_type: AgentType, description: str) -> AgentCard:
    return AgentCard(
        name=f"mrpii-{receiver_type.value.lower().replace('_', '-')}",
        description=description,
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(url=get_settings().a2a_base_url.rstrip("/") + path, protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="negotiation-envelope",
                name="C4 negotiation envelope",
                description="Receives a C4 negotiation message as one data part and acknowledges it.",
                tags=["negotiation"],
            )
        ],
    )


def install_a2a_spike(app: FastAPI) -> None:
    for path, (receiver_type, description) in ENDPOINTS.items():
        card = _agent_card(path, receiver_type, description)
        handler = DefaultRequestHandler(
            agent_executor=EnvelopeExecutor(receiver_type), task_store=InMemoryTaskStore(), agent_card=card
        )
        add_a2a_routes_to_fastapi(
            app,
            agent_card_routes=create_agent_card_routes(card, card_url=f"{path}/.well-known/agent-card.json"),
            jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url=path),
        )
