"""Negotiation persistence around the Phase 1 in-memory protocol.

The protocol (`app.negotiation.session.NegotiationSession`) stays the only place that decides whether a message is
valid. This service rebuilds a session by replaying its stored messages, submits the new message to it and, if the
protocol accepts, stores the message, offers, agreement, status and audit records in one transaction. It makes no
business decisions: agents (Phase 3) and the supplier form choose the messages.

Working values still open in C4 / C7 (flagged in docs): negotiation_type, participant roles, offer statuses.
"""

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.mrpii.agreement import check_agreement
from app.negotiation.protocol import ProtocolError, ProtocolErrorCode
from app.negotiation.session import NegotiationSession
from app.models import negotiation as db_models
from app.schemas.domain import ScheduledReceipt, Shortage
from app.schemas.negotiation import (
    END_STATUSES,
    AgentRef,
    AgentType,
    MessagePayload,
    MessageType,
    NegotiationMessage,
    OfferTerms,
    SessionStatus,
)
from app.services import audit_service
from app.services.audit_service import AGENT_INVENTORY, AGENT_PURCHASING, DecisionType

NEGOTIATION_TYPE = "SHORTAGE_PROCUREMENT"
ROLE_INITIATOR = "INITIATOR"
ROLE_RESPONDER = "RESPONDER"
SUPPLIER_INTERFACE_ID = "supplier-interface"  # not an agent: no agent.agents row
APPROVAL_WORKFLOW_ID = "approval-workflow"  # not an agent: sends COMMIT after human approval (C8, later)

OFFER_PROPOSED, OFFER_SUPERSEDED, OFFER_ACCEPTED, OFFER_REJECTED = "PROPOSED", "SUPERSEDED", "ACCEPTED", "REJECTED"

_PROTOCOL_TO_APP = {
    ProtocolErrorCode.INVALID_MESSAGE: ErrorCode.VALIDATION_ERROR,
    ProtocolErrorCode.WRONG_SESSION: ErrorCode.VALIDATION_ERROR,
    ProtocolErrorCode.UNKNOWN_PARTICIPANT: ErrorCode.VALIDATION_ERROR,
    ProtocolErrorCode.DUPLICATE_MESSAGE: ErrorCode.CONFLICT,
    ProtocolErrorCode.INVALID_SEQUENCE: ErrorCode.INVALID_STATE_TRANSITION,
    ProtocolErrorCode.INVALID_STATE_TRANSITION: ErrorCode.INVALID_STATE_TRANSITION,
    ProtocolErrorCode.SESSION_ENDED: ErrorCode.INVALID_STATE_TRANSITION,
    ProtocolErrorCode.TERMS_MISMATCH: ErrorCode.BUSINESS_RULE_VIOLATION,
}


def _midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{field} must be a UUID", [{"field": field, "issue": "not a UUID"}]) from exc


def _agent_ids(db: Session) -> dict[AgentType, str]:
    return {
        AgentType.INVENTORY: str(audit_service.agent_uuid(db, AGENT_INVENTORY)),
        AgentType.PURCHASING: str(audit_service.agent_uuid(db, AGENT_PURCHASING)),
        AgentType.SUPPLIER_INTERFACE: SUPPLIER_INTERFACE_ID,
        AgentType.APPROVAL_WORKFLOW: APPROVAL_WORKFLOW_ID,
    }


# -- opening a session -------------------------------------------------------------------------------------------


