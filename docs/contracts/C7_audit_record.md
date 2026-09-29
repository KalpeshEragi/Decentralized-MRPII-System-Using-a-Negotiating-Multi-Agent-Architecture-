# C7 — Audit Record Shape

## Status

**Status:** DRAFT

**Owner:** Dev 2

**Reviewed By:** Pending (Dev 1)

## Purpose

Defines the shape and rules of the audit records that capture agent decisions for traceability.

## Scope

- The `audit.decision_audit` record.
- Who writes audit records and when.
- What a rationale may contain.
- Which outcomes must be visible through the audit trail.

**Implemented in:** Phase 4 `backend/app/agents/base` (audit writer, paired), used by all agents; read by the Phase 7 decision-log API.

## Does Not Define

- Negotiation messages, offers and agreements. These are protocol facts persisted in `negotiation.*` (C4).
- Agent state (C6).
- API response models of the decision-log API (C5, Phase 7).
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

- **PENDING:** the list of `decision_type` values.
- **PENDING:** JSON shapes of `context` and `decision`, including how they reference `order_id`, `negotiation_id` and `item_id`.
- **PENDING:** how an invalid LLM output is recorded (its own `decision_type`, or part of the decision it affected).
- **To confirm:** how human approval and rejection are recorded, since `agent_id` references `agent.agents` and the tester is not an agent (with C8).
- **To confirm:** whether actions of non-agent components (Negotiation Engine, Scenario Manager) are audited here or only in their own tables.
