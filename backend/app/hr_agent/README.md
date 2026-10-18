# backend/app/hr_agent

The HR Agent (`dev_docs/hr_agent/`): owner of worker-hours per skill pool and day. Deterministic (HR-4); template
wording until the AI steps are switched on (IMP-2). Workers are simulated and fictional (HD-2).

| File | Purpose |
| --- | --- |
| `models.py` | `hr` schema: workers, absences (PLANNED → COVERED → ACTIVE → ENDED), pool days (committed / held hours), worker moves, overtime entries, holds, commitments, named assignments, hours ledger, event versions, audit log. Simplifications against note 4: per-day hours of holds and commitments are JSON `lines`; pool capacity is computed, not stored. |
| `manager.py` | Capacity (shift hours − absences ± moves + overtime; an absent worker brings nothing anywhere), `allocate` (normal → moves (HR-2) → overtime within limits (HR-3, only if the request allows it)), `answer` (HF-1), holds / commits (`WorkforceCommitted`) / aborts, named assignment at release (HF-2), `record_absence` + cover (HR-5: reassign → move → overtime → AT_RISK, `WorkforceCapacityChanged` with a per-pool report), day start (HB-3), early completion, `setup`, `register`. |
| `reads.py` | Read module (IB-2): `free_worker_hours`, `overtime_room`, `assignments_for`, `commitments_for`. |
| `api.py` | `POST /hr/setup`, `POST /hr/absences` (simulator, `X-Door-Key`), `GET /hr/pools/{skill}`, `GET /hr/production-orders/{id}/assignments`. |

A known future absence is covered as soon as it is reported (a known absence already leaves those days short).

**Tests:** `backend/tests/platform/test_hr_agent.py` (absence covered by a move, assignments follow; then overtime
within limits and AT_RISK for the rest).