def open_session(db: Session, order_id: uuid.UUID, item_id: uuid.UUID) -> dict:
    """Create the session for a persisted shortage (Inventory is the initiator). No message is sent yet.
    One active session per shortage; a new one is allowed once the previous one has ended (replanning, C8)."""
    from app.services import planning_service  # local import: planning_service reads receipts from this module

    plan = planning_service.get_plan(db, order_id)
    shortage = next((s for s in plan.shortages if s.item_id == str(item_id)), None)
    if shortage is None:
        raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, "the order has no shortage for this item")
    ended = [status.value for status in END_STATUSES]
    active = select(db_models.NegotiationSession.objective).where(db_models.NegotiationSession.status.not_in(ended))
    for objective in db.scalars(active):
        if objective.get("mps_entry_id") == shortage.mps_entry_id and objective.get("item_id") == shortage.item_id:
            raise AppError(ErrorCode.CONFLICT, "an active negotiation session already exists for this shortage")

    ids = _agent_ids(db)
    now = _now()
    session = db_models.NegotiationSession(
        id=uuid.uuid4(),
        negotiation_type=NEGOTIATION_TYPE,
        initiator_agent_id=uuid.UUID(ids[AgentType.INVENTORY]),
        status=SessionStatus.INITIATED.value,
        objective=audit_service.jsonable(shortage),
        started_at=now,
        deadline=_midnight_utc(shortage.required_by),
    )
    db.add(session)
    db.flush()
    for agent_type, role in ((AgentType.INVENTORY, ROLE_INITIATOR), (AgentType.PURCHASING, ROLE_RESPONDER)):
        db.add(
            db_models.NegotiationParticipant(
                negotiation_id=session.id, agent_id=uuid.UUID(ids[agent_type]), role=role, joined_at=now
            )
        )
    db.commit()
    return get_session_view(db, session.id)


# -- replay ------------------------------------------------------------------------------------------------------


def _row_to_message(row: db_models.NegotiationMessage, ids: dict[AgentType, str]) -> NegotiationMessage:
    def ref(agent_type: str, agent_id: uuid.UUID | None) -> AgentRef:
        kind = AgentType(agent_type)
        return AgentRef(agent_id=str(agent_id) if agent_id else ids[kind], agent_type=kind)

    return NegotiationMessage(
        message_id=str(row.message_id),
        negotiation_id=str(row.negotiation_id),
        sender=ref(row.sender_type, row.sender_agent_id),
        receiver=ref(row.receiver_type, row.receiver_agent_id),
        message_type=MessageType(row.message_type),
        sequence_number=row.sequence_number,
        timestamp=row.created_at,
        correlation_id=str(row.correlation_id) if row.correlation_id else None,
        payload=MessagePayload.model_validate(row.payload or {}),
    )


def _load(
    db: Session, negotiation_id: uuid.UUID, lock: bool = False
) -> tuple[db_models.NegotiationSession, NegotiationSession]:
    """The session row and the in-memory protocol session rebuilt from its stored messages (lock: row lock for writes)."""
    row = db.get(db_models.NegotiationSession, negotiation_id, with_for_update=lock)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "negotiation not found")
    ids = _agent_ids(db)
    session = NegotiationSession(
        str(negotiation_id),
        ids[AgentType.INVENTORY],
        ids[AgentType.PURCHASING],
        SUPPLIER_INTERFACE_ID,
        APPROVAL_WORKFLOW_ID,
    )
    stored = db.scalars(
        select(db_models.NegotiationMessage)
        .where(db_models.NegotiationMessage.negotiation_id == negotiation_id)
        .order_by(db_models.NegotiationMessage.sequence_number)
    )
    for message_row in stored:
        session.submit(_row_to_message(message_row, ids))
    return row, session


# -- submitting messages -----------------------------------------------------------------------------------------


