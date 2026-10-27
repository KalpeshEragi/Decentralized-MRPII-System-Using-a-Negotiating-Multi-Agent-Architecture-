"""Decision records and the model client for decisions (QD-3, QD-5, QD-10; design §6.1, §10).

A decision is stored in the deciding agent's own `audit_log` (`event_type = DECISION`) and each model call in
`observability.llm_calls`. The caller passes its own audit model, so no agent writes another agent's table.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_decisions.think import Decision, Situation
from app.core.config import get_settings
from app.llm.client import LLMClient, OllamaClient
from app.observability.models import LlmCall
from app.simulation.settings import setting

DECISION = "DECISION"
# Measured 2026-10-26 on this laptop: one decision call ~50 s on CPU, ~34 s after the Ollama repair (RTX 2050, model
# split about 50/50 GPU/CPU: 3.7 GB does not fit in the 3.2 GB free of 4 GB). With the model's hidden thinking
# mode on, a call did not finish within 300 s, so the agent's thinking is written into its JSON answer instead
# ("thinking" field, shown in the UI) and the hidden mode stays off.
DECISION_TIMEOUT_SECONDS = 90.0


def ai_decisions_on(db: Session) -> bool:
    """AI on, and a small run (QD-5): load runs keep the deterministic fallbacks."""
    from app.planning_agent import reads as planning

    if not int(setting(db, "ai_enabled")):
        return False
    return planning.open_demand_count(db) <= int(setting(db, "ai_decision_max_orders"))


def decision_client(db: Session) -> LLMClient | None:
    """The shared model for decisions, or None when decisions use the fallbacks. The agent writes its reasoning in the
    answer's "thinking" field; the model's hidden thinking mode stays off (too slow here, see above)."""
    if not ai_decisions_on(db):
        return None
    return OllamaClient.from_settings(reasoning_effort="none", timeout=DECISION_TIMEOUT_SECONDS)


def record(db: Session, audit_model: type, situation: Situation, decision: Decision) -> uuid.UUID:
    """Store the decision in the agent's own audit log and its model calls in the call log (caller commits)."""
    model_name = get_settings().ollama_model
    call_ids = []
    finished = datetime.now(timezone.utc)
    for call in reversed(decision.calls):  # times counted back from now, oldest last
        started = finished - timedelta(seconds=call.seconds)
        row = LlmCall(id=uuid.uuid4(), agent=situation.agent, purpose=f"DECISION_{situation.point}",
                      case_id=situation.case_id, queued_at=started, started_at=started, finished_at=finished,
                      outcome=call.outcome, prompt_chars=call.prompt_chars, output_chars=call.output_chars,
                      model=model_name)
        db.add(row)
        call_ids.insert(0, str(row.id))
        finished = started
    entry = audit_model(id=uuid.uuid4(), actor="AGENT_AI" if decision.chosen_by != "FALLBACK" else "POLICY",
                        event_type=DECISION, case_id=situation.case_id, details=details(situation, decision, call_ids))
    db.add(entry)
    db.flush()
    return entry.id


def details(situation: Situation, decision: Decision, call_ids: list[str] | None = None) -> dict[str, Any]:
    """The decision record (design §6.1), JSON-ready."""
    return _jsonable({
        "agent": situation.agent, "decision_point": situation.point, "case_id": situation.case_id,
        "order_id": situation.order_id, "goal": situation.goal, "facts": situation.facts,
        "actions": situation.actions, "hints": situation.hints,
        "thinking": decision.thinking, "looked_up": decision.looked_up,
        "action": decision.action, "params": decision.params, "reason": decision.reason,
        "chosen_by": decision.chosen_by, "fallback": list(decision.fallback) if decision.fallback else None,
        "fallback_reason": decision.fallback_reason, "refusals": decision.refusals,
        "llm_call_ids": call_ids or [],
    })


def rows(db: Session, audit_model: type, after: datetime | None = None, at: datetime | None = None,
         limit: int | None = None) -> list[dict[str, Any]]:
    """An agent's decisions as timeline rows (`source = "decision"`), for its read module (IB-2)."""
    query = select(audit_model).where(audit_model.event_type == DECISION).order_by(audit_model.time)
    if at is not None:
        query = query.where(audit_model.time == at)
    else:
        query = query.where(audit_model.time > after) if after else query
        query = query.limit(limit) if limit else query
    return [{"time": row.time, "source": "decision", "agent": row.details.get("agent"), "case_id": row.case_id,
             "decision": row.details} for row in db.scalars(query)]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)  # Decimal, date, UUID: as text
