"""The event manager on the database (EM-1, EM-2): a published event stores its catalogue version, is delivered only to
subscribers with a handler, and shows up in the live numbers of the read-only Events door."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.events import api, channel
from app.events.models import Event, EventDelivery
from sqlalchemy import select


def test_published_events_are_versioned_counted_and_shown(session_factory, agents):
    with session_factory() as db:
        channel.publish(db, event_type="SimulatedDayStarted", publisher=channel.SIMULATOR_CLOCK, entity_type="clock",
                        entity_id="clock", entity_version=1, correlation_id="day-1", payload={"date": "2026-11-03"})
        db.commit()
        event = db.scalar(select(Event))
        assert event.schema_version == 1
        receivers = sorted(d.subscriber for d in db.scalars(select(EventDelivery)))
        assert receivers == ["HR", "INVENTORY", "PLANNING", "PURCHASING", "WAREHOUSE"]  # Sales has no handler

    app = FastAPI()
    app.include_router(api.router)

    def session_per_request():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = session_per_request
    view = TestClient(app).get("/events/catalogue").json()
    day = next(e for e in view["events"] if e["name"] == "SimulatedDayStarted")
    assert day["stats"]["published"] == 1 and day["stats"]["last_published"]
    assert day["stats"]["deliveries"]["PLANNING"] == {"PENDING": 1}
    assert {s["agent"]: s["handler"] for s in day["subscribers"]}["SALES"] is False
    assert view["report"]["missing_handlers"] == []
