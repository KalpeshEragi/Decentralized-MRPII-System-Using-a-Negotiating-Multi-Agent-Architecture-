"""HR Agent (hr_agent/1-3). Owner of worker-hours per skill pool and day. Deterministic (HR-4); template wording
until the AI steps are switched on (IMP-2).

- `handle_message`: skill-hours negotiations (HF-1 answer order, holds, commits, aborts).
- `on_production_order_released`: named workers (HF-2). `on_production_completed`: free unused later hours.
- `record_absence` / `on_day_started`: absences and their cover (HR-5: reassign -> move -> overtime -> AT_RISK).
- `setup`: the simulated workforce (demo.md §4).

Request terms: resource_type WORKFORCE, resource_ref = skill, quantity = total hours, order_id = production order,
extra = {"hours_by_day": {day: hours}, "allow_overtime": bool}.
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.core.owner_tables import LedgerWriter
from app.events import channel
from app.events.models import Event
from app.hr_agent.models import (Absence, Assignment, AuditLog, Commitment, EventVersion, Hold, HoursLedger,
                                 OvertimeEntry, PoolDay, Worker, WorkerMove)
from app.negotiation import layer
from app.negotiation.envelope import Envelope, Hold as HoldTerms, MessageType as M, ReasonCode, Terms
from app.negotiation.models import Session
from app.simulation.clock import today
from app.simulation.settings import setting

AGENT = "HR"
ZERO = Decimal(0)
LIVE = ("HELD", "COMMITTED")


# -- capacity ----------------------------------------------------------------------------------------------------------


def _absent(db: DbSession, worker_id, day: date) -> bool:
    return db.scalar(select(Absence.absence_id).where(Absence.worker_id == worker_id, Absence.first_day <= day,
                                                      Absence.last_day >= day,
                                                      Absence.status.in_(("PLANNED", "COVERED", "ACTIVE")))) is not None


def _moved(db: DbSession, day: date, **where) -> Decimal:
    query = select(func.coalesce(func.sum(WorkerMove.hours), 0)).where(WorkerMove.day == day,
                                                                       WorkerMove.status.in_(LIVE))
    for column, value in where.items():
        query = query.where(getattr(WorkerMove, column) == value)
    return Decimal(db.scalar(query))


def home_hours(db: DbSession, worker: Worker, day: date) -> Decimal:
    """A worker's hours in their primary pool that day: shift minus hours moved to other pools; 0 if absent."""
    if _absent(db, worker.id, day):
        return ZERO
    return worker.shift_hours - _moved(db, day, worker_id=worker.id)


def _moved_in(db: DbSession, skill: str, day: date) -> Decimal:
    """Hours moved into a pool that day by workers who are present (an absent worker brings nothing)."""
    moves = db.scalars(select(WorkerMove).where(WorkerMove.day == day, WorkerMove.to_skill == skill,
                                                WorkerMove.status.in_(LIVE))).all()
    return sum((m.hours for m in moves if not _absent(db, m.worker_id, day)), ZERO)


def overtime_hours(db: DbSession, skill: str, day: date, worker_id=None) -> Decimal:
    query = select(func.coalesce(func.sum(OvertimeEntry.hours), 0)).where(OvertimeEntry.day == day,
                                                                          OvertimeEntry.status.in_(LIVE))
    query = query.where(OvertimeEntry.skill == skill) if skill else query
    query = query.where(OvertimeEntry.worker_id == worker_id) if worker_id else query
    return Decimal(db.scalar(query))


def pool_day(db: DbSession, skill: str, day: date, lock: bool = True) -> PoolDay:
    row = db.get(PoolDay, (skill, day), with_for_update=lock)
    if row is None:
        row = PoolDay(skill=skill, day=day, committed_hours=ZERO, held_hours=ZERO, version=0)
        db.add(row)
        db.flush()
    return row


def capacity(db: DbSession, skill: str, day: date) -> Decimal:
    workers = db.scalars(select(Worker).where(Worker.primary_skill == skill)).all()
    return sum((home_hours(db, w, day) for w in workers), ZERO) + _moved_in(db, skill, day) + overtime_hours(db, skill, day)


def free(db: DbSession, skill: str, day: date) -> Decimal:
    row = pool_day(db, skill, day, lock=False)
    return capacity(db, skill, day) - row.committed_hours - row.held_hours


