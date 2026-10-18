# HR Agent: Backend Design

**Status:** APPROVED by the developer (2026-10-17). Nothing here is implemented.
**Stack:** FastAPI backend, PostgreSQL on Neon.
**Related:** `1_hr_agent_high_level_architecture.md`, `2_hr_agent_functions.md`,
`../warehouse_agent/3_warehouse_agent_backend.md` (same pattern), `../architecture/negotiation.md` §10.

## A. Layers

| # | Layer | Job |
| --- | --- | --- |
| 1 | API doors | A2A endpoint; simulator input (workers, calendars, absences); read-only view doors |
| 2 | HR manager | Work queue with **one writer** (HB-2); the daily routine (HB-3) |
| 3 | Rules | Answer rule (HF-1), assignment (HF-2), absence cover (HR-5), overtime limits (HR-3) |
| 4 | Calculation | Pure functions from `2_hr_agent_functions.md` §4.1 |
| 5 | AI wording | Negotiation wording only (HR-4) |
| 6 | Data access | The only code that reads and writes the `hr` schema |
| 7 | Read module | `reads.py`: `free_worker_hours`, `overtime_room`, `assignments_for` (IB-2) |
| 8 | Connectors | Negotiation client (outbox → A2A), AI model, event publisher (outbox), Planning read module |
| Side | Audit, settings, errors | |

**Folder (HB-1):** `backend/app/hr_agent/` with the Sales layout (`manager.py`, `rules.py`, `calc.py`, `agent.py`,
`prompts.py`, `data_access.py`, `reads.py`, `connectors.py`, `api.py`, `models.py`, `views.py`). No old HR code exists.

## B. API doors

| # | Door | Who | Returns |
| --- | --- | --- | --- |
| 1 | `/a2a/hr` | Planning (A2A) | Store and acknowledge |
| 2 | `POST /hr/absences` | Simulator (key) | `202` received / duplicate (by `absence_id`) |
| 3 | `POST /hr/setup` | Simulator configuration (key) | Workers, skills, calendars for a run (with `demo.md`) |
| 4 | `GET /hr/pools/{skill}?from=&to=` | Team, demo | Capacity, committed, held, free, overtime used per day |
| 5 | `GET /hr/workers/{worker_id}` | Team, demo | Skills, calendar, absences, assignments |
| 6 | `GET /hr/production-orders/{id}/assignments` | Team, demo | Named workers per day |
| 7 | `GET /hr/ledger?skill=&from=&to=` | Team, demo | Ledger rows |
| 8 | `POST /hr/maintenance/reconcile` | Us | Balances vs ledger; reports only |

## C. Functions (plumbing)

**Manager:** `handle_negotiation_message`; `handle_event` (records a work item); `accept_absence` (door 2);
`process_work` (the single writer); `run_day` (HB-3); `answer_request`; `commit_hold`; `assign_named`;
`apply_absence`; `free_after_completion`; `reconcile`.

**Connectors:** `negotiation_client` (outbox); `ai_connector` (timeout, one retry, template); `publish` (event outbox);
Planning read module (production order days and steps).

## D. Flows

1. **Skill-hours request:** A2A stored and acknowledged → work item → HF-1 → reply through the outbox.
2. **Hold, commit, abort, expiry:** as in the other owners; commit → `WorkforceCommitted`.
3. **Production order released:** `ProductionOrderReleased` → `assign_named` (HF-2).
4. **Absence reported:** door 2 stores it → if it starts today or earlier, `apply_absence` at once; otherwise on its
   first day → HR-5 cover → `WorkforceCapacityChanged`.
5. **Daily routine** on `SimulatedDayStarted` (HB-3), in this order:
   1. expire holds;
   2. start absences beginning today (with HR-5 cover); end absences finishing yesterday;
   3. mark yesterday's assignments WORKED and release unused committed hours of finished orders.
6. **Production completed early:** `ProductionCompleted` → `free_after_completion`.

## E. Data shapes

- **Skill-hours request terms:** `resource_type = WORKFORCE`, **skill**, **days with hours per day**, **production
  order**, **case_id**, **allow_overtime**, `facts_version`.
- **Offer terms:** per day: normal hours, moved hours (which workers), overtime hours.
- **Absence input:** **absence_id**, **worker_id**, **first day**, **last day**, reason (free text, simulated).
- **`WorkforceCommitted` payload:** production order, skill, days with hours, commitment id.
- **`WorkforceCapacityChanged` payload:** skill, days, old and new capacity, how it was covered (reassigned, moved,
  overtime hours), AT_RISK commitments with missing hours.

## F. Concurrency (HB-2)

- All HR writes run through one worker, one work item at a time; reads run in parallel.
- Each write is one transaction (ledger + balance + outbox event) under row locks, so a later split needs no data
  change (split by skill pool with a fixed lock order by skill code).
- AI wording runs after the decision is saved.

## G. Errors and tests

| Situation | What we do | Test |
| --- | --- | --- |
| Same absence posted twice | Duplicate, nothing repeated | Post twice |
| Absence for a worker with a named assignment | Reassign / move / overtime (HR-5), else AT_RISK | Absence on day 13 of the research example |
| Overtime limit reached | No more overtime; counter or AT_RISK | Several orders in one week |
| Move would uncover the home pool | Not done | Multi-skilled worker already committed |
| Repeated event / message | No second ledger row | Replay |
| Restart in the middle of the daily routine | Each step is its own work item | Kill during `run_day` |

Plus the tests in `2_hr_agent_functions.md` §11.

## H. Decisions recorded

| ID | Decision |
| --- | --- |
| HB-1 | New folder `backend/app/hr_agent/` with the Sales layout. |
| HB-2 | One writer for all HR changes; reads in parallel; split by skill pool only if measurements show waiting. |
| HB-3 | Daily routine on `SimulatedDayStarted`: expire holds → start/end absences (with cover) → mark worked assignments and free unused hours. |

## I. Open

| ID | Item |
| --- | --- |
| HB-O1 | Resolved 2026-10-17: setup through `POST /hr/setup` while the run is CONFIGURING; reset by restoring a state (`demo.md` §4, §5, DM-2). |
| HB-O2 | Resolved 2026-10-17: DM-5. |