def submit_message(db: Session, negotiation_id: uuid.UUID, message: NegotiationMessage) -> dict:
    """Validate `message` with the protocol and persist it. Refused messages change nothing."""
    _uuid(message.message_id, "message_id")
    if message.correlation_id:
        _uuid(message.correlation_id, "correlation_id")
    if message.negotiation_id != str(negotiation_id):
        raise AppError(ErrorCode.VALIDATION_ERROR, "message negotiation_id does not match the session")

    row, session = _load(db, negotiation_id, lock=True)
    objective = Shortage.model_validate(row.objective)
    terms = message.payload.terms
    kind = message.message_type

    try:
        status = session.submit(message)
    except ProtocolError as exc:
        raise AppError(_PROTOCOL_TO_APP[exc.code], exc.message, [{"issue": exc.code.value}]) from exc

    # Deterministic validation is the authority on feasibility (C4 section 8); it runs on the accepted message.
    agreement_problems = check_agreement(terms, objective) if kind == MessageType.AGREEMENT_PROPOSED else []
    if kind == MessageType.COMMIT:
        agreement = _agreement(db, negotiation_id)
        if agreement is None or not agreement.validated:
            raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, "only a validated agreement can be committed")

    def db_agent(ref: AgentRef) -> uuid.UUID | None:
        return uuid.UUID(ref.agent_id) if ref.agent_type in (AgentType.INVENTORY, AgentType.PURCHASING) else None

    message_row = db_models.NegotiationMessage(
        negotiation_id=negotiation_id,
        message_id=uuid.UUID(message.message_id),
        sender_type=message.sender.agent_type.value,
        sender_agent_id=db_agent(message.sender),
        receiver_type=message.receiver.agent_type.value,
        receiver_agent_id=db_agent(message.receiver),
        message_type=kind.value,
        sequence_number=message.sequence_number,
        correlation_id=uuid.UUID(message.correlation_id) if message.correlation_id else None,
        payload=audit_service.jsonable(message.payload),
        created_at=message.timestamp,
    )
    db.add(message_row)
    db.flush()

    context = {"order_id": objective.order_id, "item_id": objective.item_id, "negotiation_id": str(negotiation_id)}
    _record_offers(db, negotiation_id, message, message_row.id, status)
    _record_audit(db, message, context, session, status, agreement_problems)

    if kind == MessageType.AGREEMENT_PROPOSED:
        db.add(
            db_models.NegotiationAgreement(
                negotiation_id=negotiation_id,
                agreed_terms=audit_service.jsonable(terms),
                validated=not agreement_problems,
                committed=False,
            )
        )
    if kind == MessageType.COMMIT:
        db.execute(
            update(db_models.NegotiationAgreement)
            .where(db_models.NegotiationAgreement.negotiation_id == negotiation_id)
            .values(committed=True)
        )
    row.status = status.value
    if session.is_ended:
        row.completed_at = _now()
    db.commit()
    return get_session_view(db, negotiation_id)


def _record_offers(db: Session, negotiation_id: uuid.UUID, message: NegotiationMessage, message_row_id: uuid.UUID, status: SessionStatus) -> None:
    """offers table: every OFFER / COUNTER_OFFER that opens or answers a round. A Purchasing counter that trips the
    round limit is stored as a message only; no round (and no offer) is opened."""
    offers = db_models.NegotiationOffer
    open_offers = (offers.negotiation_id == negotiation_id) & (offers.status == OFFER_PROPOSED)
    kind = message.message_type
    if kind in (MessageType.OFFER, MessageType.COUNTER_OFFER) and status != SessionStatus.FAILED:
        db.execute(update(offers).where(open_offers).values(status=OFFER_SUPERSEDED))
        count = db.scalar(select(func.count()).select_from(offers).where(offers.negotiation_id == negotiation_id)) or 0
        db.add(
            offers(
                negotiation_id=negotiation_id,
                message_id=message_row_id,
                offer_number=count + 1,
                offer_type=kind.value,
                terms=audit_service.jsonable(message.payload.terms),
                valid_until=None,
                status=OFFER_PROPOSED,
            )
        )
    elif kind == MessageType.AGREEMENT_PROPOSED:
        db.execute(update(offers).where(open_offers).values(status=OFFER_ACCEPTED))
    elif kind == MessageType.REJECT:
        db.execute(update(offers).where(open_offers).values(status=OFFER_REJECTED))
    elif status == SessionStatus.FAILED:
        db.execute(update(offers).where(open_offers).values(status=OFFER_SUPERSEDED))


