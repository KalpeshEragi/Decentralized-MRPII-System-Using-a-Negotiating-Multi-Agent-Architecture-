"""Agent base (Phase 3): C6 agent state, the C7 audit writer, the LLM proposer client and A2A sending.

State (C6): each agent reads and writes only its own `agent.agent_state` row through `Agent.load_state` /
`Agent.save_state` (C6 rule 1). State is validated against the C6 shapes before every write (no cost/price keys) and
holds decision context only; business truth stays in the owning services. C6 has one row per agent while several
sessions can be open at once (the X1 baseline has two shortages), so the state describes the agent's *current* work:
the negotiation (or order) it handled last. Offer histories are rebuilt from the stored session messages
(`offer_history`), so nothing is lost when the focus moves; the dialogue history restarts with the new focus.

LLM: agents take their proposer from `llm_client()` (the configured Ollama model unless replaced, e.g. by tests).
A2A: `Agent.send` commits first, so no row lock is held while the receiver reacts, then drops cached rows.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core import a2a_client
from app.llm.client import LLMClient, OllamaClient
from app.models.agent import AgentState as AgentStateRow
from app.schemas.negotiation import (
    MAX_ROUNDS,
    AgentRef,
    AgentType,
    MessagePayload,
    MessageType,
    NegotiationMessage,
    OfferTerms,
)
from app.services import audit_service
from app.services.audit_service import DecisionType

SUMMARY_MAX = 300  # concise rationale only (C6 rule 4, C7 rule 3)
DIALOGUE_MAX = 10

Round = Annotated[int, Field(ge=1, le=MAX_ROUNDS)]
Counterpart = Literal["PLANNING", "INVENTORY", "PURCHASING", "SUPPLIER_INTERFACE"]


def now() -> datetime:
    return datetime.now(timezone.utc)


def plain(value: Any) -> Any:
    """JSON-ready copy for free-form state fields: Decimal -> number, dates -> ISO strings, models -> dicts."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    return audit_service.jsonable(value)


# -- C6 shapes ------------------------------------------------------------------------------------------------------


class _Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Refs(_Shape):
    order_id: str | None = None
    mps_entry_id: str | None = None
    item_id: str | None = None
    negotiation_id: str | None = None


class Goal(_Shape):
    goal_type: str
    description: str
    refs: Refs = Refs()


class Task(_Shape):
    task_type: str
    status: Literal["IDLE", "IN_PROGRESS", "WAITING", "DONE"]
    refs: Refs = Refs()
    started_at: datetime | None = None


class OfferRecord(_Shape):
    negotiation_id: str
    message_id: str
    round: Round
    message_type: MessageType
    terms: OfferTerms
    at: datetime


class DialogueEntry(_Shape):
    round: Round | None = None
    counterpart: Counterpart
    summary: Annotated[str, Field(max_length=SUMMARY_MAX)]
    at: datetime


class NegotiationRules(_Shape):
    max_rounds: Literal[3] = MAX_ROUNDS
    policy: dict[str, Any] = Field(default_factory=dict)


