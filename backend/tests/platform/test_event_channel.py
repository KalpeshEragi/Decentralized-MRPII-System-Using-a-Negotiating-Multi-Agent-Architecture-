"""The event channel (pubsub_event_channel.md): an event and its deliveries are saved with the business change or not
at all; each registered subscriber gets its own copy; per-entity order is kept per subscriber; one subscriber's
failure never blocks another. Uses the simulated clock, whose `next_day` publishes `SimulatedDayStarted`."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core import work_runner as wr
from app.events import channel
from app.events.models import Event, EventDelivery
from app.simulation import clock
from app.simulation.models import Clock


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_publish_is_saved_with_the_change_or_not_at_all(session_factory):
    channel.subscribe("PLANNING", "SimulatedDayStarted", lambda db, event: None)
    with session_factory() as db:
        clock.next_day(db)
        db.rollback()  # the business change fails
        assert (_count(db, Event), _count(db, EventDelivery), _count(db, Clock)) == (0, 0, 0)


def test_each_subscriber_gets_its_own_copy_in_order_and_failures_stay_isolated(session_factory):
    seen = {"PLANNING": [], "INVENTORY": []}
    inventory_calls = {"n": 0}

    def planning(db, event):
        seen["PLANNING"].append(event.payload["date"])

    def inventory(db, event):
        inventory_calls["n"] += 1
        if inventory_calls["n"] == 1:
            raise RuntimeError("inventory is down for a moment")
        seen["INVENTORY"].append(event.payload["date"])

    channel.subscribe("PLANNING", "SimulatedDayStarted", planning)
    channel.subscribe("INVENTORY", "SimulatedDayStarted", inventory)
    with session_factory() as db:
        day_1, day_2 = clock.next_day(db), clock.next_day(db)
        db.commit()
        assert _count(db, EventDelivery) == 4  # 2 events x 2 registered subscribers; Sales/Warehouse/HR not built yet

    now = wr.utc_now()
    while wr.run_one_short(session_factory, EventDelivery, channel.deliver, now=now):
        pass
    days = [day_1.isoformat(), day_2.isoformat()]
    assert seen == {"PLANNING": days, "INVENTORY": []}  # Inventory's failure did not block Planning

    later = now + timedelta(seconds=wr.BACKOFF_SECONDS[0] + 1)
    while wr.run_one_short(session_factory, EventDelivery, channel.deliver, now=later):
        pass
    assert seen["INVENTORY"] == days  # retried, and day 2 waited for day 1 (per-entity order)


def test_catalogue_is_enforced():
    with pytest.raises(ValueError):
        channel.subscribe("SALES", "ReservationCommitted", lambda db, event: None)  # Sales is not a subscriber
    with pytest.raises(ValueError):
        channel.publish(None, event_type="OrderConfirmed", publisher="PLANNING", entity_type="order",
                        entity_id="1", entity_version=1, correlation_id="c")  # only Sales publishes it