def _overtime_room(db: DbSession, worker: Worker, day: date, planned: dict) -> Decimal:
    if _absent(db, worker.id, day):
        return ZERO
    per_day = Decimal(str(setting(db, "overtime_max_hours_per_day")))
    per_week = Decimal(str(setting(db, "overtime_max_hours_per_week")))
    monday = day - timedelta(days=day.weekday())
    week = sum((overtime_hours(db, "", monday + timedelta(days=n), worker.id) for n in range(7)), ZERO)
    week += sum(h for (w, d), h in planned.items() if w == worker.id and monday <= d <= monday + timedelta(days=6))
    today_used = overtime_hours(db, "", day, worker.id) + planned.get((worker.id, day), ZERO)
    return max(ZERO, min(per_day - today_used, per_week - week))


def allocate(db: DbSession, skill: str, hours_by_day: dict[date, Decimal], allow_overtime: bool) -> dict | None:
    """Plan how each day's hours are covered: normal pool hours, moved multi-skilled workers (HR-2), then overtime
    (HR-3, only if allowed). Returns {day: {"normal", "moves": [(worker, from, hours)], "overtime": [(worker, hours)]}}
    or None if a day cannot be covered."""
    plan, planned_overtime = {}, {}
    for day, hours in sorted(hours_by_day.items()):
        need = hours - max(ZERO, free(db, skill, day))
        entry = {"normal": min(hours, max(ZERO, free(db, skill, day))), "moves": [], "overtime": []}
        if need > 0:
            for worker in db.scalars(select(Worker).order_by(Worker.code)):
                if need <= 0:
                    break
                if worker.primary_skill == skill or skill not in worker.secondary_skills:
                    continue
                movable = min(home_hours(db, worker, day), max(ZERO, free(db, worker.primary_skill, day)))
                take = min(need, movable)
                if take > 0:
                    entry["moves"].append((worker.id, worker.primary_skill, take))
                    need -= take
        if need > 0 and allow_overtime:
            for worker in db.scalars(select(Worker).where(Worker.primary_skill == skill).order_by(Worker.code)):
                if need <= 0:
                    break
                take = min(need, _overtime_room(db, worker, day, planned_overtime))
                if take > 0:
                    entry["overtime"].append((worker.id, take))
                    planned_overtime[(worker.id, day)] = planned_overtime.get((worker.id, day), ZERO) + take
                    need -= take
        if need > 0:
            return None
        plan[day] = entry
    return plan


def _plan_json(plan: dict) -> dict:
    return {day.isoformat(): {"normal": str(e["normal"]),
                              "moved": str(sum((h for _, _, h in e["moves"]), ZERO)),
                              "overtime": str(sum((h for _, h in e["overtime"]), ZERO))} for day, e in plan.items()}


# -- the answer rule (HF-1) ------------------------------------------------------------------------------------------------


def _hours(terms: Terms) -> dict[date, Decimal]:
    return {date.fromisoformat(d): Decimal(str(h)) for d, h in terms.extra["hours_by_day"].items()}


def _with_hours(terms: Terms, hours: dict[date, Decimal], plan: dict | None, **update) -> Terms:
    extra = {**terms.extra, "hours_by_day": {d.isoformat(): str(h) for d, h in sorted(hours.items())}}
    if plan is not None:
        extra["allocation"] = _plan_json(plan)
    return terms.model_copy(update={"extra": extra, "quantity": sum(hours.values(), ZERO),
                                    "date_from": min(hours), "date_to": max(hours), **update})


def answer(db: DbSession, terms: Terms) -> tuple[M, Terms | None, ReasonCode | None]:
    skill, wanted = terms.resource_ref, _hours(terms)
    allow_overtime = bool(terms.extra.get("allow_overtime", False))
    plan = allocate(db, skill, wanted, allow_overtime)
    if plan is not None:
        return M.OFFER, _with_hours(terms, wanted, plan), None
    for shift in range(1, int(setting(db, "later_date_horizon_days")) + 1):
        later = {d + timedelta(days=shift): h for d, h in wanted.items()}
        plan = allocate(db, skill, later, False)
        if plan is not None:
            return M.COUNTER_OFFER, _with_hours(terms, later, plan), ReasonCode.TOO_LATE
    possible = {}
    for day, hours in wanted.items():
        fits = max(ZERO, free(db, skill, day))
        if fits > 0:
            possible[day] = min(hours, fits)
    if possible:
        return M.COUNTER_OFFER, _with_hours(terms, possible, allocate(db, skill, possible, False)), \
            ReasonCode.NO_WORKFORCE
    return M.REJECT, None, ReasonCode.NO_WORKFORCE


