"""Plan approval workflow (C8): plan attempts, the human approve / reject decision, COMMIT and ABORT.

The approval workflow is application logic, not an agent (sender type APPROVAL_WORKFLOW, C4). It never negotiates and
never replans: it records the human decision and sends COMMIT (approve) or ABORT (reject) for the attempt's uncommitted
agreements. The agents' reactions (reservation, replanning) are routed by `app/agents/workflow.py`.

Storage (C8 option B): attempt state lives in `audit.decision_audit` records of the Planning Agent, like the plan data
that has no table (`planning_service`). Per attempt there is one PLAN_ATTEMPT_STARTED record and at most one decision
record (PLAN_APPROVED, PLAN_REJECTED or HUMAN_INTERVENTION_REQUIRED, `decided_by = HUMAN`). PENDING_NEGOTIATION and
AWAITING_APPROVAL are derived from the attempt's sessions, never stored.

    PENDING_NEGOTIATION -> AWAITING_APPROVAL -> APPROVED                       (COMMIT, only if approvable)
                                             -> REJECTED                       (attempt 1; Planning replans: attempt 2)
                                             -> HUMAN_INTERVENTION_REQUIRED    (reject of attempt 2; no more replanning)
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.audit import DecisionAudit
from app.schemas.negotiation import MessageType, SessionStatus
from app.services import audit_service, negotiation_service
from app.services.audit_service import AGENT_PLANNING, DecisionType

MAX_ATTEMPTS = 2  # planning attempts per order (DECISIONS.md, human rejection)

PENDING_NEGOTIATION = "PENDING_NEGOTIATION"
AWAITING_APPROVAL = "AWAITING_APPROVAL"
DECISIONS = {
    DecisionType.PLAN_APPROVED.value: "APPROVED",
    DecisionType.PLAN_REJECTED.value: "REJECTED",
    DecisionType.HUMAN_INTERVENTION_REQUIRED.value: "HUMAN_INTERVENTION_REQUIRED",
}
OPEN_SESSION = {SessionStatus.INITIATED.value, SessionStatus.NEGOTIATING.value}


def _records(db: Session, order_id: uuid.UUID) -> list[DecisionAudit]:
    types = [DecisionType.PLAN_ATTEMPT_STARTED.value, *DECISIONS]
    return list(db.scalars(
        select(DecisionAudit)
        .where(DecisionAudit.decision_type.in_(types), DecisionAudit.context["order_id"].astext == str(order_id))
        .execution_options(populate_existing=True)
    ))


def record_attempt_started(db: Session, order_id: uuid.UUID, attempt_number: int, negotiation_ids: list[str],
                           plan_status: str) -> None:
    """Called by the Planning Agent after each planning run it starts (attempt 1 on intake, attempt 2 on replan)."""
    audit_service.record(
        db, AGENT_PLANNING, DecisionType.PLAN_ATTEMPT_STARTED, {"order_id": str(order_id)},
        {"attempt_number": attempt_number, "negotiation_ids": negotiation_ids, "plan_status": plan_status},
        f"Planning attempt {attempt_number} of {MAX_ATTEMPTS}: plan {plan_status}, {len(negotiation_ids)} negotiations.",
    )


def attempts(db: Session, order_id: uuid.UUID) -> list[dict]:
    """Every attempt of the order with its approval status, whether it can be approved, and its negotiations."""
    records = _records(db, order_id)
    started = {r.decision["attempt_number"]: r for r in records if r.decision_type == DecisionType.PLAN_ATTEMPT_STARTED}
    decided = {r.decision["attempt_number"]: r for r in records if r.decision_type in DECISIONS}
    return [_view(db, order_id, number, started[number], decided.get(number)) for number in sorted(started)]


def current(db: Session, order_id: uuid.UUID) -> dict | None:
    all_attempts = attempts(db, order_id)
    return all_attempts[-1] if all_attempts else None


def _view(db: Session, order_id: uuid.UUID, number: int, started: DecisionAudit, decided: DecisionAudit | None) -> dict:
    sessions = [negotiation_service.get_session_view(db, uuid.UUID(nid)) for nid in started.decision["negotiation_ids"]]
    negotiations = [
        {"negotiation_id": s["id"], "item_id": s["objective"]["item_id"], "session_status": s["status"],
         "outcome": s["outcome"], "agreement": s["agreement"]}
        for s in sessions
    ]
    if decided is not None:
        status = DECISIONS[decided.decision_type]
    elif any(s["status"] in OPEN_SESSION for s in sessions):
        status = PENDING_NEGOTIATION
    else:
        status = AWAITING_APPROVAL
    blockers = _blockers(negotiations) if status == AWAITING_APPROVAL else []
    return {
        "order_id": str(order_id),
        "attempt_number": number,
        "approval_status": status,
        "plan_status": started.decision["plan_status"],
        "approvable": status == AWAITING_APPROVAL and not blockers,
        "blockers": blockers,
        "negotiations": negotiations,
        "attempts_remaining": MAX_ATTEMPTS - number,
        "decision_reason": decided.decision.get("reason") if decided else None,
        "decided_at": decided.created_at if decided else None,
    }


def _blockers(negotiations: list[dict]) -> list[str]:
    """C8 section 3: approvable only if every shortage has a validated, uncommitted agreement (FAILED never is)."""
    return [
        f"item {n['item_id']}: negotiation {n['session_status']} without a validated agreement"
        for n in negotiations
        if not (n["session_status"] == SessionStatus.AGREEMENT_PROPOSED.value and n["agreement"]
                and n["agreement"]["validated"])
    ]


def _decidable(db: Session, order_id: uuid.UUID, attempt_number: int) -> dict:
    latest = current(db, order_id)
    if latest is None:
        raise AppError(ErrorCode.NOT_FOUND, "the order has no planning attempt; hand it to the Planning Agent first")
    if attempt_number != latest["attempt_number"]:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"attempt {attempt_number} is not the current attempt",
                       [{"field": "attempt_number", "issue": f"current attempt is {latest['attempt_number']}"}])
    if latest["approval_status"] != AWAITING_APPROVAL:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"attempt {attempt_number} is {latest['approval_status']}")
    return latest


def _record_decision(db: Session, order_id: uuid.UUID, kind: DecisionType, attempt: dict, reason: str | None,
                     summary: str) -> None:
    audit_service.record(
        db, AGENT_PLANNING, kind, {"order_id": str(order_id)},
        {"attempt_number": attempt["attempt_number"], "decided_by": "HUMAN", "reason": reason,
         "negotiation_ids": [n["negotiation_id"] for n in attempt["negotiations"]],
         "decided_at": datetime.now(timezone.utc)},
        summary,
    )


def approve(db: Session, order_id: uuid.UUID, attempt_number: int) -> dict:
    """Human approval: COMMIT every agreement of the attempt (the agreements become scheduled receipts, P0-12)."""
    attempt = _decidable(db, order_id, attempt_number)
    if not attempt["approvable"]:
        raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, "the plan cannot be approved; reject it to replan",
                       [{"issue": blocker} for blocker in attempt["blockers"]])
    for negotiation in attempt["negotiations"]:
        negotiation_service.send_approval_action(db, uuid.UUID(negotiation["negotiation_id"]), MessageType.COMMIT)
    _record_decision(db, order_id, DecisionType.PLAN_APPROVED, attempt, None,
                     f"Human approved attempt {attempt_number}; {len(attempt['negotiations'])} agreements committed.")
    db.commit()
    return current(db, order_id)


def reject(db: Session, order_id: uuid.UUID, attempt_number: int, reason: str | None = None) -> dict:
    """Human rejection: ABORT the attempt's uncommitted agreements. Attempt < MAX -> REJECTED (the caller replans);
    the last attempt -> HUMAN_INTERVENTION_REQUIRED (no automatic replanning)."""
    attempt = _decidable(db, order_id, attempt_number)
    for negotiation in attempt["negotiations"]:
        if negotiation["session_status"] == SessionStatus.AGREEMENT_PROPOSED.value:
            negotiation_service.send_approval_action(db, uuid.UUID(negotiation["negotiation_id"]), MessageType.ABORT)
    if attempt_number < MAX_ATTEMPTS:
        _record_decision(db, order_id, DecisionType.PLAN_REJECTED, attempt, reason,
                         f"Human rejected attempt {attempt_number}; Planning replans (attempt {attempt_number + 1}).")
    else:
        _record_decision(db, order_id, DecisionType.HUMAN_INTERVENTION_REQUIRED, attempt, reason,
                         f"Human rejected attempt {attempt_number} of {MAX_ATTEMPTS}; automatic replanning stops, "
                         "human intervention required.")
    db.commit()
    return current(db, order_id)
