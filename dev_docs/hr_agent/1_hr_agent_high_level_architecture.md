# HR Agent: High-Level Architecture (System Boundary)

**Status:** APPROVED by the developer (2026-10-17). Nothing here is implemented; there is no HR code or table.
**Scope:** the HR Agent only. Other agents appear as contact points.
**Related:** `../architecture/quantity_accounting.md` §7 (capacity rule, worker-absence example), RD-2 in
`../DECISIONS.md` (machine + worker hours), `../planning_agent/`, `../architecture/negotiation.md`.
Later notes: `2_hr_agent_functions.md`, `3_hr_agent_backend.md`, `4_hr_agent_database.md`.

## 1. Purpose

HR owns the factory's **workforce capacity**: which workers exist, which skills they have, when they work, when they
are absent, and how many worker-hours per skill are free each day. It promises hours only once, assigns named workers
when production is released, keeps its promises when someone is absent if it can, and reports at once when it cannot.

## 2. Inside the HR boundary (HR owns this)

1. Workers, their skills (one primary skill, possibly secondary skills), and their shift calendars.
2. Absences (entered through HR's input from the simulator).
3. Worker-hours per skill pool per day: capacity, committed, held (`quantity_accounting.md` §7).
4. Holds and commitments of skill hours (owner role in negotiations with Planning).
5. Overtime within configurable limits (HR-3).
6. Moving a multi-skilled worker to another skill pool for given days (HR-2).
7. Named worker assignment when a production order is released (HR-1).
8. Keeping commitments after an absence (reassign → move → overtime), and reporting what cannot be kept.
9. The hours ledger and balance (QA-1).

## 3. Outside the boundary

| Item | Owner |
| --- | --- |
| Which production step runs on which day; machine-hours | Planning |
| Warehouse capacity (no workers used, WH-3) | Warehouse |
| Payroll, contracts, real employee data | Out of scope (simulated workforce only) |

## 4. Contact points

| Contact point | Direction | Kind |
| --- | --- | --- |
| Skill-hours requests (REQUEST → OFFER/COUNTER → hold → COMMIT/ABORT) | Planning → HR | Private negotiation (A2A); HR is the owner |
| `free_worker_hours(skill, from, to)`, `assignments_for(order)` | Others → HR | Read module (IB-2) |
| Absences, worker and calendar setup | Simulator → HR input | Input door (trigger travels the normal path, pub-sub §9) |
| Subscribed / published events | §6 | Event channel |
| AI model | HR ↔ shared model | Negotiation wording only (HR-4) |
| Storage | HR ↔ `hr` schema | HR-owned data only |

## 5. How hours are promised

- A request names a skill, days and hours per day (from Planning: `(setup + qty × run time) × crew size`, RD-2).
- Per day: `free = capacity − committed − held`, where capacity = Σ shift hours of workers in that skill's pool that
  day − absences. Every requested day must fit.
- Not enough normal hours → HR may counter-offer with **overtime** (within limits) or with **another day**; it may
  first **move** a multi-skilled worker into the pool for those days if that worker's hours are free (HR-2).
- Hold on agreement (24 h) → `COMMIT` → commitment → `WorkforceCommitted`.
- On `ProductionOrderReleased`, HR assigns named workers to the order's committed hours (HR-1).

## 6. Events

| Subscribes to | Reaction |
| --- | --- |
| `ProductionOrderReleased` | Assign named workers to the committed hours |
| `ProductionCompleted` | Free hours committed for days after completion (if finished early) |
| `SimulatedDayStarted` | Expire holds; apply absences starting today |

| Publishes | When |
| --- | --- |
| `WorkforceCommitted` | Skill hours committed to a production order |
| `WorkforceCapacityChanged` | Capacity of a skill pool changes (absence, worker moved) — lists commitments that could not be kept |

Named assignments are not an event; they are visible through the read module and the view doors.

## 7. Keeping commitments after an absence (HR-5)

When a worker becomes absent, HR tries, in this order, using only its own resources:

1. **Reassign** within the same skill pool (another worker with free hours that day).
2. **Move** a multi-skilled worker with free hours into the pool (HR-2).
3. **Overtime** for workers in the pool, within the limits (HR-3).
4. Otherwise: commitments are walked in start-date order (then commit time); the ones that cannot be covered become
   AT_RISK and are listed in `WorkforceCapacityChanged`; Planning repairs (`quantity_accounting.md` §7.2).

HR never cancels a commitment on its own (same rule as IF-2).

## 8. Rules (write these on the diagram)

1. One worker-hour is promised only once; every day of a request must fit.
2. Hours are committed per skill pool; names are assigned at release.
3. Overtime only within the configured limits; moving a worker only into a skill they hold and only with free hours.
4. HR keeps its commitments with its own means first, then reports; it never cancels on its own.
5. The AI writes wording only; all checks are code.
6. No pay, cost or real personal data.

## 9. Decisions recorded

| ID | Decision |
| --- | --- |
| HR-1 | HR commits hours per skill pool per day; named workers are assigned when the production order is released. |
| HR-2 | Each worker's hours count in their primary skill pool; HR alone may move a worker to another skill they hold for given days, only with free hours and never breaking a commitment. |
| HR-3 | Overtime is offered when normal hours are not enough, within configurable limits (defaults: 2 h per worker per day, 8 h per worker per week). |
| HR-4 | All HR decisions are deterministic; the AI writes negotiation wording only. |
| HR-5 | After an absence HR first reassigns, then moves workers, then uses overtime; what remains uncovered becomes AT_RISK and is reported. |

## 10. Open (for the next notes)

| ID | Question |
| --- | --- |
| HR-O1 | Shift model: one shift per worker per day (default 8 h) is assumed; more shifts only if a scenario needs them. |
| HR-O2 | Resolved 2026-10-17: every simulated day is a working day unless the worker's calendar says otherwise (DM-5). |
| HR-O3 | Decided 2026-10-17: yes, HR may use overtime itself after an absence, within the limits (HR-5 as drafted). |

## 11. Diagram checklist

- One box "HR Agent" with the 9 inside items (§2); skill pools drawn inside with workers.
- Planning → HR: dashed negotiation arrow (skill hours); HR → Planning: `WorkforceCommitted`, `WorkforceCapacityChanged`.
- Simulator → HR input: absences, workers, calendars.
- Planning → HR: `ProductionOrderReleased` (named assignment).
- Simulator clock → HR: `SimulatedDayStarted`.
- Read module: `free_worker_hours`, `assignments_for`.
- AI model: "wording only". `hr` schema with ledger + balance.
- Rules note (§8).