def _reply(db: DbSession, message: Envelope, kind: M, terms: Terms | None = None, reason: ReasonCode | None = None,
           hold: HoldTerms | None = None) -> None:
    text = f"{kind.value.lower()}" + (f": {terms.quantity} h of {terms.resource_ref}" if terms else "") + \
           (f" ({reason.value.lower()})" if reason else "")
    layer.send(db, layer.reply_to(message, kind, terms=terms, reason_code=reason, hold=hold, text=text))


def _change(ledger: LedgerWriter, row: PoolDay, column: str, delta: Decimal, reason: str, **refs) -> None:
    value = getattr(row, column) + delta
    if value < 0:
        raise ValueError(f"{column} of {row.skill} on {row.day} would go below 0")
    setattr(row, column, value)
    row.version += 1
    ledger.write(row.skill, "COMMITTED" if column == "committed_hours" else "HELD", delta, reason, day=row.day, **refs)


# -- inbox ----------------------------------------------------------------------------------------------------------------------


def handle_message(db: DbSession, message: Envelope, session: Session) -> None:
    kind = message.message_type
    if kind in (M.REQUEST, M.COUNTER_OFFER):
        reply_kind, terms, reason = answer(db, message.terms)
        _reply(db, message, reply_kind, terms, reason)
    elif kind == M.ACCEPT and session.status == "NEGOTIATING":
        _place_hold(db, message, session)
    elif kind == M.COMMIT:
        _commit(db, message, session)
    elif kind == M.ABORT:
        _release(db, str(session.id), message.message_id, "HOLD_ABORTED", "ABORTED")


def _place_hold(db: DbSession, message: Envelope, session: Session) -> None:
    offer = Terms.model_validate(session.last_offer)
    skill, hours = offer.resource_ref, _hours(offer)
    plan = allocate(db, skill, hours, bool(offer.extra.get("allow_overtime", False)))
    if plan is None:
        _reply(db, message, M.REJECT, reason=ReasonCode.STALE)
        return
    expires_day = today(db) + timedelta(days=int(setting(db, "hold_validity_days")))
    hold = Hold(skill=skill, production_order_ref=offer.order_id or session.case_id, case_id=session.case_id,
                negotiation_id=str(session.id), lines={d.isoformat(): str(h) for d, h in hours.items()},
                expires_day=expires_day, status="ACTIVE")
    db.add(hold)
    db.flush()
    ledger = LedgerWriter(db, HoursLedger, message.message_id, today(db))
    for day, entry in plan.items():
        for worker_id, from_skill, moved in entry["moves"]:
            db.add(WorkerMove(worker_id=worker_id, from_skill=from_skill, to_skill=skill, day=day, hours=moved,
                              reason="REQUEST", hold_id=hold.id, status="HELD"))
        for worker_id, extra in entry["overtime"]:
            db.add(OvertimeEntry(worker_id=worker_id, skill=skill, day=day, hours=extra, reason="REQUEST",
                                 hold_id=hold.id, status="HELD"))
        db.flush()
        _change(ledger, pool_day(db, skill, day), "held_hours", hours[day], "HOLD", hold=hold.id)
    expires_at = datetime.combine(expires_day, time.min, tzinfo=timezone.utc)
    _reply(db, message, M.AGREEMENT_PROPOSED, offer, hold=HoldTerms(hold_id=str(hold.id), expires_at=expires_at))