def _record_audit(db: Session, message: NegotiationMessage, context: dict, session: NegotiationSession, status: SessionStatus, problems: list[str]) -> None:
    """C7: agent decisions only. Supplier-interface responses (except REJECT, which ends the session) are protocol facts
    in negotiation.* and are not audited here; the approval workflow's COMMIT is recorded under Inventory."""
    kind, sender, terms = message.message_type, message.sender.agent_type, message.payload.terms
    if kind == MessageType.REQUEST:
        audit_service.record(db, AGENT_INVENTORY, DecisionType.NEGOTIATION_REQUEST, context, {"terms": terms},
                             "Inventory opened procurement negotiation with Purchasing for a detected shortage.")
    elif status == SessionStatus.FAILED:
        audit_service.record(db, AGENT_PURCHASING, DecisionType.NEGOTIATION_FAILED, context,
                             {"rounds": session.round_number, "outcome": "FAILED"},
                             "Round limit reached without an acceptable agreement; the shortage stays unresolved.")
    elif kind in (MessageType.OFFER, MessageType.COUNTER_OFFER) and sender == AgentType.PURCHASING:
        audit_service.record(db, AGENT_PURCHASING, DecisionType.NEGOTIATION_MESSAGE, context,
                             {"message_type": kind, "round": session.round_number, "terms": terms},
                             f"Purchasing sent {kind.value} in round {session.round_number} of 3.")
    elif kind == MessageType.AGREEMENT_PROPOSED:
        audit_service.record(db, AGENT_PURCHASING, DecisionType.AGREEMENT_PROPOSED, context,
                             {"terms": terms, "validated": not problems, "problems": problems},
                             "Purchasing proposed an agreement." + (" Deterministic validation failed." if problems else ""))
    elif kind == MessageType.REJECT:
        audit_service.record(db, AGENT_PURCHASING, DecisionType.NEGOTIATION_REJECTED, context,
                             {"rejected_by": sender, "rounds": session.round_number, "outcome": "FAILED"},
                             f"Negotiation rejected by {sender.value}; reported to Planning as FAILED.")
    elif kind == MessageType.COMMIT:
        audit_service.record(db, AGENT_INVENTORY, DecisionType.AGREEMENT_COMMITTED, context, {"committed": True},
                             "Agreement committed by the approval workflow.")
    elif kind == MessageType.ABORT:
        audit_service.record(db, AGENT_INVENTORY, DecisionType.AGREEMENT_ABORTED, context, {"committed": False},
                             "Uncommitted agreement closed by the approval workflow after the plan was rejected.")


def send_approval_action(db: Session, negotiation_id: uuid.UUID, kind: MessageType) -> dict:
    """COMMIT or ABORT from the approval workflow (C8), sent to Inventory, the session initiator. Only the approval
    service calls this, after the human's decision; the protocol accepts both only from AGREEMENT_PROPOSED."""
    if kind not in (MessageType.COMMIT, MessageType.ABORT):
        raise AppError(ErrorCode.VALIDATION_ERROR, "the approval workflow sends only COMMIT or ABORT")
    _, session = _load(db, negotiation_id)
    ids = _agent_ids(db)
    message = NegotiationMessage(
        message_id=str(uuid.uuid4()),
        negotiation_id=str(negotiation_id),
        sender=AgentRef(agent_id=APPROVAL_WORKFLOW_ID, agent_type=AgentType.APPROVAL_WORKFLOW),
        receiver=AgentRef(agent_id=ids[AgentType.INVENTORY], agent_type=AgentType.INVENTORY),
        message_type=kind,
        sequence_number=len(session.messages) + 1,
        timestamp=_now(),
    )
    return submit_message(db, negotiation_id, message)


def build_supplier_message(
    db: Session,
    negotiation_id: uuid.UUID,
    round_number: int,
    response_type: MessageType,
    quantity: Decimal | None = None,
    delivery_date: date | None = None,
    note: str | None = None,
) -> NegotiationMessage:
    """The supplier form as a C4 message from SUPPLIER_INTERFACE: one response for the current round (C4 section 7,
    C5 INVALID_STATE_TRANSITION rules). Nothing is stored here."""
    if response_type not in (MessageType.ACCEPT, MessageType.COUNTER_OFFER, MessageType.REJECT):
        raise AppError(ErrorCode.VALIDATION_ERROR, "a supplier response is ACCEPT, COUNTER_OFFER or REJECT")
    row, session = _load(db, negotiation_id)
    if session.is_ended:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION, f"the negotiation is {row.status}")
    if not session.awaiting_supplier or round_number != session.round_number:
        raise AppError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"no supplier response is expected for round {round_number}",
            [{"field": "round_number", "issue": f"current round is {session.round_number}"}],
        )
    terms = None
    if response_type == MessageType.COUNTER_OFFER:
        if quantity is None or delivery_date is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "a counter offer needs quantity and delivery_date")
        terms = OfferTerms(quantity=quantity, delivery_date=delivery_date)
    return NegotiationMessage(
        message_id=str(uuid.uuid4()),
        negotiation_id=str(negotiation_id),
        sender=AgentRef(agent_id=SUPPLIER_INTERFACE_ID, agent_type=AgentType.SUPPLIER_INTERFACE),
        receiver=AgentRef(agent_id=_agent_ids(db)[AgentType.PURCHASING], agent_type=AgentType.PURCHASING),
        message_type=response_type,
        sequence_number=len(session.messages) + 1,
        timestamp=_now(),
        payload=MessagePayload(terms=terms, message=note),
    )


