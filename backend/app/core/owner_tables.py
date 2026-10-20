"""Column shapes every resource owner repeats (quantity_accounting.md §8, QA-1): the ledger, the audit log and the
event-version table. Each owner declares its own tables in its own schema with these mixins."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column


class LedgerMixin:
    """One signed change of one number. `source_id` + `line_no` are unique per table, so a repeated event or message
    can never change a number twice."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_ref: Mapped[str] = mapped_column(String, nullable=False)  # item / zone / skill / "receiving"
    day: Mapped[date | None] = mapped_column(Date)  # for per-day resources
    bucket: Mapped[str] = mapped_column(String, nullable=False)
    delta: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    refs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # hold, reservation, order, case ...
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sim_day: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    case_id: Mapped[str | None] = mapped_column(String)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class LedgerWriter:
    """Writes ledger rows for one source (event or message) with increasing line numbers."""

    def __init__(self, db: Session, model: type, source_id: str, sim_day: date | None):
        self.db, self.model, self.source_id, self.sim_day, self.line = db, model, source_id, sim_day, 0

    def write(self, resource_ref: str, bucket: str, delta: Decimal, reason: str, day: date | None = None,
              **refs: object) -> None:
        self.line += 1
        self.db.add(self.model(resource_ref=str(resource_ref), day=day, bucket=bucket, delta=Decimal(delta),
                               reason=reason, refs={k: str(v) for k, v in refs.items() if v is not None},
                               source_id=self.source_id, line_no=self.line, sim_day=self.sim_day))

    def already_applied(self) -> bool:
        """True if this source already wrote rows (a repeat): the caller then changes nothing."""
        return self.db.query(self.model.id).filter(self.model.source_id == self.source_id).first() is not None


def ledger_sums(db: Session, model: type) -> dict[tuple, Decimal]:
    """Sum of every ledger's deltas per (resource, day, bucket): what the balances must equal (QA-1 reconcile)."""
    rows = db.execute(select(model.resource_ref, model.day, model.bucket, func.sum(model.delta))
                      .group_by(model.resource_ref, model.day, model.bucket)).all()
    return {(ref, day, bucket): total for ref, day, bucket, total in rows}


def differences(expected: dict[str, Decimal], actual: dict[str, Decimal]) -> list[str]:
    """Readable list of every key where the ledger and the balance disagree (empty = reconciled)."""
    zero = Decimal(0)
    return [f"{key}: ledger {expected.get(key, zero)} != balance {actual.get(key, zero)}"
            for key in sorted(set(expected) | set(actual)) if expected.get(key, zero) != actual.get(key, zero)]
