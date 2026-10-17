"""The shared work runner (dev_docs/architecture/system_design.md §4, decision SD-1).

All pending background work lives in PostgreSQL queue tables of one standard shape (`QueueMixin`). This module claims
work safely, retries failures with backoff, tracks attempts, and keeps work with the same `scope_key` strictly one at
a time and in order. It knows nothing about business: owners register handlers.

Two run modes:
- short (`run_one_short`): claim, handle and mark done in ONE transaction. For quick deterministic handlers.
- long  (`run_one_long`): claim with a lease and commit; the handler runs without an open transaction (AI calls, HTTP
  sends); then mark done. A crashed worker's lease expires and another worker takes the item over. Handlers must make
  every business write idempotent (unique keys), so a takeover never repeats an action.

Only database row locks are used (FOR UPDATE SKIP LOCKED), no in-memory locks, so several worker processes are safe.
Times here are real time (leases, retries), never simulated business time.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Integer, String, Text, exists, func, or_, and_, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, aliased, mapped_column

logger = logging.getLogger(__name__)

PENDING, RUNNING, DONE, FAILED, IGNORED_STALE = "PENDING", "RUNNING", "DONE", "FAILED", "IGNORED_STALE"
FINISHED = (DONE, IGNORED_STALE)
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (1, 5, 30, 120)  # wait after attempt 1, 2, 3, 4; attempt 5 failing -> FAILED
DEFAULT_LEASE_SECONDS = 120


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class QueueMixin:
    """The standard queue shape (system_design.md §4.2). `seq` gives a strict order inside a scope."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    scope_key: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default=PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    locked_by: Mapped[str | None] = mapped_column(String)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class WorkItem:
    """A plain copy of a claimed row, handed to long-mode handlers (no ORM object outlives its transaction)."""

    id: uuid.UUID
    scope_key: str
    kind: str
    payload: dict
    attempts: int


def enqueue(db: Session, model: type, *, scope_key: str, kind: str, payload: dict | None = None,
            now: datetime | None = None, **columns: Any):
    """Add one PENDING item in the caller's transaction (nothing is committed here)."""
    row = model(scope_key=scope_key, kind=kind, payload=payload or {}, status=PENDING, attempts=0,
                next_attempt_at=now or utc_now(), **columns)
    db.add(row)
    return row


def claim(db: Session, model: type, now: datetime, where=None):
    """Lock and return the next item that may run now, or None.

    May run: PENDING and due, or RUNNING with an expired lease. And no earlier item (smaller seq) of the same scope is
    unfinished — so one scope runs one item at a time, in order, and a FAILED item holds its scope until retried.
    `where` narrows the rows this worker may take (e.g. only messages addressed to one agent).
    """
    earlier = aliased(model)
    blocked = exists().where(earlier.scope_key == model.scope_key, earlier.seq < model.seq,
                             earlier.status.not_in(FINISHED))
    may_run = or_(and_(model.status == PENDING, model.next_attempt_at <= now),
                  and_(model.status == RUNNING, model.locked_until < now))
    statement = select(model).where(may_run, ~blocked)
    if where is not None:
        statement = statement.where(where)
    statement = statement.order_by(model.seq).limit(1).with_for_update(skip_locked=True, of=model)
    return db.scalars(statement).first()


def _record_failure(db: Session, row, error: BaseException, now: datetime) -> None:
    row.attempts = (row.attempts or 0) + (0 if row.status == RUNNING else 1)  # long mode counted it at claim
    row.last_error = f"{type(error).__name__}: {error}"[:2000]
    row.locked_by = row.locked_until = None
    if row.attempts >= MAX_ATTEMPTS:
        row.status = FAILED
    else:
        row.status = PENDING
        row.next_attempt_at = now + timedelta(seconds=BACKOFF_SECONDS[row.attempts - 1])


def run_one_short(session_factory: Callable[[], Session], model: type, handler: Callable[[Session, Any], str | None],
                  now: datetime | None = None, where=None) -> bool:
    """Claim one item and run `handler(db, row)` in the same transaction. Returns False if nothing could be claimed.

    The handler returns DONE (or None) or IGNORED_STALE. If it raises, everything it did is undone and the failure is
    recorded in a new transaction (retry with backoff, FAILED after MAX_ATTEMPTS).
    """
    now = now or utc_now()
    with session_factory() as db:
        row = claim(db, model, now, where)
        if row is None:
            db.rollback()
            return False
        row_id = row.id
        try:
            result = handler(db, row) or DONE
            row.status, row.attempts, row.done_at = result, row.attempts + 1, now
            row.locked_by = row.locked_until = None
            db.commit()
            return True
        except Exception as error:  # noqa: BLE001 - any handler failure becomes a retry, never a lost item
            db.rollback()
            logger.warning("work item %s (%s) failed: %s", row_id, model.__tablename__, error)
            row = db.get(model, row_id, with_for_update=True)
            _record_failure(db, row, error, now)
            db.commit()
            return True


