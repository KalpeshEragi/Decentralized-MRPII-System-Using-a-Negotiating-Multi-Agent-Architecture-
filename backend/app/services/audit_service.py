"""Audit writes (C7). Records are append-only and written through this service, never by agents directly.

`decision_type` values and the JSON shape of `context` / `decision` are still PENDING in C7; the values below are the
Phase 2 / Phase 3 working set. `context` always carries the ids the record relates to (order_id, negotiation_id, item_id).
"""

import uuid
from enum import StrEnum

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.agent import Agent
from app.models.audit import DecisionAudit

AGENT_PLANNING = "PRODUCTION_PLANNING_AGENT"
AGENT_INVENTORY = "INVENTORY_AGENT"
AGENT_PURCHASING = "PURCHASING_AGENT"


class DecisionType(StrEnum):
    ORDER_RECEIVED = "ORDER_RECEIVED"  # Planning
    PLAN_CREATED = "PLAN_CREATED"  # Planning
    SHORTAGE_DETECTED = "SHORTAGE_DETECTED"  # Inventory (P0-02)
    NEGOTIATION_REQUEST = "NEGOTIATION_REQUEST"  # Inventory opens the session
    NEGOTIATION_MESSAGE = "NEGOTIATION_MESSAGE"  # Purchasing OFFER / COUNTER_OFFER
    AGREEMENT_PROPOSED = "AGREEMENT_PROPOSED"  # Purchasing
    NEGOTIATION_REJECTED = "NEGOTIATION_REJECTED"  # session REJECTED (by Purchasing or the supplier interface)
    NEGOTIATION_FAILED = "NEGOTIATION_FAILED"  # round limit reached without agreement
    AGREEMENT_COMMITTED = "AGREEMENT_COMMITTED"  # COMMIT by the approval workflow, recorded under Inventory
    AGREEMENT_ABORTED = "AGREEMENT_ABORTED"  # ABORT by the approval workflow (plan rejected), recorded under Inventory
    # Phase 3 (agents), working values:
    AVAILABILITY_ASSESSED = "AVAILABILITY_ASSESSED"  # Inventory: requirement-by-requirement stock / procurement decision
    REQUISITION_CREATED = "REQUISITION_CREATED"  # Purchasing
    NEGOTIATION_DECISION = "NEGOTIATION_DECISION"  # Purchasing: how a turn was decided (LLM or own policy) and its rationale
    LLM_PROPOSAL_REJECTED = "LLM_PROPOSAL_REJECTED"  # any agent: LLM output refused by deterministic validation (C7 rule 7)
    NEGOTIATION_RESULT_RECEIVED = "NEGOTIATION_RESULT_RECEIVED"  # Inventory, then Planning: AGREEMENT or FAILED
    # Phase 4 (C8), working values; the human's decisions are recorded under Planning with decided_by = HUMAN:
    PLAN_ATTEMPT_STARTED = "PLAN_ATTEMPT_STARTED"  # Planning: attempt n of 2, its plan status and negotiations
    PLAN_APPROVED = "PLAN_APPROVED"
    PLAN_REJECTED = "PLAN_REJECTED"
    HUMAN_INTERVENTION_REQUIRED = "HUMAN_INTERVENTION_REQUIRED"
    STOCK_RESERVED = "STOCK_RESERVED"  # Inventory, after COMMIT (D8)


def jsonable(value: object) -> object:
    """JSON-safe copy of a pydantic model, dict or list (dates become ISO strings; model quantities become numbers)."""
    return to_jsonable_python(value)


def agent_uuid(db: Session, agent_code: str) -> uuid.UUID:
    """The agent's id, cached for the life of the DB session (every agent step needs it; each query is a round trip)."""
    cache = db.info.setdefault("agent_ids", {})
    if agent_code not in cache:
        agent_id = db.scalar(select(Agent.id).where(Agent.agent_code == agent_code))
        if agent_id is None:
            raise AppError(ErrorCode.INTERNAL_ERROR, f"agent {agent_code} is not seeded")
        cache[agent_code] = agent_id
    return cache[agent_code]


def record(
    db: Session,
    agent_code: str,
    decision_type: DecisionType,
    context: dict,
    decision: dict,
    reasoning_summary: str,
) -> DecisionAudit:
    """Add one audit row to the session; the caller's transaction commits it. No cost/price, no chain-of-thought."""
    row = DecisionAudit(
        agent_id=agent_uuid(db, agent_code),
        decision_type=decision_type.value,
        context=jsonable(context),
        decision=jsonable(decision),
        reasoning_summary=reasoning_summary,
    )
    db.add(row)
    db.flush()
    return row


def list_decisions(db: Session, order_id: uuid.UUID | None = None, negotiation_id: uuid.UUID | None = None) -> list[dict]:
    """The decision log: records in creation order, each with the code of the agent that made the decision."""
    codes = dict(db.execute(select(Agent.id, Agent.agent_code)).all())
    return [
        {
            "id": str(row.id),
            "agent": codes.get(row.agent_id),
            "decision_type": row.decision_type,
            "context": row.context,
            "decision": row.decision,
            "reasoning_summary": row.reasoning_summary,
            "created_at": row.created_at,
        }
        for row in list_records(db, order_id, negotiation_id)
    ]


def list_records(db: Session, order_id: uuid.UUID | None = None, negotiation_id: uuid.UUID | None = None) -> list[DecisionAudit]:
    query = select(DecisionAudit).order_by(DecisionAudit.created_at, DecisionAudit.id)
    if order_id is not None:
        query = query.where(DecisionAudit.context["order_id"].astext == str(order_id))
    if negotiation_id is not None:
        query = query.where(DecisionAudit.context["negotiation_id"].astext == str(negotiation_id))
    return list(db.scalars(query))
