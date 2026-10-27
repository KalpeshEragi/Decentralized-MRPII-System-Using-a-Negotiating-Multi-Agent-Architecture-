"""Planning's decision point D7 in a full run (S8: four competing orders on the same day). When an owner counters or
rejects while an option is being secured, Planning decides — with the deterministic policy when AI is off, or with
the (fake) model when it is on — and records each decision. Whatever it decides, nothing is booked twice, every
owner's records still add up, and every order gets a final answer."""

import json
from collections import Counter
from decimal import Decimal

import pytest

from app.llm.client import FakeLLMClient
from app.planning_agent import decisions as d7, reads as plans
from app.planning_agent.models import AuditLog, Case, WorkCenterDay
from app.simulation.states import reconcile
from tests.platform.phone_factory import KEY, run_day
from sqlalchemy import select

HEADERS = {"X-Door-Key": KEY}


def play_s8(session_factory, pump, client) -> list[dict]:
    assert client.post("/simulation/scenarios/S8/start", json={"seed": 1}, headers=HEADERS).status_code == 201
    for _ in range(25):
        run_day(session_factory, pump, client)
        with session_factory() as db:
            assert reconcile(db) == {"inventory": [], "hr": [], "warehouse": [], "planning": []}
            demands = plans.demands(db)
            if len(demands) == 4 and all(d["status"] in plans.FINISHED_DEMANDS for d in demands):
                break
    with session_factory() as db:
        demands = plans.demands(db)
        assert len(demands) == 4 and all(d["status"] in plans.FINISHED_DEMANDS for d in demands), demands
        for d in demands:
            if d["status"] == "COMPLETED":
                assert d["quantity_shipped"] == d["committed_quantity"]
        rows = db.scalars(select(AuditLog).where(AuditLog.event_type == "DECISION"))
        return [row.details for row in rows if row.details["decision_point"] == "D7"]  # D6 = make-or-buy from quotes


def test_ai_off_planning_decides_with_its_policy_and_records_it(session_factory, pump, factory):
    records = play_s8(session_factory, pump, factory["client"])
    print("AI off", Counter((r["chosen_by"], r["action"]) for r in records))  # what the policy did (pytest -s)
    assert records, "S8 must make Planning decide at least once (competing orders)"
    assert {r["chosen_by"] for r in records} == {"FALLBACK"}
    assert {r["fallback_reason"] for r in records} == {"AI_OFF"}
    assert {r["action"] for r in records} <= {"RE_ASK", "NEXT_OPTION"}
    for r in records:  # the policy of QD-6
        stale = r["facts"]["what_happened"]["reason"] in d7.RETRYABLE
        if r["action"] == "RE_ASK":
            assert stale and r["facts"]["re_asks_used"] < d7.MAX_REASKS


@pytest.mark.parametrize("choice", ["REPLAN", "PARTIAL_AND_BUY"])
def test_ai_on_the_agents_choice_is_checked_and_the_run_stays_consistent(session_factory, pump, factory,
                                                                         monkeypatch, choice):
    """The fake model always proposes `choice`. Where the check allows it, it is carried out (MODEL); where not, the
    agent gets one revision (it repeats itself) and the policy decides (FALLBACK, NOT_VALID)."""
    answer = json.dumps({"thinking": f"I prefer {choice} here.", "action": choice, "params": {},
                         "reason": f"test: always {choice}"})
    monkeypatch.setattr(d7, "decision_client", lambda db: FakeLLMClient([answer]))
    records = play_s8(session_factory, pump, factory["client"])
    assert records
    print(choice, Counter((r["chosen_by"], r["action"]) for r in records))  # what the agent did (pytest -s)
    for r in records:
        if r["chosen_by"] == "MODEL":
            assert r["action"] == choice and r["thinking"] == f"I prefer {choice} here." and not r["refusals"]
        else:
            assert (r["chosen_by"], r["fallback_reason"]) == ("FALLBACK", "NOT_VALID")
            assert len(r["refusals"]) == 2 and r["action"] in ("RE_ASK", "NEXT_OPTION")
    with session_factory() as db:
        if choice == "PARTIAL_AND_BUY" and any(r["chosen_by"] == "MODEL" for r in records):
            needs = [s["need"] for c in db.scalars(select(Case)) for s in c.sessions.values()]
            assert any(n.endswith("(rest)") for n in needs)  # the rest was asked from Purchasing
        for work_center in plans.work_centers(db):
            days = {row.day for row in db.scalars(select(WorkCenterDay))}
            assert all(Decimal(plans.machine_hours_free(db, work_center, day)) >= 0 for day in days)