def run_one_long(session_factory: Callable[[], Session], model: type,
                 handler: Callable[[Callable[[], Session], WorkItem, Callable[[], None]], None],
                 worker_id: str, now: datetime | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS,
                 clock: Callable[[], datetime] = utc_now, where=None) -> bool:
    """Claim one item with a lease, run `handler(session_factory, item, renew)` outside any transaction, then mark it
    done. `renew()` extends the lease during long work. If another worker took the item over after the lease expired,
    this worker's late finish is ignored. Returns False if nothing could be claimed."""
    now = now or clock()
    with session_factory() as db:
        row = claim(db, model, now, where)
        if row is None:
            db.rollback()
            return False
        row.status, row.locked_by = RUNNING, worker_id
        row.locked_until = now + timedelta(seconds=lease_seconds)
        row.attempts += 1
        item = WorkItem(row.id, row.scope_key, row.kind, dict(row.payload), row.attempts)
        db.commit()

    def renew() -> None:
        with session_factory() as db:
            current = db.get(model, item.id, with_for_update=True)
            if current is not None and current.status == RUNNING and current.locked_by == worker_id:
                current.locked_until = clock() + timedelta(seconds=lease_seconds)
            db.commit()

    try:
        handler(session_factory, item, renew)
        error = None
    except Exception as exc:  # noqa: BLE001
        logger.warning("work item %s (%s) failed: %s", item.id, model.__tablename__, exc)
        error = exc

    with session_factory() as db:
        current = db.get(model, item.id, with_for_update=True)
        if current is None or current.status != RUNNING or current.locked_by != worker_id:
            db.rollback()  # taken over by another worker after our lease expired: its result counts, not ours
            return True
        if error is None:
            current.status, current.done_at = DONE, clock()
            current.locked_by = current.locked_until = None
        else:
            _record_failure(db, current, error, clock())
        db.commit()
    return True


def retry_failed(db: Session, model: type, item_id: uuid.UUID, now: datetime | None = None) -> bool:
    """Manual retry door: put one FAILED item back to PENDING (attempts reset). False if it is not FAILED."""
    row = db.get(model, item_id, with_for_update=True)
    if row is None or row.status != FAILED:
        return False
    row.status, row.attempts, row.next_attempt_at, row.last_error = PENDING, 0, now or utc_now(), None
    return True


@dataclass
class Registration:
    name: str
    model: type
    handler: Callable
    mode: str = "short"  # "short" or "long"
    workers: int = 1
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    where: Any = None  # optional filter on the rows this registration may take


@dataclass
class WorkRunner:
    """Background threads that keep claiming work from the registered queues (started by the FastAPI lifespan today;
    a separate worker program can start the same registrations later). Threads are its own, never the request pool."""

    session_factory: Callable[[], Session]
    poll_seconds: float = 0.5
    registrations: list[Registration] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _threads: list[threading.Thread] = field(default_factory=list)

    def register(self, registration: Registration) -> None:
        if any(r.name == registration.name for r in self.registrations):
            return  # registering twice (e.g. app restarted in tests) is harmless
        self.registrations.append(registration)

    def start(self) -> None:
        self._stop.clear()
        for registration in self.registrations:
            for number in range(registration.workers):
                worker_id = f"{registration.name}-{number}-{uuid.uuid4().hex[:8]}"
                thread = threading.Thread(target=self._loop, args=(registration, worker_id), name=worker_id,
                                          daemon=True)
                thread.start()
                self._threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout)
        self._threads.clear()

    def _loop(self, registration: Registration, worker_id: str) -> None:
        while not self._stop.is_set():
            try:
                if registration.mode == "long":
                    worked = run_one_long(self.session_factory, registration.model, registration.handler, worker_id,
                                          lease_seconds=registration.lease_seconds, where=registration.where)
                else:
                    worked = run_one_short(self.session_factory, registration.model, registration.handler,
                                           where=registration.where)
            except Exception:  # noqa: BLE001 - e.g. database unreachable; keep the thread alive and try again later
                logger.exception("work runner %s: claiming failed", worker_id)
                worked = False
            if not worked:
                self._stop.wait(self.poll_seconds)
