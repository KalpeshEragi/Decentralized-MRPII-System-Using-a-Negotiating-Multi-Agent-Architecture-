# C7 — Audit Record Shape

## Status

**Status:** CONFIRMED

**Owner:** Project developer

**Reviewed:** 2026-09-30 (see Review)

## Purpose

Defines the shape and rules of the audit records that capture agent decisions for traceability.

## Scope

- The `audit.decision_audit` record.
- Who writes audit records and when.
- What a rationale may contain.
- Which outcomes must be visible through the audit trail.

**Implemented in:** Phase 2 audit service, Phase 3 `backend/app/agents/base` (audit writer), used by all agents; read by the Phase 5 decision-log page.

## Does Not Define

- Negotiation messages, offers and agreements. These are protocol facts persisted in `negotiation.*` (C4).
- Agent state (C6).
- API response models of the decision-log API (C5, Phase 5).
- Table DDL (C2, `database_schema.md`).

## Specification

### 1. Data Shape

`audit.decision_audit` (`database_schema.md` §10):

```text
id                 UUID       PK
agent_id           UUID       FK → agent.agents.id
decision_type      VARCHAR    NOT NULL
context            JSONB      NOT NULL
decision           JSONB      NOT NULL
reasoning_summary  TEXT       NOT NULL
created_at         TIMESTAMP
```

### 2. Rules

1. **Every agent decision is recorded.** Each agent decision writes one `audit.decision_audit` record with agent, type, context, decision and a concise `reasoning_summary` (`system_spec.md` A11).
2. **Own decisions only.** Each agent writes records for its own decisions. Records are append-only (`system_spec.md` §6).
3. **Concise rationale.** `reasoning_summary` stores a concise structured rationale, never hidden chain-of-thought (`database_schema.md` §10, `system_spec.md` P10).
4. **Written through a service.** Audit writes are a deterministic service capability; agents do not write the table directly (`system_spec.md` §4.1).
5. **Outcomes come from agents.** The audit log must show that negotiation outcomes come from agent decisions, not from the engine (`system_spec.md` A7).
6. **Failures are visible.** A `FAILED` negotiation is recorded and visible in the dashboard/decision log (`dev_docs/DECISIONS.md`, Failure).
7. **Invalid LLM output.** Output rejected by deterministic validation is recorded per this contract and never changes business state (C5 §4).
8. **Approval activity.** Approval and activity are recorded through agreement/audit records (`dev_docs/DECISIONS.md`, Purchase orders).
9. **No cost/price** in any field.

### 3. Open Items

- **Working set in Phase 2 (`audit_service.DecisionType`, not final):** `ORDER_RECEIVED`, `PLAN_CREATED` (Planning agent); `SHORTAGE_DETECTED`, `NEGOTIATION_REQUEST`, `AGREEMENT_COMMITTED` (Inventory agent); `NEGOTIATION_MESSAGE`, `AGREEMENT_PROPOSED`, `NEGOTIATION_REJECTED`, `NEGOTIATION_FAILED` (Purchasing agent). `context` carries `order_id` / `item_id` / `negotiation_id`; `PLAN_CREATED.decision` also stores the parts of the plan snapshot that have no table (finished-goods netting, capacity checks, validation, planning date). Supplier-interface responses other than REJECT are not audited (not an agent decision). Phase 3 adds (P3-01):
  `AVAILABILITY_ASSESSED` (Inventory), `REQUISITION_CREATED`, `NEGOTIATION_DECISION` (Purchasing: source LLM / POLICY,
  rationale), `LLM_PROPOSAL_REJECTED` (any agent), `NEGOTIATION_RESULT_RECEIVED` (Inventory, Planning). **PENDING:** the final list.
- **PENDING:** JSON shapes of `context` and `decision`, including how they reference `order_id`, `negotiation_id` and `item_id`.
- **PENDING:** how an invalid LLM output is recorded (its own `decision_type`, or part of the decision it affected).
  Phase 3 working choice: its own `LLM_PROPOSAL_REJECTED` record with the structured proposal (never raw text) and the problems.
- **To confirm:** how human approval and rejection are recorded, since `agent_id` references `agent.agents` and the tester is not an agent (with C8).
- **To confirm:** whether actions of non-agent components (Negotiation Engine, Scenario Manager) are audited here or only in their own tables.

## Review

**Result: CONFIRMED.** The record shape matches `database_schema.md` §10, and the rules (every agent decision recorded,
own decisions only, append-only, concise rationale, written through a service, `FAILED` visible, invalid LLM output
recorded without changing state, no cost/price) match `system_spec.md` and `dev_docs/DECISIONS.md`.
The open items in §3 (`decision_type` values, `context`/`decision` JSON, recording of invalid LLM output, human approval
recording with C8, non-agent components) stay **PENDING**; they are needed by Phase 3 (`agents/base`) and Phase 4 (C8),
not by Phase 1.
