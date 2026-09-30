"""negotiation schema.

Message sender/receiver are stored as a type plus a nullable agent id (P1-07 decision): the supplier interface and
the approval workflow are not agents, so they have no agent.agents row.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk

SESSION_FK = "negotiation.negotiation_sessions.id"


class NegotiationSession(Base):
    __tablename__ = "negotiation_sessions"
    __table_args__ = {"schema": "negotiation"}

    id: Mapped[uuid.UUID] = uuid_pk()
    negotiation_type: Mapped[str] = mapped_column(String, nullable=False)
    initiator_agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.agents.id"))
    status: Mapped[str] = mapped_column(String, nullable=False)  # C4 session status
    objective: Mapped[dict] = mapped_column(JSONB, nullable=False)  # C1 Shortage
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # shortage required_by (P1-04)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # only at an end status (P0-04)


class NegotiationParticipant(Base):
    __tablename__ = "negotiation_participants"
    __table_args__ = {"schema": "negotiation"}

    id: Mapped[uuid.UUID] = uuid_pk()
    negotiation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(SESSION_FK))
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.agents.id"))
    role: Mapped[str] = mapped_column(String, nullable=False)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NegotiationMessage(Base):
    __tablename__ = "negotiation_messages"
    __table_args__ = {"schema": "negotiation"}

    id: Mapped[uuid.UUID] = uuid_pk()
    negotiation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(SESSION_FK))
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    sender_type: Mapped[str] = mapped_column(String, nullable=False)
    sender_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.agents.id"))
    receiver_type: Mapped[str] = mapped_column(String, nullable=False)
    receiver_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.agents.id"))
    message_type: Mapped[str | None] = mapped_column(String)
    sequence_number: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict | None] = mapped_column(JSONB)  # C4 MessagePayload
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the envelope timestamp


class NegotiationOffer(Base):
    __tablename__ = "negotiation_offers"
    __table_args__ = {"schema": "negotiation"}

    id: Mapped[uuid.UUID] = uuid_pk()
    negotiation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(SESSION_FK))
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("negotiation.negotiation_messages.id")
    )
    offer_number: Mapped[int] = mapped_column(Integer, nullable=False)
    offer_type: Mapped[str] = mapped_column(String, nullable=False)
    terms: Mapped[dict] = mapped_column(JSONB, nullable=False)  # C4 OfferTerms
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # stays NULL (P1-04)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime | None] = created_at()


class NegotiationAgreement(Base):
    __tablename__ = "negotiation_agreements"
    __table_args__ = {"schema": "negotiation"}

    id: Mapped[uuid.UUID] = uuid_pk()
    negotiation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(SESSION_FK))
    agreed_terms: Mapped[dict] = mapped_column(JSONB, nullable=False)
    validated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    committed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime | None] = created_at()
