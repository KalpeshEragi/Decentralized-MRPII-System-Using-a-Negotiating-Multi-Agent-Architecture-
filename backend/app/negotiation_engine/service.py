"""The Negotiation Engine's interface: open a session, append a message (or reword the agent's latest one), read a
session's state, current offer or missed deadline, close or cancel a session.

It keeps protocol state only (sessions, participants, messages, rounds, deadlines) and makes no business decisions:
whether terms are acceptable is always the calling agent's decision. Functions add to the caller's transaction and
never commit.

Rounds: one round = one agent offer or counter-offer + the respondent's reply. The round starts with the offer, so an
OFFER or COUNTER_OFFER from the AGENT raises `round_count`; clarifications, confirmations and replies do not.

Deadlines: the session's `response_deadline` is when the respondent's reply is due. The calling agent sets it at open
and moves it with each message that awaits a reply. The Engine only reports a missed deadline when asked
(`missed_deadline`); there is no scheduler, and closing the session TIMED_OUT is the calling agent's decision.

Statuses: OPEN while negotiating; AGREED, REJECTED, TIMED_OUT or CANCELLED when the calling agent closes the session.
The calling agent may also cancel an AGREED session, or explicitly reopen it (AGREED → OPEN). The Engine records the
status it is told; it never decides it.
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
    "AGENT": ("OFFER", "COUNTER_OFFER", "CLARIFICATION_REQUEST", "CANCEL", "CONFIRMATION"),
    "SUPPLIER": ("ACCEPT", "COUNTER_OFFER", "REJECT", "UNCLEAR"),
}
ROUND_OPENING_TYPES = ("OFFER", "COUNTER_OFFER")  # when sent by the AGENT
END_STATUSES = ("AGREED", "REJECTED", "TIMED_OUT", "CANCELLED")
CANCELLABLE = ("OPEN", "AGREED")  # an agreement isn't final until the calling agent commits it


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
    causation_id: uuid.UUID | None = None, response_deadline: datetime | None = None,
) -> bool:
    """Add a message to an OPEN session, or the agent's CANCEL to a CANCELLABLE one. Returns False (and changes nothing) when `message_id` was already stored in
    this session. `message_id` is unique across all sessions (schema §8): reusing it in another session is a conflict.
    `response_deadline`, when given, is when the reply to this message is due: it replaces the session's deadline."""
    session = _session(db, session_id, lock=True)  # one message at a time per session
    stored_in = db.scalar(select(NegotiationMessage.session_id).where(NegotiationMessage.message_id == message_id))
    if stored_in == session_id:
        return False
    if stored_in is not None:
        raise AppError(ErrorCode.CONFLICT, "message_id is already used in another negotiation session",
                       [{"field": "message_id", "issue": "already used"}])
    if session.status != "OPEN" and not (message_type == "CANCEL" and session.status in CANCELLABLE):
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
    if response_deadline is not None:
        session.response_deadline = response_deadline
    last_sequence = db.scalar(
        select(func.max(NegotiationMessage.sequence_number)).where(NegotiationMessage.session_id == session_id))
    db.add(NegotiationMessage(
        session_id=session_id, message_id=message_id, sequence_number=(last_sequence or 0) + 1,
        round_number=session.round_count, sender_type=sender_type, sender_ref=sender_ref, message_type=message_type,
        text=text, terms=terms, interpretation_source=interpretation_source, causation_id=causation_id,
    ))
    db.flush()
    return True


def message_session(db: Session, message_id: uuid.UUID) -> uuid.UUID | None:
    """The session `message_id` is stored in, if any. A read without locks, e.g. to skip a duplicate delivery early;
    `append_message` checks again when it stores."""
    return db.scalar(select(NegotiationMessage.session_id).where(NegotiationMessage.message_id == message_id))


REWORDABLE_TYPES = ("OFFER", "COUNTER_OFFER", "CLARIFICATION_REQUEST")  # the agent's messages awaiting a reply


def latest_message_id(db: Session, session_id: uuid.UUID) -> uuid.UUID | None:
    """The session's latest message, e.g. the one a cancellation cancels."""
    return db.scalar(select(NegotiationMessage.message_id).where(NegotiationMessage.session_id == session_id)
                     .order_by(NegotiationMessage.sequence_number.desc()).limit(1))


def awaited_message_id(db: Session, session_id: uuid.UUID) -> uuid.UUID | None:
    """The agent's latest message awaiting a reply (offer, counter-offer or clarification request): what the
    respondent's next reply answers."""
    return db.scalar(select(NegotiationMessage.message_id).where(
        NegotiationMessage.session_id == session_id, NegotiationMessage.sender_type == "AGENT",
        NegotiationMessage.message_type.in_(REWORDABLE_TYPES),
    ).order_by(NegotiationMessage.sequence_number.desc()).limit(1))