def submit_supplier_response(
    db: Session,
    negotiation_id: uuid.UUID,
    round_number: int,
    response_type: MessageType,
    quantity: Decimal | None = None,
    delivery_date: date | None = None,
    note: str | None = None,
) -> dict:
    """Store a supplier-form response directly (Phase 2 path; no agent reacts). The agent-driven path is
    `supplier_interface_service.respond`, which delivers the same message to the Purchasing Agent over A2A."""
    message = build_supplier_message(db, negotiation_id, round_number, response_type, quantity, delivery_date, note)
    return submit_message(db, negotiation_id, message)


# -- reads -------------------------------------------------------------------------------------------------------


def _agreement(db: Session, negotiation_id: uuid.UUID) -> db_models.NegotiationAgreement | None:
    return db.scalars(
        select(db_models.NegotiationAgreement)
        .where(db_models.NegotiationAgreement.negotiation_id == negotiation_id)
        .order_by(db_models.NegotiationAgreement.created_at.desc())
    ).first()


def get_session_view(db: Session, negotiation_id: uuid.UUID) -> dict:
    row, session = _load(db, negotiation_id)
    offers = db.scalars(
        select(db_models.NegotiationOffer)
        .where(db_models.NegotiationOffer.negotiation_id == negotiation_id)
        .order_by(db_models.NegotiationOffer.offer_number)
    )
    agreement = _agreement(db, negotiation_id)
    return {
        "id": str(row.id),
        "negotiation_type": row.negotiation_type,
        "status": row.status,
        "round_number": session.round_number,
        "max_rounds": 3,
        "awaiting_supplier": session.awaiting_supplier,
        "outcome": session.outcome,  # what Planning receives: AGREEMENT, or FAILED for REJECTED / FAILED
        "participants": {kind.value: agent_id for kind, agent_id in _agent_ids(db).items()},  # ids to put in envelopes
        "objective": row.objective,
        "started_at": row.started_at,
        "deadline": row.deadline,
        "completed_at": row.completed_at,
        "messages": [
            {
                "message_id": m.message_id,
                "sequence_number": m.sequence_number,
                "message_type": m.message_type.value,
                "sender": m.sender.agent_type.value,
                "receiver": m.receiver.agent_type.value,
                "payload": m.payload.model_dump(mode="json"),
                "timestamp": m.timestamp,
            }
            for m in session.messages
        ],
        "offers": [
            {"offer_number": o.offer_number, "offer_type": o.offer_type, "terms": o.terms, "status": o.status}
            for o in offers
        ],
        "agreement": None
        if agreement is None
        else {
            "id": str(agreement.id),
            "agreed_terms": agreement.agreed_terms,
            "validated": agreement.validated,
            "committed": agreement.committed,
        },
    }


def sessions_for_order(db: Session, order_id: uuid.UUID) -> list[dict]:
    """Views of every session opened for the order's shortages, oldest first."""
    ids = db.scalars(
        select(db_models.NegotiationSession.id)
        .where(db_models.NegotiationSession.objective["order_id"].astext == str(order_id))
        .order_by(db_models.NegotiationSession.started_at, db_models.NegotiationSession.id)
    )
    return [get_session_view(db, negotiation_id) for negotiation_id in list(ids)]


def scheduled_receipts(db: Session, item_ids: set[str]) -> list[ScheduledReceipt]:
    """Committed agreements are the scheduled receipts (P0-12). Uncommitted agreements never count."""
    rows = db.execute(
        select(db_models.NegotiationAgreement, db_models.NegotiationSession.objective)
        .join(db_models.NegotiationSession, db_models.NegotiationSession.id == db_models.NegotiationAgreement.negotiation_id)
        .where(db_models.NegotiationAgreement.committed.is_(True))
    )
    receipts = []
    for agreement, objective in rows:
        if objective["item_id"] in item_ids:
            terms = OfferTerms.model_validate(agreement.agreed_terms)
            receipts.append(
                ScheduledReceipt(
                    item_id=objective["item_id"],
                    quantity=terms.quantity,
                    expected_date=terms.delivery_date,
                    source_ref=str(agreement.id),
                )
            )
    return receipts
