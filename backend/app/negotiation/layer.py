"""The negotiation layer of the six-agent design (negotiation.md §4, §10.3). Shared infrastructure: it stores
sessions and messages, checks the protocol, and moves messages — it never judges whether terms are acceptable.

Sending side:   `send` puts the message in the outbox inside the sender's own transaction (outbox pattern).
                The outbox worker sends it over A2A (`transport.send`); network failures are retried; a message the
                receiving side refuses is recorded and not retried; "duplicate" counts as delivered.
Receiving side: `receive` (called by the A2A endpoint) checks the message against the session state machine, stores
                the session change and the message (= the receiver's inbox item) and acknowledges at once.
                The inbox worker of the receiving agent then runs that agent's handler.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.work_runner import Registration, WorkItem, enqueue
from app.negotiation import transport
from app.negotiation.envelope import AGENTS, Envelope, Hold, MessageType, ReasonCode, Terms
from app.negotiation.models import Message, Outbox, Session
from app.negotiation.state import ENDED, ProtocolError, SessionState, apply

logger = logging.getLogger(__name__)


def send(db: DbSession, envelope: Envelope) -> None:
    """Queue one message for sending, in the caller's transaction (nothing is committed here)."""
    enqueue(db, Outbox, scope_key=envelope.session_id, kind=envelope.message_type.value,
            message_id=envelope.message_id, receiver=envelope.receiver, envelope=envelope.model_dump(mode="json"))


def new_ids() -> tuple[str, str]:
    """(message_id, session_id) for a new REQUEST."""
    return str(uuid.uuid4()), str(uuid.uuid4())


def reply_to(message: Envelope, kind: MessageType, *, terms: Terms | None = None,
             reason_code: ReasonCode | None = None, hold: Hold | None = None, text: str | None = None) -> Envelope:
    """The answer to `message` in the same session (sender and receiver swapped, new message id)."""
    return Envelope(message_id=str(uuid.uuid4()), session_id=message.session_id, case_id=message.case_id,
                    sender=message.receiver, receiver=message.sender, message_type=kind, terms=terms,
                    reason_code=reason_code, hold=hold, text=text, sent_at=datetime.now(timezone.utc))


def _refusal(code: str, message: str) -> dict:
    return {"accepted": False, "duplicate": False, "error": {"code": code, "message": message}}


def _state(row: Session) -> SessionState:
    return SessionState(str(row.id), row.case_id, row.starter, row.owner, row.status, row.turn, row.round,
                        Terms.model_validate(row.last_offer) if row.last_offer else None, row.accepted,
                        row.commit_requested, Terms.model_validate(row.agreed_terms) if row.agreed_terms else None,
                        row.hold_id)