def reword_message(db: Session, session_id: uuid.UUID, message_id: uuid.UUID, text: str) -> bool:
    """Replace the text of the agent's message awaiting a reply, only while it is still the session's latest message
    and the session is OPEN (nobody has answered it or acted since). Terms, type and sequence never change. Returns
    whether the text was replaced."""
    session = _session(db, session_id, lock=True)
    latest = db.scalar(select(NegotiationMessage).where(NegotiationMessage.session_id == session_id)
                       .order_by(NegotiationMessage.sequence_number.desc()).limit(1))
    if (session.status != "OPEN" or latest is None or latest.message_id != message_id
            or latest.sender_type != "AGENT" or latest.message_type not in REWORDABLE_TYPES):
        return False
    latest.text = text
    db.flush()
    return True


@dataclass(frozen=True)
class SessionState:
    status: str
    round_count: int
    max_rounds: int

    @property
    def rounds_left(self) -> int:
        return self.max_rounds - self.round_count


@dataclass(frozen=True)
class Offer:
    """The agent's latest OFFER or COUNTER_OFFER: the terms the respondent is answering."""

    message_id: uuid.UUID
    terms: dict


def _session(db: Session, session_id: uuid.UUID, lock: bool = False) -> NegotiationSession:
    session = db.get(NegotiationSession, session_id, with_for_update=lock)
    if session is None:
        raise AppError(ErrorCode.NOT_FOUND, "negotiation session not found")
    return session


def session_state(db: Session, session_id: uuid.UUID) -> SessionState:
    session = _session(db, session_id)
    return SessionState(session.status, session.round_count, session.max_rounds)


def current_offer(db: Session, session_id: uuid.UUID) -> Offer | None:
    message = db.scalar(select(NegotiationMessage).where(
        NegotiationMessage.session_id == session_id, NegotiationMessage.sender_type == "AGENT",
        NegotiationMessage.message_type.in_(ROUND_OPENING_TYPES),
    ).order_by(NegotiationMessage.sequence_number.desc()).limit(1))
    return Offer(message.message_id, message.terms) if message else None


def clarifications_since_offer(db: Session, session_id: uuid.UUID) -> int:
    """The agent's CLARIFICATION_REQUESTs sent after its current offer."""
    offer = select(func.max(NegotiationMessage.sequence_number)).where(
        NegotiationMessage.session_id == session_id, NegotiationMessage.sender_type == "AGENT",
        NegotiationMessage.message_type.in_(ROUND_OPENING_TYPES)).scalar_subquery()
    return db.scalar(select(func.count()).select_from(NegotiationMessage).where(
        NegotiationMessage.session_id == session_id, NegotiationMessage.sender_type == "AGENT",
        NegotiationMessage.message_type == "CLARIFICATION_REQUEST",
        NegotiationMessage.sequence_number > func.coalesce(offer, 0)))


def missed_deadline(db: Session, session_id: uuid.UUID, now: datetime) -> datetime | None:
    """The session's response deadline if the session is OPEN and `now` is past it; else None. Read from the database,
    not the session cache, so a reply committed meanwhile is seen."""
    row = db.execute(select(NegotiationSession.status, NegotiationSession.response_deadline)
                     .where(NegotiationSession.id == session_id)).one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "negotiation session not found")
    status, deadline = row
    return deadline if status == "OPEN" and deadline is not None and now > deadline else None


def respondent_counter_offers(db: Session, session_id: uuid.UUID) -> list[Offer]:
    """The respondent's counter-offers in this session, oldest first, with the terms as interpreted when stored."""
    rows = db.scalars(select(NegotiationMessage).where(
        NegotiationMessage.session_id == session_id, NegotiationMessage.sender_type != "AGENT",
        NegotiationMessage.message_type == "COUNTER_OFFER",
    ).order_by(NegotiationMessage.sequence_number))
    return [Offer(m.message_id, m.terms) for m in rows]


def close_session(db: Session, session_id: uuid.UUID, status: str, reason: str | None, now: datetime) -> None:
    """End an OPEN session with the status the calling agent decided."""
    if status not in END_STATUSES:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{status} is not an end status")
    _end(db, session_id, ("OPEN",), status, reason, now)


def cancel_session(db: Session, session_id: uuid.UUID, reason: str, now: datetime) -> None:
    """The calling agent cancels an OPEN or AGREED session. Ended sessions (REJECTED, TIMED_OUT, CANCELLED) stay."""
    _end(db, session_id, CANCELLABLE, "CANCELLED", reason, now)


def reopen_session(db: Session, session_id: uuid.UUID) -> None:
    """AGREED → OPEN, only when the calling agent explicitly reopens an agreement it has not committed (e.g. to revise
    the terms). No other ended session can be reopened."""
    session = _session(db, session_id, lock=True)
    if session.status != "AGREED":
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"negotiation session is {session.status}, not AGREED")
    session.status, session.status_reason, session.completed_at = "OPEN", None, None
    db.flush()


def _end(db: Session, session_id: uuid.UUID, allowed_from: tuple[str, ...], status: str, reason: str | None,
         now: datetime) -> None:
    session = _session(db, session_id, lock=True)
    if session.status not in allowed_from:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"negotiation session is {session.status}")
    session.status, session.status_reason, session.completed_at = status, reason, now
    db.flush()


def session_view(db: Session, session_id: uuid.UUID) -> dict:
    session = _session(db, session_id)
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
