"""LLM wording applied after the decision is committed (dev_docs/purchasing_agent/purchasing_agent_architecture.md §9,
"Locks and LLM calls"). No lock is held while the LLM runs:

1. The deterministic transaction stores every message awaiting a reply with its template text, collects a
   `PendingWording` for each, and commits (the supplier-item and row locks are released).
2. `apply_wordings` asks the LLM (`writer.py`, guardrails included) to word each template, outside any transaction.
3. Each Leg is then locked again, briefly, and the worded text replaces the template only if the Leg is still PENDING
   and the message is still its session's latest, unanswered message (`negotiation_engine.reword_message`). The terms
   are stored with the message and never change. Otherwise the result is stale: the template stays.

The selection explanation follows the same pattern (`apply_explanation`): it is stored in the SUPPLIER_SELECTION audit
only while that audit has none. The audited decision never changes, so it cannot go stale.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.llm.client import LLMClient
from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent.models import DecisionAudit, LegStatus, PurchaseRequisition
from app.purchasing_agent.writer import MessageWriter, explain_selection


@dataclass(frozen=True)
class PendingWording:
    leg_id: uuid.UUID
    session_id: uuid.UUID
    message_id: uuid.UUID
    supplier_id: uuid.UUID
    template: str  # the text stored now
    terms: dict | None  # must appear exactly in the wording
    prefix: str = ""  # the echo, kept as written


def apply_wordings(db: Session, writer: MessageWriter, pending: list[PendingWording]) -> None:
    """Call with no transaction open (after the deterministic commit). Commits."""
    db.rollback()  # never hold a transaction (or its locks) while the LLM runs
    worded = [(p, writer.write(p.supplier_id, p.template, p.terms, p.prefix)) for p in pending]
    for p, text in worded:
        if text == p.template:
            continue
        # The Leg first, then its session: the lock order every writer uses.
        leg = db.get(PurchaseRequisition, p.leg_id, with_for_update=True, populate_existing=True)
        if leg is not None and leg.status == LegStatus.PENDING:
            negotiation_engine.reword_message(db, p.session_id, p.message_id, text)
        db.commit()


def apply_explanation(db: Session, llm_client: LLMClient, audit_id: uuid.UUID, facts: dict) -> None:
    """Call with no transaction open (after the deterministic commit). Commits."""
    db.rollback()
    if (explanation := explain_selection(llm_client, facts)) is None:
        return
    db.execute(update(DecisionAudit)
               .where(DecisionAudit.id == audit_id, DecisionAudit.llm_explanation.is_(None))
               .values(llm_explanation=explanation))
    db.commit()
