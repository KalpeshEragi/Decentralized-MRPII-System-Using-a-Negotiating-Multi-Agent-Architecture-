"""The shared work runner (system_design.md §4): one item per scope at a time and in order, retries with backoff,
FAILED holds its scope until a manual retry, and a long-mode lease takeover never finishes an item twice.
Uses the event-delivery queue as a concrete queue table."""

from datetime import timedelta

from app.core import work_runner as wr
from app.events.models import Event, EventDelivery

Q = EventDelivery


def _add_items(session_factory, *scopes: str) -> list:
    """One committed queue item per scope given, in this order."""
    with session_factory() as db:
        event = Event(event_type="T", publisher="TEST", entity_type="t", entity_id="x", entity_version=1,
                      correlation_id="c", occurred_at=wr.utc_now())
        db.add(event)
        db.flush()
        rows = [wr.enqueue(db, Q, scope_key=scope, kind=f"item-{n}", now=wr.utc_now() - timedelta(seconds=1),
                           event_id=event.event_id, subscriber=f"S{n}") for n, scope in enumerate(scopes)]
        db.commit()
        return [row.id for row in rows]


def _status(session_factory, item_id):
    with session_factory() as db:
        row = db.get(Q, item_id)
        return row.status, row.attempts


def test_one_item_per_scope_at_a_time_in_order(session_factory):
    a, b, c = _add_items(session_factory, "s1", "s1", "s2")
    now = wr.utc_now()

    first, second, third = session_factory(), session_factory(), session_factory()
    try:
        assert wr.claim(first, Q, now).id == a          # A is locked by the first worker
        assert wr.claim(second, Q, now).id == c         # B waits behind A (same scope); C is free
        assert wr.claim(third, Q, now) is None          # nothing else may run
    finally:
        for db in (first, second, third):
            db.rollback()
            db.close()

    order = []
    while wr.run_one_short(session_factory, Q, lambda db, row: order.append(row.id), now=now):
        pass
    assert order == [a, b, c]
    assert not wr.run_one_short(session_factory, Q, lambda db, row: order.append(row.id), now=now)  # DONE stays done


def test_failures_retry_with_backoff_then_fail_and_hold_the_scope(session_factory):
    a, b = _add_items(session_factory, "s1", "s1")
    broken = {"on": True}
    done = []

    def handler(db, row):
        if broken["on"] and row.id == a:
            raise RuntimeError("boom")
        done.append(row.id)

    now = wr.utc_now()
    for attempt, wait in enumerate((*wr.BACKOFF_SECONDS, None), start=1):
        assert wr.run_one_short(session_factory, Q, handler, now=now)
        status, attempts = _status(session_factory, a)
        assert attempts == attempt
        if wait is None:
            assert status == wr.FAILED
        else:
            assert status == wr.PENDING
            assert not wr.run_one_short(session_factory, Q, handler, now=now)  # not due yet; B waits behind A
            now += timedelta(seconds=wait)

    far = now + timedelta(days=1)
    assert not wr.run_one_short(session_factory, Q, handler, now=far)  # FAILED A holds its scope: B never runs
    assert done == []

    with session_factory() as db:
        assert wr.retry_failed(db, Q, a, now=far)
        db.commit()
    broken["on"] = False
    while wr.run_one_short(session_factory, Q, handler, now=far):
        pass
    assert done == [a, b]


def test_long_mode_lease_takeover_finishes_once(session_factory):
    (a,) = _add_items(session_factory, "s1")
    start = wr.utc_now()
    finished_by = []

    def slow_worker(factory, item, renew):
        # While worker 1 is still busy, its lease is valid: nobody else may take the item.
        assert not wr.run_one_long(factory, Q, lambda *_: None, "w2", now=start + timedelta(seconds=60))
        # Worker 1 hangs past its lease; worker 2 takes the item over and finishes it.
        assert wr.run_one_long(factory, Q, lambda *_: finished_by.append("w2"), "w2",
                               now=start + timedelta(seconds=wr.DEFAULT_LEASE_SECONDS + 1))
        finished_by.append("w1-work")

    assert wr.run_one_long(session_factory, Q, slow_worker, "w1", now=start)
    status, attempts = _status(session_factory, a)
    assert (status, attempts) == (wr.DONE, 2)
    assert finished_by == ["w2", "w1-work"]  # w1 did its work, but its late finish was ignored (no double finish)
