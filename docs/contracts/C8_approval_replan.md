# C8 — Plan Approval, Replanning and the Attempt Counter

## Status

**Status:** DRAFT (2026-09-30), **implemented minimally in Phase 4** — awaiting developer confirmation.
Implementation choices: storage **option B** (audit records, no migration; developer asked to reuse existing
persistence), `ABORT` added to C4 (§5), attempt 2 re-runs the negotiations only (O1 a), no C9 in this cut (O4 open),
split procurement not supported (O5). `SUPERSEDED` is not produced (no C9 events yet).

**Owner:** Project developer

**Depends on:** D8 (what approve does, `docs/DECISIONS.md`), C1 (plan shapes), C4 (COMMIT), C7 (audit).

## Purpose

Defines how a plan reaches the human, what approve and reject do to plan state, the maximum of 2 planning attempts,
and when automatic replanning stops and human intervention is required.

## Scope

- Plan approval states and their transitions.
- Where the approval state and the attempt counter are stored.
- What happens to negotiation sessions and uncommitted agreements when a plan is rejected.
- The approval API request and response shapes.

## Does Not Define

- What approve executes (COMMIT, reservation): **D8**.
- Simulation events that trigger re-evaluation: **C9**.
- Negotiation protocol rules (C4), except the one proposed change in §5.

## Specification

### 1. Confirmed rules this contract implements (`dev_docs/DECISIONS.md`)

- After deterministic validation, the tester approves (execute/commit) or rejects (reconsider/replan) the plan. The
  human is not the planner or negotiator.
- Rejecting a plan automatically triggers Planning to replan; the new plan returns to human approval.
- Maximum 2 planning attempts per order, each with at most one negotiation session of at most 3 rounds per shortage.
- If attempt 2 yields no feasible plan or agreement, automatic replanning stops and human intervention is required. No loops.

### 2. Approval states (proposed)

One **plan attempt** per planning run of an order. Its `approval_status`:

```text
PENDING_NEGOTIATION   shortages still under negotiation (some session outcome is null)
AWAITING_APPROVAL     every shortage has an outcome (AGREEMENT or FAILED) or there is none; shown to the human
APPROVED              human approved; D8 executed
REJECTED              human rejected; attempt closed (a new attempt starts automatically if attempts remain)
HUMAN_INTERVENTION_REQUIRED   attempt 2 rejected, or attempt 2 not feasible: no automatic replanning
SUPERSEDED            closed by a simulation event (C9) that forced re-evaluation
```

Transitions:

```text
PENDING_NEGOTIATION --all outcomes known--> AWAITING_APPROVAL
AWAITING_APPROVAL --approve (only if approvable, §3)--> APPROVED
AWAITING_APPROVAL --reject, attempt 1--> REJECTED  => attempt 2 starts (PENDING_NEGOTIATION or AWAITING_APPROVAL)
AWAITING_APPROVAL --reject, attempt 2--> HUMAN_INTERVENTION_REQUIRED
attempt 2 AWAITING_APPROVAL with a FAILED shortage: approvable = false; the human can only reject
any open attempt --C9 event--> SUPERSEDED  => a new attempt (see open item O4 on the counter)
```

`PlanStatus` in C1 (`DRAFT`, `SHORTAGE`, `VALIDATED`, `INVALID`) stays the deterministic result of the calculation;
`approval_status` is separate (C1 left approval states PENDING for C8).

### 3. Approvable

A plan attempt is approvable only when deterministic validation passes **with every proposed agreement treated as a
scheduled receipt**: every shortage has outcome `AGREEMENT` with `validated = true`, and the re-run validation of the
plan has no violations. A plan with a `FAILED` shortage is never approvable (the shortage stays unresolved, C4 §3).

### 4. Storage (proposed option A)

