"""`hr` schema of the HR Agent (hr_agent/4_hr_agent_database.md). Workers are simulated and fictional (HD-2).

Simplifications against note 4 (same meaning): a hold's and a commitment's per-day hours are a JSON `lines` column
instead of separate line tables; a pool's capacity is computed from workers, absences, moves and overtime instead of
being stored. Committed and held hours are stored per skill and day with a ledger (HD-1, QA-1).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.owner_tables import AuditMixin, LedgerMixin
from app.core.platform_base import PlatformBase
from app.events.models import EventVersionMixin

SCHEMA = "hr"


class Worker(PlatformBase):
    __tablename__ = "workers"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    primary_skill: Mapped[str] = mapped_column(String, nullable=False)
    secondary_skills: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    shift_hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=8)


class Absence(PlatformBase):
    __tablename__ = "absences"
    __table_args__ = {"schema": SCHEMA}

    absence_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    first_day: Mapped[date] = mapped_column(Date, nullable=False)
    last_day: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PLANNED")  # PLANNED, COVERED, ACTIVE, ENDED


class PoolDay(PlatformBase):
    __tablename__ = "pool_days"
    __table_args__ = {"schema": SCHEMA}

    skill: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    committed_hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    held_hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkerMove(PlatformBase):
    """A multi-skilled worker's hours moved to another pool for one day (HR-2). Counts while HELD or COMMITTED."""

    __tablename__ = "worker_moves"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    worker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_skill: Mapped[str] = mapped_column(String, nullable=False)
    to_skill: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    hold_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String, nullable=False, default="HELD")


class OvertimeEntry(PlatformBase):
    __tablename__ = "overtime_entries"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    worker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    skill: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    hold_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String, nullable=False, default="HELD")


class Hold(PlatformBase):
    __tablename__ = "holds"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill: Mapped[str] = mapped_column(String, nullable=False)
    production_order_ref: Mapped[str] = mapped_column(String, nullable=False)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    negotiation_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    lines: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {day: hours}
    expires_day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")


class Commitment(PlatformBase):
    __tablename__ = "commitments"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill: Mapped[str] = mapped_column(String, nullable=False)
    production_order_ref: Mapped[str] = mapped_column(String, nullable=False)
    case_id: Mapped[str] = mapped_column(String, nullable=False)
    hold_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    lines: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {day: hours}
    missing: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {day: missing hours} when AT_RISK
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Assignment(PlatformBase):
    __tablename__ = "assignments"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commitment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    worker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PLANNED")


class HoursLedger(LedgerMixin, PlatformBase):
    __tablename__ = "hours_ledger"
    __table_args__ = (UniqueConstraint("source_id", "line_no"), {"schema": SCHEMA})


class EventVersion(EventVersionMixin, PlatformBase):
    __tablename__ = "event_versions"
    __table_args__ = {"schema": SCHEMA}


class AuditLog(AuditMixin, PlatformBase):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": SCHEMA}
