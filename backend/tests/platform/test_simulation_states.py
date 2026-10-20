"""Step 7 (demo.md §5, DM-2): a saved state is restored exactly, every owner reconciles, and replaying the same day
from it gives the same result. The factory is `phone_factory.py`."""

from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import func, select

from app.events.models import Event
from app.inventory_agent import reads as stock
from app.simulation.clock import today
from app.simulation.states import reconcile
from tests.platform.phone_factory import KEY, confirm, request, run_day

CLEAN = {"inventory": [], "hr": [], "warehouse": [], "planning": []}


def chips(session_factory, factory) -> tuple:
    with session_factory() as db:
        position = stock.stock_position(db, factory["chip"])
        return D(position["on_hand"]), D(position["reserved"]), today(db)


def test_a_saved_state_is_restored_exactly_and_replays_the_same(session_factory, pump, factory):
    client = factory["client"]
    due = factory["start"] + timedelta(days=3)  # the PCBs (200 chips) are made on day 1, the phones on day 2
    sent = request(client, "REQ-ST", 100, due, factory["start"])
    pump()
    confirm(session_factory, sent, "SA-ST", 100, due)
    pump()
    saved = client.post("/simulation/states", json={"name": "committed"}, headers={"X-Door-Key": KEY})
    assert saved.status_code == 201 and saved.json()["rows"] > 0, saved.text
    with session_factory() as db:
        assert reconcile(db) == CLEAN
        events_at_save = db.scalar(select(func.count()).select_from(Event))
    before = chips(session_factory, factory)
    assert before[:2] == (1000, 200)

    run_day(session_factory, pump, client)  # kits issued: 200 chips leave
    after_day = chips(session_factory, factory)
    assert after_day[:2] == (800, 0)

    restored = client.post("/simulation/states/committed/restore", headers={"X-Door-Key": KEY})
    assert restored.status_code == 200 and restored.json()["reconcile"] == CLEAN, restored.text
    assert chips(session_factory, factory) == before  # stock and the simulated day exactly as saved
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Event)) == events_at_save  # nothing of the later day left

    run_day(session_factory, pump, client)  # same state + same inputs = same result
    assert chips(session_factory, factory) == after_day
    with session_factory() as db:
        assert reconcile(db) == CLEAN
