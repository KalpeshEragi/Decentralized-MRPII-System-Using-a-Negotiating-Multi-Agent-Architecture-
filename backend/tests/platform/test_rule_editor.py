"""The rule editor on the database (RE-1, RE-6): a change updates what the agents read, is kept in the rule profile and
the history, is refused outside its bounds, and survives a scenario restore. Played through the rule doors."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import install_error_handlers
from app.rules import api
from app.simulation import factory_a, states
from app.simulation.settings import setting

KEY = "test-door-key"


def client(session_factory, monkeypatch) -> TestClient:
    monkeypatch.setattr(get_settings(), "simulation_door_key", KEY)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(api.router)

    def session_per_request():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = session_per_request
    return TestClient(app, headers={"X-Door-Key": KEY})


def test_a_rule_change_is_applied_kept_and_survives_a_restore(session_factory, monkeypatch):
    with session_factory() as db:  # a saved starting state, like a scenario's
        factory_a.build(db)
        db.flush()
        states.save(db, "start", "test state")
        db.commit()
    web = client(session_factory, monkeypatch)

    listed = web.get("/rules").json()
    hr = next(g for g in listed["groups"] if g["owner"] == "HR")
    assert [r["key"] for r in hr["rules"]] == ["overtime_max_hours_per_day", "overtime_max_hours_per_week"]
    assert listed["hidden_system_settings"] > 0

    changed = web.put("/rules/overtime_max_hours_per_day", json={"value": 4, "note": "busy season"},
                      headers={"X-Changed-By": "Kalpesh"})
    assert changed.status_code == 200 and changed.json() == {"key": "overtime_max_hours_per_day", "from": 2, "to": 4,
                                                             "action": "CHANGED"}
    with session_factory() as db:
        assert setting(db, "overtime_max_hours_per_day") == 4  # what HR reads from now on

    with session_factory() as db:  # starting a scenario restores the saved state ...
        states.restore(db, "start")
        db.commit()
        assert setting(db, "overtime_max_hours_per_day") == 4  # ... and the personalised rule is put back

    rule = next(r for g in web.get("/rules").json()["groups"] for r in g["rules"]
                if r["key"] == "overtime_max_hours_per_day")
    assert rule["changed"] and rule["personalised"] and rule["last_change"]["by"] == "Kalpesh"
    history = web.get("/rules/history").json()
    assert history[0]["from"] == 2 and history[0]["to"] == 4 and history[0]["note"] == "busy season"

    assert web.delete("/rules/overtime_max_hours_per_day").json()["action"] == "RESET"
    with session_factory() as db:
        states.restore(db, "start")
        db.commit()
        assert setting(db, "overtime_max_hours_per_day") == 2  # reset: the profile no longer overrides


def test_values_that_would_break_the_system_are_refused(session_factory, monkeypatch):
    web = client(session_factory, monkeypatch)
    too_much = web.put("/rules/overtime_max_hours_per_day", json={"value": 9})
    assert too_much.status_code == 422 and "between 0 h and 6 h" in too_much.json()["detail"]
    conflict = web.put("/rules/overtime_max_hours_per_week", json={"value": 1})  # less than the 2 h per day
    assert conflict.status_code == 422 and "cannot be less" in conflict.json()["detail"]
    unused = web.put("/rules/dampener_days", json={"value": 2})
    assert unused.status_code == 422 and "not used" in unused.json()["detail"]
    assert web.put("/rules/no_such_rule", json={"value": 1}).status_code == 404
    no_key = web.put("/rules/time_fence_days", json={"value": 3}, headers={"X-Door-Key": "wrong"})
    assert no_key.status_code == 403
    with session_factory() as db:
        assert setting(db, "overtime_max_hours_per_week") == 8 and setting(db, "time_fence_days") == 2
