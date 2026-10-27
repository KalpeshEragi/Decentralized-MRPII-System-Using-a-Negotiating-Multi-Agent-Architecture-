"""The observer's timeline (API-2) is read page by page through its cursor. Events saved in one transaction share one
time (PostgreSQL `now()`); a page boundary inside such a group must not lose the rest of the group, or the panel and
the run report would miss facts during a busy run."""

from datetime import date, datetime, timedelta

from app.events import channel
from app.observer import views

START = date(2026, 1, 1)


def day(n: int) -> str:
    """Each test event carries its number as a day (a valid SimulatedDayStarted payload)."""
    return (START + timedelta(days=n)).isoformat()


def test_paging_through_the_timeline_loses_nothing_when_many_events_share_one_time(session_factory):
    with session_factory() as db:  # 250 events in one transaction: one shared time, more than one page
        for n in range(250):
            channel.publish(db, event_type="SimulatedDayStarted", publisher=channel.SIMULATOR_CLOCK,
                            entity_type="clock", entity_id="clock", entity_version=n + 1, correlation_id="test",
                            payload={"date": day(n)})
        db.commit()
    with session_factory() as db:  # and two more later
        for n in (250, 251):
            channel.publish(db, event_type="SimulatedDayStarted", publisher=channel.SIMULATOR_CLOCK,
                            entity_type="clock", entity_id="clock", entity_version=n + 1, correlation_id="test",
                            payload={"date": day(n)})
        db.commit()

    seen, after = [], None
    with session_factory() as db:
        for _ in range(10):
            page = views.timeline(db, datetime.fromisoformat(after) if after else None)
            if not page["items"]:
                break
            seen += [(date.fromisoformat(item["payload"]["date"]) - START).days for item in page["items"]]
            after = page["next"]
    assert sorted(seen) == list(range(252))  # every event exactly once