def receive(db: DbSession, receiver: str, data: object) -> dict:
    """Validate and store one message addressed to `receiver`; returns the acknowledgement (caller commits)."""
    try:
        envelope = Envelope.model_validate(data)
    except ValidationError as error:
        return _refusal("VALIDATION_ERROR", "; ".join(e["msg"] for e in error.errors()))
    if envelope.receiver != receiver:
        return _refusal("VALIDATION_ERROR", f"this endpoint receives {receiver} messages")
    if db.scalar(select(Message.id).where(Message.message_id == envelope.message_id)) is not None:
        return {"accepted": True, "duplicate": True, "session_id": envelope.session_id}
    try:
        session_id = uuid.UUID(envelope.session_id)
    except ValueError:
        return _refusal("VALIDATION_ERROR", "session_id must be a UUID")

    row = db.get(Session, session_id, with_for_update=True)
    try:
        new = apply(_state(row) if row is not None else None, envelope)
    except ProtocolError as error:
        return _refusal(error.code, error.message)

    if row is None:
        terms = envelope.terms
        open_twin = db.scalar(select(Session.id).where(
            Session.case_id == envelope.case_id, Session.resource_type == terms.resource_type.value,
            Session.resource_ref == terms.resource_ref, Session.need_ref.is_not_distinct_from(terms.order_id),
            Session.starter == envelope.sender,
            Session.owner == envelope.receiver, Session.status.in_(("NEGOTIATING", "AGREEMENT_PROPOSED"))))
        if open_twin is not None:  # NG-5: one open negotiation per need and resource
            return _refusal("CONFLICT", f"an open negotiation for this need already exists ({open_twin})")
        row = Session(id=session_id, case_id=envelope.case_id, resource_type=terms.resource_type.value,
                      resource_ref=terms.resource_ref, need_ref=terms.order_id, starter=new.starter, owner=new.owner,
                      status=new.status,
                      turn=new.turn, round=0, accepted=False, commit_requested=False, message_count=0)
        db.add(row)
    row.status, row.turn, row.round = new.status, new.turn, new.round
    row.accepted, row.commit_requested, row.hold_id = new.accepted, new.commit_requested, new.hold_id
    row.last_offer = new.last_offer.model_dump(mode="json") if new.last_offer else None
    row.agreed_terms = new.agreed_terms.model_dump(mode="json") if new.agreed_terms else None
    if envelope.hold is not None:
        row.hold_expires_at = envelope.hold.expires_at
    if envelope.reason_code is not None:
        row.last_reason_code = envelope.reason_code.value
    row.message_count += 1
    if new.status in ENDED:
        row.closed_at = datetime.now(timezone.utc)
    db.flush()
    enqueue(db, Message, scope_key=f"{receiver}:{session_id}", kind=envelope.message_type.value,
            message_id=envelope.message_id, session_id=session_id, sequence_number=row.message_count,
            sender=envelope.sender, receiver=receiver, envelope=envelope.model_dump(mode="json"))
    return {"accepted": True, "duplicate": False, "session_id": str(session_id), "session_status": new.status}


# -- inbox: each agent registers what it does with messages addressed to it -----------------------------------------

InboxHandler = Callable[[DbSession, Envelope, Session], None]  # (db, message, session row) in one transaction
_inbox: dict[str, InboxHandler] = {}


def register_inbox(agent: str, handler: InboxHandler) -> Registration:
    """Register an agent's inbox handler; returns the work-runner registration (short mode) for its inbox."""
    if agent not in AGENTS:
        raise ValueError(f"unknown agent {agent}")
    _inbox[agent] = handler
    return Registration(name=f"negotiation-inbox-{agent.lower()}", model=Message, handler=handle_inbox,
                        mode="short", where=Message.receiver == agent)


def unregister_all() -> None:
    """Tests only."""
    _inbox.clear()


def handle_inbox(db: DbSession, row: Message) -> None:
    handler = _inbox.get(row.receiver)
    if handler is None:
        raise LookupError(f"no inbox handler for {row.receiver}")
    handler(db, Envelope.model_validate(row.envelope), db.get(Session, row.session_id))


# -- outbox: sending over A2A ---------------------------------------------------------------------------------------


def send_outbox_item(session_factory: Callable[[], DbSession], item: WorkItem, renew: Callable[[], None]) -> None:
    """Long-mode handler: one HTTP send. Raises on network failure (retried). A refusal is recorded, not retried."""
    with session_factory() as db:
        row = db.scalar(select(Outbox).where(Outbox.id == item.id))
        envelope, receiver = row.envelope, row.receiver
    ack = transport.send(receiver, envelope)
    if not ack.get("accepted"):
        logger.error("negotiation message %s refused by %s: %s", envelope["message_id"], receiver, ack.get("error"))
        with session_factory() as db:
            row = db.get(Outbox, item.id)
            row.last_error = f"REFUSED: {ack.get('error')}"[:2000]
            db.commit()


def outbox_registration(workers: int = 2) -> Registration:
    return Registration(name="negotiation-outbox", model=Outbox, handler=send_outbox_item, mode="long",
                        workers=workers)
