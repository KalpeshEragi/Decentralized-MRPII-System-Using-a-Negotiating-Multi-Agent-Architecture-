# HR Agent: Database Design

**Status:** APPROVED by the developer (2026-10-17). Nothing here is created or migrated.
**Database:** PostgreSQL on Neon (`DATABASE_URL`; tests use `TEST_DATABASE_URL`).
**Schema:** `hr` (owned by HR; new, no old tables).
**Related:** `1_hr_agent_high_level_architecture.md`, `2_hr_agent_functions.md`, `3_hr_agent_backend.md`,
`../architecture/quantity_accounting.md` (§7 capacity rule, §8 ledger).

## 1. Ground rules

1. HR writes only the `hr` schema. Production orders are referenced by Planning's ids only.
2. Workers are **simulated and fictional**: a code and a display name, skills and a calendar; no real personal data,
   no pay or contract fields (HD-2).
3. Worker-hours are a per-day resource: one balance row per skill pool and day, created when first needed (HD-1).
4. Every change is a ledger row plus a balance update in one transaction (QA-1).
5. No price, cost or priority. Times UTC; days `DATE`; ids UUID; JSON = JSONB. Statuses enforced by the database.

## 2. Tables

### Workforce

**skills** — code (PK, e.g. ASSEMBLY, SMT) · name

**workers** — id (PK) · code (unique) · display_name (fictional) · primary_skill (FK skills) · default_shift_hours
(default 8) · active

**worker_skills** (secondary skills) — worker_id (FK) · skill (FK). PK (worker_id, skill).

**worker_day_overrides** — worker_id (FK) · day · shift_hours · reason (e.g. DAY_OFF, SHORT_SHIFT). PK (worker_id, day).

**absences** — absence_id (PK) · worker_id (FK) · first_day · last_day · reason · status (PLANNED, ACTIVE, ENDED)

### Pool balance (per skill and day)

**pool_days** — skill (FK) · day · normal_capacity_hours · overtime_hours_added · committed_hours · held_hours ·
version. PK (skill, day). `free = normal_capacity_hours + overtime_hours_added − committed_hours − held_hours`.

**worker_moves** — id (PK) · worker_id (FK) · from_skill · to_skill · day · hours · reason (REQUEST, ABSENCE_COVER) ·
commitment_id

**overtime_entries** — id (PK) · worker_id (FK) · skill · day · hours · reason (REQUEST, ABSENCE_COVER) · commitment_id

### Holds, commitments, assignments

**holds** — id (PK) · skill · production_order_ref · case_id · negotiation_id (unique) · allow_overtime · expires_at ·
status (ACTIVE, COMMITTED, EXPIRED, ABORTED)

**hold_lines** — hold_id (FK) · day · normal_hours · moved_hours · overtime_hours. PK (hold_id, day).

**commitments** — id (PK) · skill · production_order_ref · case_id · hold_id (unique) · status (ACTIVE, AT_RISK, DONE,
RELEASED) · version · created_at · updated_at

**commitment_lines** — commitment_id (FK) · day · hours · missing_hours. PK (commitment_id, day).

**assignments** — id (PK) · commitment_id (FK) · worker_id (FK) · day · hours · overtime_hours · status (PLANNED,
WORKED, REASSIGNED, CANCELLED)

### Ledger and plumbing

**hours_ledger** — id (PK) · skill · day · bucket (CAPACITY, OVERTIME, COMMITTED, HELD) · delta · reason (SETUP,
ABSENCE, ABSENCE_END, MOVE_IN, MOVE_OUT, OVERTIME, HOLD, HOLD_EXPIRED, HOLD_ABORTED, COMMIT, RELEASE, COMPLETED_EARLY)
· worker_id · commitment_id · hold_id · absence_id · source_id · line_no · sim_time · created_at.
Unique (source_id, line_no).

**Queue tables** (`work_items` and any outbox here) use the standard queue shape of `../architecture/system_design.md` §4.2: `scope_key` (the "one at a time" key; `ref` below), `status` adds RUNNING, plus `locked_by`, `locked_until`, `last_error`, `done_at` (SD-1).

**work_items** — id (PK) · kind · ref · payload (JSON) · status (PENDING, DONE, FAILED) · attempts · next_attempt_at ·
created_at (one writer, HB-2)

**event_versions** — entity_type · entity_id · last_version. PK (entity_type, entity_id).

**audit_log** — id (PK) · time · actor (HR_AI, SYSTEM, HUMAN) · event_type (e.g. REQUEST_ANSWERED, COMMITTED,
ASSIGNED, ABSENCE_COVERED, MARKED_AT_RISK, RECONCILE_DIFFERENCE) · case_id · details (JSON)

## 3. Statuses

| Table | Statuses |
| --- | --- |
| absences | PLANNED → ACTIVE → ENDED |
| holds | ACTIVE → COMMITTED; side: EXPIRED, ABORTED |
| commitments | ACTIVE ↔ AT_RISK → DONE; side: RELEASED |
| assignments | PLANNED → WORKED; side: REASSIGNED, CANCELLED |

## 4. How balances relate to records (checked by reconcile)

| Balance | Equals |
| --- | --- |
| `normal_capacity_hours` | Σ shift hours of workers whose primary skill is the pool that day (overrides applied) − absent workers' hours + moved-in hours − moved-out hours |
| `overtime_hours_added` | Σ `overtime_entries.hours` for the pool and day |
| `committed_hours` | Σ `commitment_lines.hours` of ACTIVE / AT_RISK commitments for the pool and day |
| `held_hours` | Σ hold line hours of ACTIVE holds |
| every balance | Σ of its ledger deltas |

Overtime limits are checked from `overtime_entries`: per worker per day ≤ 2 h, per worker per Monday–Sunday week ≤ 8 h
(configurable, HR-3).

## 5. Rules the database enforces

- Hours ≥ 0; `missing_hours ≤ hours`; `last_day ≥ first_day`.
- A move's `to_skill` must be one of the worker's skills (`worker_skills`), and differ from `from_skill`.
- Unique (source_id, line_no) in the ledger; unique `negotiation_id` on holds; one commitment per hold; unique
  `absence_id`.
- Status values only from §3.

"Fits every day", the overtime limits, and "a worker is never assigned more than shift + allowed overtime" are checked
by code under the single writer (HB-2).

## 6. Decisions recorded

| ID | Decision |
| --- | --- |
| HD-1 | One balance row per skill pool and day (`pool_days`), created when first needed; moves and overtime are their own records; QA-1 ledger. |
| HD-2 | Workers are simulated and fictional: code, display name, skills, calendar; no real personal data, pay or contract fields. |

## 7. Open

| ID | Question |
| --- | --- |
| HD-O1 | Resolved 2026-10-17: Factory A defaults in `demo.md` §4.1. |
| HD-O2 | Resolved 2026-10-17: cleared on reset; kept in the run report (DM-4). |