def _commit(db: DbSession, message: Envelope, session: Session) -> None:
    hold = db.scalar(select(Hold).where(Hold.negotiation_id == str(session.id)).with_for_update())
    if hold is None or hold.status != "ACTIVE":
        _reply(db, message, M.REJECT, reason=ReasonCode.UNAVAILABLE if hold is None else ReasonCode.HOLD_EXPIRED)
        return
    ledger = LedgerWriter(db, HoursLedger, message.message_id, today(db))
    commitment = Commitment(skill=hold.skill, production_order_ref=hold.production_order_ref, case_id=hold.case_id,
                            hold_id=hold.id, lines=hold.lines, missing={}, status="ACTIVE", version=1)
    db.add(commitment)
    db.flush()
    for day_text, hours_text in hold.lines.items():
        row = pool_day(db, hold.skill, date.fromisoformat(day_text))
        _change(ledger, row, "held_hours", -Decimal(hours_text), "COMMIT", hold=hold.id)
        _change(ledger, row, "committed_hours", Decimal(hours_text), "COMMIT", commitment=commitment.id)
    for model in (WorkerMove, OvertimeEntry):
        for entry in db.scalars(select(model).where(model.hold_id == hold.id)):
            entry.status = "COMMITTED"
    hold.status = "COMMITTED"
    channel.publish(db, event_type="WorkforceCommitted", publisher=AGENT, entity_type="workforce_commitment",
                    entity_id=str(commitment.id), entity_version=1, correlation_id=hold.case_id,
                    payload={"commitment_id": str(commitment.id), "skill": hold.skill,
                             "production_order_id": hold.production_order_ref, "hours_by_day": hold.lines})
    _reply(db, message, M.ACCEPT)


def _release(db: DbSession, negotiation_id: str, source_id: str, reason: str, status: str) -> None:
    hold = db.scalar(select(Hold).where(Hold.negotiation_id == negotiation_id).with_for_update())
    if hold is None or hold.status != "ACTIVE":
        return
    ledger = LedgerWriter(db, HoursLedger, f"{source_id}:{hold.id}", today(db))
    for day_text, hours_text in hold.lines.items():
        _change(ledger, pool_day(db, hold.skill, date.fromisoformat(day_text)), "held_hours", -Decimal(hours_text),
                reason, hold=hold.id)
    for model in (WorkerMove, OvertimeEntry):
        for entry in db.scalars(select(model).where(model.hold_id == hold.id)):
            entry.status = "RELEASED"
    hold.status = status


# -- named assignment (HF-2) --------------------------------------------------------------------------------------------


def _assigned(db: DbSession, worker_id, day: date) -> Decimal:
    return Decimal(db.scalar(select(func.coalesce(func.sum(Assignment.hours), 0)).where(
        Assignment.worker_id == worker_id, Assignment.day == day, Assignment.status.in_(("PLANNED", "WORKED")))))


def _assignable(db: DbSession, worker: Worker, skill: str, day: date) -> Decimal:
    if _absent(db, worker.id, day):
        return ZERO
    base = home_hours(db, worker, day) if worker.primary_skill == skill else \
        _moved(db, day, worker_id=worker.id, to_skill=skill)
    return max(ZERO, base + overtime_hours(db, skill, day, worker.id) - _assigned(db, worker.id, day))


def _assign_day(db: DbSession, commitment: Commitment, day: date, hours: Decimal) -> Decimal:
    """HF-2: fewest assigned hours that day first, primary-skill workers before moved-in ones, ties by code.
    Returns the hours that could not be assigned."""
    candidates = [w for w in db.scalars(select(Worker)) if w.primary_skill == commitment.skill or
                  commitment.skill in w.secondary_skills]
    candidates.sort(key=lambda w: (_assigned(db, w.id, day), w.primary_skill != commitment.skill, w.code))
    remaining = hours
    for worker in candidates:
        take = min(remaining, _assignable(db, worker, commitment.skill, day))
        if take > 0:
            db.add(Assignment(commitment_id=commitment.id, worker_id=worker.id, day=day, hours=take,
                              status="PLANNED"))
            db.flush()
            remaining -= take
        if remaining <= 0:
            break
    return remaining


def on_production_order_released(db: DbSession, event: Event) -> None:
    if not channel.is_newer(db, EventVersion, event):
        return
    for commitment in db.scalars(select(Commitment).where(
            Commitment.production_order_ref == event.payload["production_order_id"],
            Commitment.status.in_(("ACTIVE", "AT_RISK")))):
        for day_text, hours_text in sorted(commitment.lines.items()):
            _assign_day(db, commitment, date.fromisoformat(day_text), Decimal(hours_text))


