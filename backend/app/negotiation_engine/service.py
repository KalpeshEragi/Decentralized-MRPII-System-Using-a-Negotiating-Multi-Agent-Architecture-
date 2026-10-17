"""The Negotiation Engine's interface: open a session, append a message, read a session.

It keeps protocol state only (sessions, participants, messages, rounds, deadlines) and makes no business decisions:
whether terms are acceptable is always the calling agent's decision. Functions add to the caller's transaction and
never commit.

Rounds: one round = one agent offer or counter-offer + the respondent's reply. The round starts with the offer, so an
OFFER or COUNTER_OFFER from the AGENT raises `round_count`; clarifications and replies do not.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text as sql
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.negotiation_engine.models import (
    NegotiationEngineBase, NegotiationMessage, NegotiationParticipant, NegotiationSession,
)
from app.supplier_service import service as supplier_service

SESSION_TYPES = ("PURCHASING_SUPPLIER",)
KNOWN_AGENTS = ("PURCHASING",)  # agent codes allowed as AGENT participants
MESSAGE_TYPES = {
    "AGENT": ("OFFER", "COUNTER_OFFER", "CLARIFICATION_REQUEST", "CANCEL"),
    "SUPPLIER": ("ACCEPT", "COUNTER_OFFER", "REJECT", "UNCLEAR"),
}
ROUND_OPENING_TYPES = ("OFFER", "COUNTER_OFFER")  # when sent by the AGENT


@dataclass(frozen=True)
class Participant:
    participant_type: str  # AGENT, SUPPLIER
    participant_ref: str
    role: str  # INITIATOR, RESPONDENT


def _check_participant(db: Session, participant: Participant) -> None:
    """References are logical (no foreign key): check that each points at something that exists."""
    if participant.participant_type == "AGENT":
        known = participant.participant_ref in KNOWN_AGENTS
    elif participant.participant_type == "SUPPLIER":
        try:
            known = supplier_service.get_supplier(db, uuid.UUID(participant.participant_ref)) is not None
        except ValueError:
            known = False
    else:
        known = False
    if not known:
        raise AppError(ErrorCode.VALIDATION_ERROR, "unknown negotiation participant", [
            {"field": "participant_ref", "issue": f"{participant.participant_type} {participant.participant_ref} does not exist"}])


def open_session(
    db: Session, *, session_type: str, correlation_id: uuid.UUID, objective: dict, participants: list[Participant],
    max_rounds: int, response_deadline: datetime | None, now: datetime,
) -> uuid.UUID:
    if session_type not in SESSION_TYPES:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"unknown session type {session_type}")
    for participant in participants:
        _check_participant(db, participant)
    session = NegotiationSession(
        id=uuid.uuid4(), session_type=session_type, status="OPEN", correlation_id=correlation_id, objective=objective,
        round_count=0, max_rounds=max_rounds, response_deadline=response_deadline, started_at=now,
    )
    db.add(session)
    db.flush()
    db.add_all(NegotiationParticipant(session_id=session.id, joined_at=now, **vars(p)) for p in participants)
    db.flush()
    return session.id


def append_message(
    db: Session, session_id: uuid.UUID, *, message_id: uuid.UUID, sender_type: str, sender_ref: str,
    message_type: str, text: str, terms: dict | None = None, interpretation_source: str | None = None,
    causation_id: uuid.UUID | None = None,
) -> bool:
    """Add a message to an OPEN session. Returns False (and changes nothing) when `message_id` was already stored.
    `message_id` is unique across all sessions (schema §8)."""
    session = db.get(NegotiationSession, session_id, with_for_update=True)  # one message at a time per session
    if session is None:
        raise AppError(ErrorCode.NOT_FOUND, "negotiation session not found")
    if db.scalar(select(NegotiationMessage.id).where(NegotiationMessage.message_id == message_id)) is not None:
        return False
    if session.status != "OPEN":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"negotiation session is {session.status}")
    if message_type not in MESSAGE_TYPES.get(sender_type, ()):
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{sender_type} cannot send {message_type}")
    is_participant = db.scalar(select(NegotiationParticipant.id).where(
        NegotiationParticipant.session_id == session_id, NegotiationParticipant.participant_type == sender_type,
        NegotiationParticipant.participant_ref == sender_ref))
    if is_participant is None:
        raise AppError(ErrorCode.FORBIDDEN, "the sender is not a participant of this session")

    if sender_type == "AGENT" and message_type in ROUND_OPENING_TYPES:
        if session.round_count >= session.max_rounds:
            raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, "the round limit of this session is reached")
        session.round_count += 1
    last_sequence = db.scalar(
        select(func.max(NegotiationMessage.sequence_number)).where(NegotiationMessage.session_id == session_id))
    db.add(NegotiationMessage(
        session_id=session_id, message_id=message_id, sequence_number=(last_sequence or 0) + 1,
        round_number=session.round_count, sender_type=sender_type, sender_ref=sender_ref, message_type=message_type,
        text=text, terms=terms, interpretation_source=interpretation_source, causation_id=causation_id,
    ))
    db.flush()
    return True


def session_view(db: Session, session_id: uuid.UUID) -> dict:
    session = db.get(NegotiationSession, session_id)
    if session is None:
        raise AppError(ErrorCode.NOT_FOUND, "negotiation session not found")
    participants = db.scalars(select(NegotiationParticipant).where(NegotiationParticipant.session_id == session_id)
                              .order_by(NegotiationParticipant.role))
    messages = db.scalars(select(NegotiationMessage).where(NegotiationMessage.session_id == session_id)
                          .order_by(NegotiationMessage.sequence_number))
    return {
        "session_id": str(session.id),
        "session_type": session.session_type,
        "status": session.status,
        "status_reason": session.status_reason,
        "objective": session.objective,
        "round_count": session.round_count,
        "max_rounds": session.max_rounds,
        "response_deadline": session.response_deadline.isoformat() if session.response_deadline else None,
        "participants": [
            {"participant_type": p.participant_type, "participant_ref": p.participant_ref, "role": p.role}
            for p in participants
        ],
        "messages": [
            {
                "message_id": str(m.message_id), "sequence_number": m.sequence_number, "round_number": m.round_number,
                "sender_type": m.sender_type, "sender_ref": m.sender_ref, "message_type": m.message_type,
                "text": m.text, "terms": m.terms, "interpretation_source": m.interpretation_source,
                "causation_id": str(m.causation_id) if m.causation_id else None,
            }
            for m in messages
        ],
    }


def reset(db: Session) -> None:
    """Empty the Engine tables (test/demo reset only). The caller commits."""
    tables = ", ".join(f'"{t.schema}"."{t.name}"' for t in NegotiationEngineBase.metadata.sorted_tables)
    db.execute(sql(f"TRUNCATE {tables} CASCADE"))
