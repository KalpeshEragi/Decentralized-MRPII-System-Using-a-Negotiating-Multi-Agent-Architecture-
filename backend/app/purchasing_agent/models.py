"""The Purchasing Agent tables (schema `purchasing_agent`, dev_docs/OVERALL_DATABASE_SCHEMA.md §5.2). They match migration 009 (004 before the merge).

Own declarative base, like the Sales Agent. References to the Supplier Service and the Negotiation Engine are logical
(UUIDs without a database foreign key), checked through those modules' interfaces. Allowed status values are enforced
by CHECK constraints in the migration and listed in comments here.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, MetaData, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "purchasing_agent"



class RequestStatus:
    """`procurement_requests.status`."""

    RECEIVED = "RECEIVED"
    NEGOTIATING = "NEGOTIATING"
    AGREEMENT_PROPOSED = "AGREEMENT_PROPOSED"
    COMMITTED = "COMMITTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    FAILED = "FAILED"


class LegStatus:
    """`purchase_requisitions.status`."""

    PENDING = "PENDING"
    AGREED = "AGREED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    COMMITTED = "COMMITTED"
    OPEN = (PENDING, AGREED)  # still negotiating or agreed: part of the procurement, not yet committed
    HOLDING = (PENDING, AGREED, COMMITTED)  # reduce the supplier's effective availability (§6.3)


class LegReason:
    """`purchase_requisitions.status_reason` of a FAILED or ABORTED Leg (also the Engine session's reason)."""

    SUPPLIER_REJECTED = "supplier_rejected"
    ROUND_LIMIT_EXCEEDED = "round_limit_exceeded"
    TIMEOUT = "timeout"
    UNCLEAR_RESPONSE = "unclear_response"
    SPLIT_FAILED = "split_failed"  # another Leg failed the procurement (§7.5)
    NO_LONGER_NEEDED = "no_longer_needed"  # dropped on reallocation (§7.4): no longer part of the procurement
    MANUALLY_ABORTED = "manually_aborted"
    APPROVAL_REJECTED = "approval_rejected"


class PurchasingAgentBase(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def logical_ref(nullable: bool = False) -> Mapped:
    return mapped_column(UUID(as_uuid=True), nullable=nullable)


def foreign_key(target: str, nullable: bool = True) -> Mapped:
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.{target}"), nullable=nullable)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PurchasingContract(PurchasingAgentBase):
    __tablename__ = "purchasing_contracts"

    id: Mapped[uuid.UUID] = uuid_pk()
    supplier_id: Mapped[uuid.UUID] = logical_ref()  # supplier_service.suppliers
    item_id: Mapped[uuid.UUID] = logical_ref()  # supplier_service.items
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # INR per unit
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)  # empty = open-ended
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()


class ProcurementRequest(PurchasingAgentBase):
    """One Procurement Request; it also holds the combined Procurement Agreement outcome."""

    __tablename__ = "procurement_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = logical_ref()  # supplier_service.items
    shortage_quantity: Mapped[Decimal] = mapped_column(Numeric)
    required_date: Mapped[date] = mapped_column(Date)  # never changed by Purchasing
    priority: Mapped[int] = mapped_column(Integer)
    requested_by: Mapped[str] = mapped_column(String)
    request_ref: Mapped[str] = mapped_column(String, unique=True)  # the requester's idempotency key
    # RECEIVED, NEGOTIATING, AGREEMENT_PROPOSED, COMMITTED, APPROVAL_REJECTED, FAILED
    status: Mapped[str] = mapped_column(String, default=RequestStatus.RECEIVED)
    split_type: Mapped[str | None] = mapped_column(String)  # SINGLE, NECESSARY_SPLIT, COST_SAVING_SPLIT
    cost_ranking_available: Mapped[bool | None] = mapped_column(Boolean)
    constrained_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    status_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class PurchaseRequisition(PurchasingAgentBase):
    """One Leg: one supplier's part of a Procurement Request."""

    __tablename__ = "purchase_requisitions"

    id: Mapped[uuid.UUID] = uuid_pk()
    procurement_request_id: Mapped[uuid.UUID] = foreign_key("procurement_requests.id", nullable=False)
    supplier_id: Mapped[uuid.UUID] = logical_ref()  # supplier_service.suppliers
    purchasing_contract_id: Mapped[uuid.UUID | None] = foreign_key("purchasing_contracts.id")  # empty = Not Registered
    unit_price_at_selection: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # price snapshot; empty = Not Registered
    allocated_quantity: Mapped[Decimal] = mapped_column(Numeric)
    quantity_cap: Mapped[Decimal | None] = mapped_column(Numeric)
    agreed_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    agreed_delivery_date: Mapped[date | None] = mapped_column(Date)
    negotiation_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)  # negotiation_engine
    status: Mapped[str] = mapped_column(String, default=LegStatus.PENDING)  # PENDING, AGREED, FAILED, ABORTED, COMMITTED
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class DecisionAudit(PurchasingAgentBase):
    __tablename__ = "decision_audit"

    id: Mapped[uuid.UUID] = uuid_pk()
    procurement_request_id: Mapped[uuid.UUID | None] = foreign_key("procurement_requests.id")
    decision_type: Mapped[str] = mapped_column(String)  # SUPPLIER_SELECTION, REALLOCATION, RE_SOURCING,
    # RESPONSE_VALIDATION, RESPONSE_DEADLINE, APPROVAL, MANUAL_ABORT
    context: Mapped[dict] = mapped_column(JSONB)  # options considered, prices or Not Registered, exclusions
    decision: Mapped[dict] = mapped_column(JSONB)
    reasoning_summary: Mapped[str] = mapped_column(Text)  # deterministic rationale
    llm_explanation: Mapped[str | None] = mapped_column(Text)  # explanation only, never evidence
    created_at: Mapped[datetime] = created_at()
