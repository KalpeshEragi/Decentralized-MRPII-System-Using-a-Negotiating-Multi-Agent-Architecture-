"""HR Agent (hr_agent/2): a committed shift loses a worker; HR covers it by moving a multi-skilled worker (HR-2,
HR-5) and named assignments follow; when even overtime is not enough (HR-3 limits), the rest becomes AT_RISK."""

from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import select

from app.events import channel
from app.events.models import Event
from app.hr_agent import manager as hr, reads
from app.hr_agent.models import Commitment
from app.negotiation.envelope import ResourceType, Terms
from app.simulation.clock import today

WORKERS = [
    {"code": "A1", "name": "Asha", "primary_skill": "ASSEMBLY"},
    {"code": "A2", "name": "Ben", "primary_skill": "ASSEMBLY"},
    {"code": "M1", "name": "Mira", "primary_skill": "SMT", "secondary_skills": ["ASSEMBLY"]},
]


def shift(day, hours) -> Terms:
    return Terms(resource_type=ResourceType.WORKFORCE, resource_ref="ASSEMBLY", quantity=D(hours), unit="h",
                 order_id="PO-1", extra={"hours_by_day": {day.isoformat(): str(hours)}, "allow_overtime": False})


def last_capacity_report(session_factory) -> dict:
    with session_factory() as db:
        event = db.scalars(select(Event).where(Event.event_type == "WorkforceCapacityChanged")
                           .order_by(Event.seq.desc())).first()
        return event.payload


def test_absence_is_covered_by_moving_a_worker_then_overtime_then_at_risk(session_factory, pump, fake_planning):
    planning, request = fake_planning
    with session_factory() as db:
        hr.setup(db, WORKERS)
        day = today(db) + timedelta(days=2)
        request(db, "HR", shift(day, 16), "C-1")  # two assembly workers x 8 h
        db.commit()
    pump([planning])
    with session_factory() as db:
        channel.publish(db, event_type="ProductionOrderReleased", publisher="PLANNING", entity_type="production_order",
                        entity_id="PO-1", entity_version=1, correlation_id="C-1",
                        payload={"production_order_id": "PO-1"})
        db.commit()
    pump([planning])
    with session_factory() as db:
        assert sorted((a["worker"], a["hours"]) for a in reads.assignments_for(db, "PO-1")) == [("A1", "8"), ("A2", "8")]

    with session_factory() as db:  # A1 is absent: Mira (SMT, also ASSEMBLY, free that day) is moved in
        hr.record_absence(db, "ABS-1", "A1", day, day)
        db.commit()
    report = last_capacity_report(session_factory)
    assert report["pools"]["ASSEMBLY"][day.isoformat()] == {"moved": "8", "overtime": "0", "uncovered": "0"}
    with session_factory() as db:
        assert sorted((a["worker"], a["hours"], a["status"]) for a in reads.assignments_for(db, "PO-1")) == [
            ("A1", "8", "REASSIGNED"), ("A2", "8", "PLANNED"), ("M1", "8", "PLANNED")]
        assert db.scalar(select(Commitment.status)) == "ACTIVE"

    with session_factory() as db:  # Mira is absent too: overtime for Ben (max 2 h a day) and 6 h stay uncovered
        hr.record_absence(db, "ABS-2", "M1", day, day)
        db.commit()
    report = last_capacity_report(session_factory)
    assert report["pools"]["ASSEMBLY"][day.isoformat()] == {"moved": "0", "overtime": "2", "uncovered": "6"}
    with session_factory() as db:
        commitment = db.scalar(select(Commitment))
        assert (commitment.status, commitment.missing) == ("AT_RISK", {day.isoformat(): "6"})
