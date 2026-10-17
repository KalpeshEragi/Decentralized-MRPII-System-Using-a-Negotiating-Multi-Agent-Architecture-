# HR Agent: Agent Design (Role, Rules, Methods, Functions)

**Status:** APPROVED by the developer (2026-10-17). Nothing here is implemented.
**Related:** `1_hr_agent_high_level_architecture.md` (boundary, HR-1 to HR-5),
`../architecture/quantity_accounting.md` §7, `../planning_agent/2_planning_agent_functions.md` (PL-6 ranking).

## 1. Role

The factory's workforce keeper. It knows who can work which skill on which day, promises worker-hours only once,
assigns named workers when production is released, keeps its promises after absences with its own means, and reports
what it cannot keep.

## 2. Instructions (rules it must follow)

- Every check: `free = capacity − committed − held` per skill pool and day; every requested day must fit.
- Capacity = Σ shift hours of the workers in the pool that day − absences + workers moved in − workers moved out.
- Overtime only within the limits, and in counter-offers only when the request allows it (HF-1).
- Move a worker only into a skill they hold, only with their free hours, never breaking another commitment (HR-2).
- Never cancel a commitment on its own; mark it AT_RISK and report (HR-5).
- No pay, cost or real personal data.

## 3. Methods (all deterministic, HR-4)

| # | Method |
| --- | --- |
| 1 | Answer a skill-hours request: OFFER, COUNTER_OFFER (HF-1) or REJECT |
| 2 | Place, commit, release and expire holds |
| 3 | Assign named workers when a production order is released (HF-2) |
| 4 | Apply an absence and keep commitments: reassign → move → overtime → AT_RISK (HR-5) |
| 5 | Free hours when production finishes early |
| 6 | Reconcile hours balances with the ledger |

The AI only turns code-computed terms and reason codes into short negotiation wording.

## 4. Functions

### 4.1 Calculation (pure)

| Function | Input | Output |
| --- | --- | --- |
| `pool_capacity` | Workers, calendars, absences, moves, skill, day | Hours available in the pool |
| `free_hours` | Pool capacity, commitments, holds | Free hours per day |
| `movable_workers` | Skill, day, other pools' free hours | Workers with that secondary skill and free hours |
| `overtime_room` | Workers in the pool, overtime used, limits, day | Overtime hours still allowed that day |
| `counter_terms` | Request, the above, horizon | HF-1 counter-offer |
| `assign_workers` | Committed hours of an order per day, workers in the pool | Named assignment (HF-2) |
| `cover_after_absence` | Commitments of the day, pool after the absence | Plan of reassignments, moves, overtime; remaining uncovered commitments |

### 4.2 Read module (IB-2)

| Function | Returns |
| --- | --- |
| `free_worker_hours(skill, from, to)` | Free normal hours per day |
| `overtime_room(skill, from, to)` | Overtime hours still allowed per day |
| `assignments_for(production_order)` | Named workers per day |

### 4.3 Actions (one transaction each: ledger + balance + outbox event)

| Action | Effect |
| --- | --- |
| `answer_request` | OFFER / COUNTER_OFFER / REJECT |
| `place_hold` / `commit_hold` / `release` / `expire_holds` | Pool balances; `WorkforceCommitted` on commit |
| `move_worker` | Hours moved between two pools for given days |
| `use_overtime` | Pool capacity + overtime hours; worker's overtime counters |
| `assign_named` | Assignment rows for a released production order |
| `apply_absence` | Capacity −; `cover_after_absence`; AT_RISK; `WorkforceCapacityChanged` |
| `free_after_completion` | Committed hours after the completion day released |
| `reconcile` | Compare balances with ledger sums; report only |

## 5. Decision rules

### 5.1 Answering a request (HF-1)

Request terms: `resource_type = WORKFORCE`, **skill**, **hours per day** for **days**, production order, case,
**allow_overtime** (set by Planning when its alternative uses overtime).

1. Every day fits with normal hours → OFFER.
2. Else, every missing day can be covered on the same day by **moving** multi-skilled workers with free hours →
   OFFER (with the moves).
3. Else, if `allow_overtime` and the rest fits with **overtime** within the limits → OFFER (with overtime hours).
4. Else, the **earliest days** (within the shared 60-day horizon, PL-7) where the full hours fit with normal hours (and
   moves) → COUNTER_OFFER.
5. Else, the **most hours** that fit on the requested days → COUNTER_OFFER.
6. Else → REJECT, reason `NO_WORKFORCE`.

Every offer says how many hours are normal, moved and overtime, so Planning's ranking can count extra worker-hours
(PL-6 step 5).

### 5.2 Named assignment at release (HF-2)

For each day of the order's committed hours: pick workers from the pool with the **fewest assigned hours that day**
(spreads the load), preferring workers whose **primary** skill is the pool's skill over moved-in workers; ties by
worker id. A worker is never assigned more than their shift hours plus allowed overtime.

### 5.3 After an absence (HR-5, decided: HR may use overtime itself)

For the absence days, in order: reassign within the pool → move multi-skilled workers with free hours → overtime
within the limits. Commitments still uncovered are walked in start-date order (then commit time), become AT_RISK, and
are listed in one `WorkforceCapacityChanged` (skill, days, old and new capacity, AT_RISK commitments with missing
hours). They return to ACTIVE if hours become free later.

### 5.4 Overtime limits (HR-3)

- Per worker per day: ≤ `overtime_max_hours_per_day` (default 2 h).
- Per worker per week: ≤ `overtime_max_hours_per_week` (default 8 h); "week" = the 7 simulated days Monday–Sunday of
  the simulated calendar.

## 6. The AI step (wording only)

Same as Inventory and Warehouse: message type + code-computed terms + reason code → one or two short sentences; every
number and date must match, else retry once, then a fixed template.

## 7. Statuses

| Record | Statuses |
| --- | --- |
| Hold | ACTIVE → COMMITTED; side: EXPIRED, ABORTED |
| Commitment | ACTIVE ↔ AT_RISK → DONE; side: RELEASED |
| Assignment | PLANNED → WORKED; side: REASSIGNED, CANCELLED |
| Absence | PLANNED → ACTIVE → ENDED |

## 8. Settings (configurable, defaults)

| Setting | Default | Source |
| --- | --- | --- |
| `overtime_max_hours_per_day` | 2 h | HR-3 |
| `overtime_max_hours_per_week` | 8 h | HR-3 |
| Shift length | 8 h, one shift per worker per day | HR-O1 |
| Hold validity | 24 h | NG-2 |
| Counter-offer horizon | 60 days | PL-7 |

## 9. Boundaries (must not do)

- Decide which production step runs when (Planning does).
- Use overtime in a new-request answer unless the request allows it.
- Cancel a commitment on its own.
- Let the AI decide or change any number.

## 10. Decisions recorded

| ID | Decision |
| --- | --- |
| HF-1 | Counter-offer order: normal hours → same-day moves → overtime only if the request allows it → earliest days → most hours that fit; offers state normal, moved and overtime hours. |
| HF-2 | Named assignment at release: fewest assigned hours that day first, primary-skill workers before moved-in workers, ties by worker id. |

## 11. Safeguards and tests

- The research report's assembly example (`quantity_accounting.md` §7.3): normal; one worker absent one day (still
  fits); absent both days (overtime within limits, then AT_RISK for the rest).
- A request with `allow_overtime = false` never receives overtime; with `true`, never more than the limits.
- Moving a worker never uncovers a commitment in their primary pool.
- Weekly overtime limit across several orders.
- Named assignment never exceeds a worker's shift plus allowed overtime.
- Repeated event or message changes nothing; reconcile after every test.