**Option A (recommended):** new table `planning.plan_attempts` (migration 003, C2 change):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `order_id` | UUID FK → `sales.customer_orders.id` | |
| `attempt_number` | INTEGER NOT NULL | 1 or 2; UNIQUE (`order_id`, `attempt_number`, `superseded_by_event`) |
| `approval_status` | VARCHAR NOT NULL | §2 |
| `plan_status` | VARCHAR NOT NULL | C1 `PlanStatus` at the time of the attempt |
| `negotiation_ids` | JSONB NOT NULL | the sessions of this attempt |
| `decision_reason` | TEXT NULL | the human's optional reason on reject |
| `decided_at` | TIMESTAMPTZ NULL | |
| `superseded_by_event` | UUID NULL FK → `simulation.simulation_events.id` | C9 |
| `created_at` | TIMESTAMPTZ | |

**Option B:** no table; the attempt and approval state are audit records (like `PLAN_CREATED`). Rejected as the
recommendation: audit is append-only history, not current state, and the attempt counter needs a reliable read.

The human's approve/reject is recorded in `audit.decision_audit` as `PLAN_APPROVED` / `PLAN_REJECTED` under the
Planning Agent with `decision.decided_by = "HUMAN"` (C7 open item "how human approval is recorded").

### 5. Sessions on reject (proposed; changes C4)

When an attempt is rejected, its uncommitted `AGREEMENT_PROPOSED` sessions are closed with status `ABORTED`
(an existing C4 end status, today unused), by sender type `APPROVAL_WORKFLOW`. Nothing was reserved, so nothing is
released. Attempt 2 opens **new** sessions for its shortages.

This needs two C4 / service changes:
1. New transition `AGREEMENT_PROPOSED --ABORT (APPROVAL_WORKFLOW)--> ABORTED`. C4 lists `ABORT` as a possible
   extension; alternative: a service-level status update with no message (not recommended: bypasses the protocol).
2. "One session per shortage" becomes "one **open or agreed** session per shortage per attempt": `open_session`
   must allow a new session when the previous one is ended (`ABORTED`, `REJECTED`, `FAILED`) and belongs to an
   earlier attempt.

### 6. API (proposed, C5 per-router)

```text
GET  /plans/{order_id}/attempts                     list attempts with approval_status, approvable, violations
POST /plans/{order_id}/attempts/{n}/approve         -> 200 attempt (APPROVED); 409 if not AWAITING_APPROVAL; 422 BUSINESS_RULE_VIOLATION if not approvable
POST /plans/{order_id}/attempts/{n}/reject  {reason?} -> 200 { rejected attempt, next attempt | null }
```

```json
{
  "order_id": "6f1c0e2a-0000-4000-8000-000000000100",
  "attempt_number": 1,
  "approval_status": "AWAITING_APPROVAL",
  "plan_status": "SHORTAGE",
  "approvable": true,
  "negotiations": [
    { "negotiation_id": "6f1c0e2a-0000-4000-8000-000000000500", "item_id": "6f1c0e2a-0000-4000-8000-000000000001",
      "outcome": "AGREEMENT", "validated": true }
  ],
  "violations": [],
  "attempts_remaining": 1
}
```

Human intervention is a normal 2xx result (C5 §3), `approval_status = "HUMAN_INTERVENTION_REQUIRED"`.

## Open Items

- **O1 — What differs in attempt 2.** Inputs are unchanged after a rejection, so the deterministic plan is the same;
  only the negotiations are re-run (new sessions, the tester may answer differently). Options: (a) that only
  (recommended, simplest); (b) the rejection reason carries a constraint (e.g. exclude a supplier) that Purchasing
  must respect. **Decide.**
- **O2 — Storage:** option A (new table, migration 003) or B (audit only). Recommended A.
- **O3 — C4 change:** `ABORT` from the approval workflow (§5). Needs C4 confirmation before code.
- **O4 — Simulation and the counter:** does a C9 event reset the 2-attempt counter (a new situation) or count toward
  it? Recommended: an event supersedes the open attempt and starts attempt 1 of a new cycle.
- **O5 — Split procurement (P3-01):** scenarios 3 and 4 need more than one supplier for a shortage; not approvable
  today. Decide before scenario tests (with C9).
