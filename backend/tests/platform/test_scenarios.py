"""Step 7 (demo.md §8, §12): a scenario played from the start to its run report, only through the simulator's doors.
S1 on Factory A: the scenario's NEW_ORDER trigger sends a simulated customer's request on day 1; the customer accepts
by rule; the agents plan, commit, produce and ship; the finished run's report counts one order completed on time.
With nothing left to do, Play pauses by itself instead of moving the clock through empty days."""

from app.planning_agent import reads as plans
from app.simulation import runner
from tests.platform.phone_factory import KEY, run_day

HEADERS = {"X-Door-Key": KEY}


def test_scenario_s1_runs_on_factory_a_from_start_to_report(session_factory, pump, factory):
    client = factory["client"]  # (the phone factory of the fixture is replaced by Factory A when S1 starts)
    started = client.post("/simulation/scenarios/S1/start", json={"seed": 7}, headers=HEADERS)
    assert started.status_code == 201, started.text
    assert started.json()["reconcile"] == {"inventory": [], "hr": [], "warehouse": [], "planning": []}
    assert client.get("/simulation/clock").json()["work_left"] == ["1 scheduled triggers"]

    for _ in range(10):
        run_day(session_factory, pump, client)
        with session_factory() as db:
            demands = plans.demands(db)
            if demands and demands[0]["status"] == "COMPLETED":
                break
    assert [t["status"] for t in client.get("/simulation/triggers").json()] == ["DONE"]

    before = client.get("/simulation/clock").json()
    assert before["work_left"] == []
    runner.play(session_factory)
    runner._play_thread.join(timeout=30)
    after = client.get("/simulation/clock").json()
    assert (after["status"], after["current_day"]) == ("PAUSED", before["current_day"])
    assert after["pause_reason"].startswith("nothing left to do")

    run_id = started.json()["run_id"]
    metrics = client.post(f"/simulation/runs/{run_id}/finish", headers=HEADERS).json()
    assert (metrics["orders"], metrics["completed"], metrics["completed_on_time"]) == (1, 1, 1)
    report = client.get(f"/simulation/runs/{run_id}/report").json()
    assert report["run"]["scenario"] == "S1" and report["timeline"]
    measured = report["measurements"]  # the run's measurements (system_design §10), also at GET /observer/metrics
    assert measured == client.get("/observer/metrics").json()
    assert (measured["orders"]["total"], measured["orders"]["completed_on_time"]) == (1, 1)
    assert measured["orders"]["seconds_request_to_committed"]["count"] == 1
    assert measured["orders"]["seconds_confirmed_to_committed"]["count"] == 1
    assert measured["days"]["count"] >= 2 and measured["days"]["p50"] is not None
    assert measured["event_delivery"]["failed"] == 0 and measured["event_delivery"]["seconds_lag"]["count"] > 0
    assert measured["negotiations"]["seconds_open_to_closed"]["count"] > 0
    assert all(q["failed"] == 0 for q in measured["queues"].values())
    assert client.get("/simulation/runs").json()[0]["status"] == "FINISHED"
