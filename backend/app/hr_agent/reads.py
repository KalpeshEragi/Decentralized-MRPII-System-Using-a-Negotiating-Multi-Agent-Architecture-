"""HR's read module (IB-2): the only thing other agents may import from the HR Agent. Read-only; plain data."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.hr_agent.manager import _overtime_room, free
from app.hr_agent.models import Assignment, Commitment, Worker


def free_worker_hours(db: DbSession, skill: str, start: date, end: date) -> dict[str, str]:
    return {(start + timedelta(days=n)).isoformat(): str(max(0, free(db, skill, start + timedelta(days=n))))
            for n in range((end - start).days + 1)}


def overtime_room(db: DbSession, skill: str, start: date, end: date) -> dict[str, str]:
    workers = db.scalars(select(Worker).where(Worker.primary_skill == skill)).all()
    return {(start + timedelta(days=n)).isoformat():
            str(sum((_overtime_room(db, w, start + timedelta(days=n), {}) for w in workers), 0))
            for n in range((end - start).days + 1)}


def assignments_for(db: DbSession, production_order_id: str) -> list[dict]:
    commitments = db.scalars(select(Commitment).where(Commitment.production_order_ref == production_order_id)).all()
    result = []
    for commitment in commitments:
        for assignment in db.scalars(select(Assignment).where(Assignment.commitment_id == commitment.id)):
            worker = db.get(Worker, assignment.worker_id)
            result.append({"skill": commitment.skill, "worker": worker.code, "day": assignment.day.isoformat(),
                           "hours": str(assignment.hours), "status": assignment.status})
    return result


def commitments_for(db: DbSession, production_order_id: str) -> list[dict]:
    return [{"id": str(c.id), "skill": c.skill, "lines": c.lines, "missing": c.missing, "status": c.status}
            for c in db.scalars(select(Commitment).where(Commitment.production_order_ref == production_order_id))]