def on_production_completed(db: DbSession, event: Event) -> None:
    """Free committed hours of days after the completion day; the commitment is DONE."""
    if not channel.is_newer(db, EventVersion, event):
        return
    finished = date.fromisoformat(event.payload["completion_day"])
    ledger = LedgerWriter(db, HoursLedger, str(event.event_id), today(db))
    for commitment in db.scalars(select(Commitment).where(
            Commitment.production_order_ref == event.payload["production_order_id"],
            Commitment.status.in_(("ACTIVE", "AT_RISK")))):
        for day_text, hours_text in commitment.lines.items():
            day = date.fromisoformat(day_text)
            if day > finished:
                _change(ledger, pool_day(db, commitment.skill, day), "committed_hours", -Decimal(hours_text),
                        "COMPLETED_EARLY", commitment=commitment.id)
        commitment.status = "DONE"


# -- absences (HR-5) -------------------------------------------------------------------------------------------------------


def record_absence(db: DbSession, absence_id: str, worker_code: str, first_day: date, last_day: date,
                   reason: str | None = None) -> str:
    """Absence input (simulator). 'duplicate' if already known. Covered at once (HR-5), also when it lies in the
    future: a known absence already leaves those days' commitments short."""
    if db.get(Absence, absence_id) is not None:
        return "duplicate"
    worker = db.scalar(select(Worker).where(Worker.code == worker_code))
    if worker is None or last_day < first_day:
        raise ValueError("unknown worker or wrong dates")
    db.add(Absence(absence_id=absence_id, worker_id=worker.id, first_day=first_day, last_day=last_day,
                   reason=reason, status="PLANNED"))
    db.flush()
    if last_day >= today(db):
        _apply_absence(db, db.get(Absence, absence_id), source_id=absence_id)
    return "received"


def _apply_absence(db: DbSession, absence: Absence, source_id: str) -> None:
    absence.status = "ACTIVE" if absence.first_day <= today(db) else "COVERED"
    worker = db.get(Worker, absence.worker_id)
    skill = worker.primary_skill
    report = {"worker": worker.code, "pools": {}, "at_risk": []}  # pools[skill][day] = how it was covered
    day = max(absence.first_day, today(db))
    while day <= absence.last_day:
        # every pool the worker was working in that day: home pool and pools they were moved into
        pools = {skill} | {m.to_skill for m in db.scalars(select(WorkerMove).where(
            WorkerMove.worker_id == worker.id, WorkerMove.day == day, WorkerMove.status.in_(LIVE)))}
        for pool in sorted(pools):
            cover = _cover_day(db, worker, pool, day, source_id, report)
            if pool == skill or any(v != "0" for v in cover.values()):
                report["pools"].setdefault(pool, {})[day.isoformat()] = cover
        day += timedelta(days=1)
    row = pool_day(db, skill, max(absence.first_day, today(db)))
    row.version += 1
    channel.publish(db, event_type="WorkforceCapacityChanged", publisher=AGENT, entity_type="skill_pool",
                    entity_id=skill, entity_version=int(db.scalar(select(func.sum(PoolDay.version)).where(
                        PoolDay.skill == skill))), correlation_id=f"absence-{absence.absence_id}",
                    payload=report)
    db.add(AuditLog(actor="SYSTEM", event_type="ABSENCE_COVERED", case_id=None, details=report))


def _cover_day(db: DbSession, absent: Worker, skill: str, day: date, source_id: str, report: dict) -> dict:
    """Reassign the absent worker's hours, then move workers in, then overtime (HR decides, HR-5); the rest AT_RISK."""
    row = pool_day(db, skill, day)
    need = row.committed_hours + row.held_hours - capacity(db, skill, day)
    cover = {"moved": "0", "overtime": "0", "uncovered": "0"}
    if need > 0:
        moved = ZERO
        for worker in db.scalars(select(Worker).order_by(Worker.code)):
            if need <= 0:
                break
            if worker.primary_skill == skill or skill not in worker.secondary_skills:
                continue
            take = min(need, home_hours(db, worker, day), max(ZERO, free(db, worker.primary_skill, day)))
            if take > 0:
                db.add(WorkerMove(worker_id=worker.id, from_skill=worker.primary_skill, to_skill=skill, day=day,
                                  hours=take, reason="ABSENCE_COVER", status="COMMITTED"))
                db.flush()
                need -= take
                moved += take
        extra = ZERO
        for worker in db.scalars(select(Worker).where(Worker.primary_skill == skill).order_by(Worker.code)):
            if need <= 0:
                break
            take = min(need, _overtime_room(db, worker, day, {}))
            if take > 0:
                db.add(OvertimeEntry(worker_id=worker.id, skill=skill, day=day, hours=take, reason="ABSENCE_COVER",
                                     status="COMMITTED"))
                db.flush()
                need -= take
                extra += take
        cover.update(moved=str(moved), overtime=str(extra))
    if need > 0:
        cover["uncovered"] = str(need)
        _mark_at_risk(db, skill, day, need, report)
    for assignment in db.scalars(select(Assignment).where(Assignment.worker_id == absent.id, Assignment.day == day,
                                                          Assignment.status == "PLANNED")).all():
        assignment.status = "REASSIGNED"
        db.flush()
        _assign_day(db, db.get(Commitment, assignment.commitment_id), day, assignment.hours)
    return cover