def _no_price(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if "price" in str(key).lower() or "cost" in str(key).lower():
                raise ValueError(f"{path}.{key}: no cost/price in agent state (out of scope for the 25%)")
            _no_price(item, f"{path}.{key}")
    elif isinstance(value, list):
        for item in value:
            _no_price(item, path)


class AgentStateData(_Shape):
    """The nine C6 JSONB columns of `agent.agent_state`."""

    current_goal: Goal | None = None
    current_task: Task | None = None
    preferred_terms: OfferTerms | None = None
    reserved_limits: dict[str, Any] = Field(default_factory=dict)
    initial_proposal: OfferTerms | None = None
    own_offer_history: Annotated[list[OfferRecord], Field(max_length=MAX_ROUNDS)] = Field(default_factory=list)
    opponent_offer_history: Annotated[list[OfferRecord], Field(max_length=MAX_ROUNDS)] = Field(default_factory=list)
    dialogue_history: Annotated[list[DialogueEntry], Field(max_length=DIALOGUE_MAX)] = Field(default_factory=list)
    negotiation_rules: NegotiationRules = Field(default_factory=NegotiationRules)

    @model_validator(mode="after")
    def _check_no_price(self) -> "AgentStateData":
        _no_price(self.reserved_limits, "reserved_limits")
        _no_price(self.negotiation_rules.policy, "negotiation_rules.policy")
        return self


FIELDS = tuple(AgentStateData.model_fields)


def load_state(db: Session, agent_code: str) -> AgentStateData:
    """Read one agent's state (fresh from the database); an agent without a row has the empty state."""
    row = db.get(AgentStateRow, audit_service.agent_uuid(db, agent_code), populate_existing=True)
    if row is None:
        return AgentStateData()
    return AgentStateData.model_validate({f: getattr(row, f) for f in FIELDS if getattr(row, f) is not None})


def _save_state(db: Session, agent_code: str, state: AgentStateData) -> None:
    data = AgentStateData.model_validate(state.model_dump()).model_dump(mode="json")  # validated before write
    agent_id = audit_service.agent_uuid(db, agent_code)
    row = db.get(AgentStateRow, agent_id, populate_existing=True)
    if row is None:
        row = AgentStateRow(agent_id=agent_id)
        db.add(row)
    for field in FIELDS:
        setattr(row, field, data[field])
    row.updated_at = now()
    db.flush()


def offer_history(view: dict) -> dict[str, list[OfferRecord]]:
    """Offer records of one session rebuilt from its stored messages (a negotiation_service session view).

    PURCHASING: Purchasing's OFFER / COUNTER_OFFER per round (a counter that tripped the round limit opened no round
    and is left out). SUPPLIER_INTERFACE: the supplier's ACCEPT / COUNTER_OFFER per round (an ACCEPT carries the
    accepted terms). AGREEMENT: Purchasing's AGREEMENT_PROPOSED.
    """
    records: dict[str, list[OfferRecord]] = {"PURCHASING": [], "SUPPLIER_INTERFACE": [], "AGREEMENT": []}
    round_number, last_offer = 0, None
    for message in view["messages"]:
        kind, sender, terms = message["message_type"], message["sender"], message["payload"].get("terms")
        if sender == "PURCHASING" and kind in ("OFFER", "COUNTER_OFFER"):
            if round_number == MAX_ROUNDS:
                continue
            round_number, last_offer, key = round_number + 1, terms, "PURCHASING"
        elif sender == "SUPPLIER_INTERFACE" and kind in ("ACCEPT", "COUNTER_OFFER"):
            terms, key = (terms if kind == "COUNTER_OFFER" else last_offer), "SUPPLIER_INTERFACE"
        elif kind == "AGREEMENT_PROPOSED" and round_number:
            key = "AGREEMENT"
        else:
            continue
        records[key].append(
            OfferRecord(
                negotiation_id=view["id"],
                message_id=str(message["message_id"]),
                round=round_number,
                message_type=MessageType(kind),
                terms=OfferTerms.model_validate(terms),
                at=message["timestamp"],
            )
        )
    return records


def build_message(
    view: dict,
    sender: AgentType,
    receiver: AgentType,
    kind: MessageType,
    terms: OfferTerms | None = None,
    note: str | None = None,
) -> NegotiationMessage:
    """The next C4 envelope of a session (a negotiation_service session view): participant ids and sequence from the view."""
    ids = view["participants"]
    return NegotiationMessage(
        message_id=str(uuid.uuid4()),
        negotiation_id=view["id"],
        sender=AgentRef(agent_id=ids[sender.value], agent_type=sender),
        receiver=AgentRef(agent_id=ids[receiver.value], agent_type=receiver),
        message_type=kind,
        sequence_number=len(view["messages"]) + 1,
        timestamp=now(),
        payload=MessagePayload(terms=terms, message=note[:SUMMARY_MAX] if note else None),
    )


# -- LLM proposer ---------------------------------------------------------------------------------------------------

_llm_client: LLMClient | None = None


def set_llm_client(client: LLMClient | None) -> None:
    """Replace the proposer (tests use a FakeLLMClient); None restores the configured Ollama model."""
    global _llm_client
    _llm_client = client


def llm_client() -> LLMClient:
    return _llm_client or OllamaClient.from_settings()


# -- agent ----------------------------------------------------------------------------------------------------------


class Agent:
    """Common behaviour. Subclasses set `agent_code` (an `agent.agents.agent_code`)."""

    agent_code: str

    def load_state(self, db: Session) -> AgentStateData:
        return load_state(db, self.agent_code)

    def save_state(self, db: Session, state: AgentStateData) -> None:
        _save_state(db, self.agent_code, state)

    def dialogue(self, state: AgentStateData, ref: str, value: str, *entries: DialogueEntry) -> list[DialogueEntry]:
        """The dialogue history continued while the focus (state.current_goal.refs.<ref>) stays on `value`."""
        same = state.current_goal is not None and getattr(state.current_goal.refs, ref) == value
        return (([*state.dialogue_history] if same else []) + [*entries])[-DIALOGUE_MAX:]

    def audit(self, db: Session, decision_type: DecisionType, context: dict, decision: dict, summary: str) -> None:
        """C7 record of this agent's own decision, through the audit service. Committed by the caller."""
        audit_service.record(db, self.agent_code, decision_type, plain(context), plain(decision), summary[:SUMMARY_MAX])

    def send(self, db: Session, message: NegotiationMessage) -> dict:
        """Send over A2A and return the acknowledgement. Commits first; the receiving agents react in other sessions."""
        db.commit()
        try:
            return a2a_client.send(message)
        finally:
            db.expire_all()
