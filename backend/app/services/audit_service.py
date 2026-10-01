"""Audit writes (C7). Records are append-only and written through this service, never by agents directly.

`decision_type` values and the JSON shape of `context` / `decision` are still PENDING in C7; the values below are the
Phase 2 working set. `context` always carries the ids the record relates to (order_id, negotiation_id, item_id).
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


def jsonable(value: object) -> object:
    """JSON-safe copy of a pydantic model, dict or list (dates become ISO strings; model quantities become numbers)."""
    return to_jsonable_python(value)


def agent_uuid(db: Session, agent_code: str) -> uuid.UUID:
    agent_id = db.scalar(select(Agent.id).where(Agent.agent_code == agent_code))
    if agent_id is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"agent {agent_code} is not seeded")
    return agent_id


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


def list_records(db: Session, order_id: uuid.UUID | None = None, negotiation_id: uuid.UUID | None = None) -> list[DecisionAudit]:
    query = select(DecisionAudit).order_by(DecisionAudit.created_at, DecisionAudit.id)
    if order_id is not None:
        query = query.where(DecisionAudit.context["order_id"].astext == str(order_id))
    if negotiation_id is not None:
        query = query.where(DecisionAudit.context["negotiation_id"].astext == str(negotiation_id))
    return list(db.scalars(query))