def _mark_at_risk(db: DbSession, skill: str, day: date, uncovered: Decimal, report: dict) -> None:
    """Walk the day's commitments in start-day order (then commit time); the last ones become AT_RISK."""
    commitments = [c for c in db.scalars(select(Commitment).where(Commitment.skill == skill,
                                                                  Commitment.status.in_(("ACTIVE", "AT_RISK"))))
                   if day.isoformat() in c.lines]
    commitments.sort(key=lambda c: (min(c.lines), c.created_at), reverse=True)
    for commitment in commitments:
        if uncovered <= 0:
            break
        missing = min(uncovered, Decimal(commitment.lines[day.isoformat()]))
        commitment.missing = {**commitment.missing, day.isoformat(): str(missing)}
        commitment.status, commitment.version = "AT_RISK", commitment.version + 1
        report["at_risk"].append({"commitment_id": str(commitment.id),
                                  "production_order_id": commitment.production_order_ref,
                                  "day": day.isoformat(), "missing_hours": str(missing)})
        uncovered -= missing


# -- day start, setup, registration ------------------------------------------------------------------------------------


def on_day_started(db: DbSession, event: Event) -> None:
    """HB-3: expire holds, start/end absences (with cover), mark yesterday's assignments worked."""
    day = date.fromisoformat(event.payload["date"])
    for hold in db.scalars(select(Hold).where(Hold.status == "ACTIVE", Hold.expires_day <= day)).all():
        session = db.get(Session, uuid.UUID(hold.negotiation_id))
        _release(db, hold.negotiation_id, str(event.event_id), "HOLD_EXPIRED", "EXPIRED")
        if session is not None and session.status == "AGREEMENT_PROPOSED":
            layer.send(db, Envelope(message_id=str(uuid.uuid4()), session_id=str(session.id), case_id=session.case_id,
                                    sender=AGENT, receiver=session.starter, message_type=M.REJECT,
                                    reason_code=ReasonCode.HOLD_EXPIRED, text="hold expired",
                                    sent_at=datetime.now(timezone.utc)))
    for absence in db.scalars(select(Absence).where(Absence.status == "PLANNED", Absence.first_day <= day)).all():
        _apply_absence(db, absence, source_id=f"{event.event_id}:{absence.absence_id}")  # not covered before
    for absence in db.scalars(select(Absence).where(Absence.status == "COVERED", Absence.first_day <= day)).all():
        absence.status = "ACTIVE"  # covered when it was reported
    for absence in db.scalars(select(Absence).where(Absence.status == "ACTIVE", Absence.last_day < day)).all():
        absence.status = "ENDED"
    for assignment in db.scalars(select(Assignment).where(Assignment.status == "PLANNED", Assignment.day < day)):
        assignment.status = "WORKED"


def setup(db: DbSession, workers: list[dict]) -> None:
    """The simulated workforce: [{code, name, primary_skill, secondary_skills, shift_hours}] (upsert by code)."""
    for data in workers:
        worker = db.scalar(select(Worker).where(Worker.code == data["code"]))
        if worker is None:
            worker = Worker(code=data["code"])
            db.add(worker)
        worker.display_name = data.get("name", data["code"])
        worker.primary_skill = data["primary_skill"]
        worker.secondary_skills = list(data.get("secondary_skills", []))
        worker.shift_hours = Decimal(str(data.get("shift_hours", 8)))
    db.flush()


def register(runner_register) -> None:
    runner_register(layer.register_inbox(AGENT, handle_message))
    channel.subscribe(AGENT, "SimulatedDayStarted", on_day_started)
    channel.subscribe(AGENT, "ProductionOrderReleased", on_production_order_released)
    channel.subscribe(AGENT, "ProductionCompleted", on_production_completed)
