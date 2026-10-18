"""A2A endpoints of the six-agent design (NG-1, negotiation.md §10.3): one JSON-RPC endpoint of the official A2A SDK
per negotiating agent at `/a2a/<agent>`, with its agent card at `/a2a/<agent>/.well-known/agent-card.json`.

Store and acknowledge: the endpoint validates the message, stores it (session change + inbox item) and answers at
once. The agent reacts later, from its inbox worker — no agent work happens inside the HTTP request.

The old 25% endpoints were retired in step 4; Purchasing's endpoint goes live with the contributor's agent (or the
FAKE stub, step 6).
"""

import asyncio
from collections.abc import Callable

from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import add_a2a_routes_to_fastapi, create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import new_session
from app.negotiation import layer
from app.negotiation.transport import path_for

LIVE_AGENTS = ("PLANNING", "INVENTORY", "WAREHOUSE", "HR", "PURCHASING")  # Purchasing through its adapter (PI-3)

_session_factory: Callable[[], Session] = new_session


def set_session_factory(factory: Callable[[], Session]) -> None:
    """Tests point the endpoints at the test database."""
    global _session_factory
    _session_factory = factory


def store_and_acknowledge(receiver: str, data: object) -> dict:
    with _session_factory() as db:
        ack = layer.receive(db, receiver, data)
        if ack["accepted"] and not ack["duplicate"]:
            db.commit()
        else:
            db.rollback()
    return ack


class NegotiationExecutor(AgentExecutor):
    def __init__(self, receiver: str):
        self.receiver = receiver

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        parts = get_data_parts(context.message.parts) if context.message else []
        ack = await asyncio.to_thread(store_and_acknowledge, self.receiver, parts[0] if parts else None)
        await event_queue.enqueue_event(new_data_message(ack))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return None  # every request completes immediately


def _card(agent: str) -> AgentCard:
    return AgentCard(
        name=f"mrpii-{agent.lower()}",
        description=f"{agent.title()} Agent negotiation endpoint (store and acknowledge)",
        version="0.2.0",
        supported_interfaces=[AgentInterface(url=get_settings().a2a_base_url.rstrip("/") + path_for(agent),
                                             protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[AgentSkill(id="negotiation", name="Negotiation message",
                           description="Receives one negotiation message (negotiation.md §4–5) and acknowledges it.",
                           tags=["negotiation"])],
    )


def install(app: FastAPI, agents: tuple[str, ...] = LIVE_AGENTS) -> None:
    for agent in agents:
        path, card = path_for(agent), _card(agent)
        handler = DefaultRequestHandler(agent_executor=NegotiationExecutor(agent), task_store=InMemoryTaskStore(),
                                        agent_card=card)
        add_a2a_routes_to_fastapi(app,
                                  agent_card_routes=create_agent_card_routes(card, card_url=f"{path}/.well-known/agent-card.json"),
                                  jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url=path))
