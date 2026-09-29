# docs/contracts

Shared contracts between Developer 1 and Developer 2 for the 25% milestone
(see `dev_docs/implementation_25%/two_developer_roadmap.md`, Section 8).

A contract fixes a shape or rule that more than one part of the system depends on,
so both developers can build against it in parallel. Contracts here are **Markdown
with JSON examples**. They are specifications, not code: nothing in this folder is
imported or executed.

## Contracts

| # | File | Drafted by | Reviewed by | Status | Implemented in (planned) |
| --- | --- | --- | --- | --- | --- |
| C1 | `C1_domain.md` — domain data shapes and enums | Dev 1 | Dev 2 | DRAFT | Phase 1: `backend/app/schemas/domain.py`, `backend/app/mrpii/` |
| C2 | Database schema subset and migration order | Dev 2 | Dev 1 | not yet drafted | Phase 2: `backend/app/models/`, `backend/alembic/` |
| C4 | Negotiation envelope, offer terms, message types, statuses | Dev 2 | Dev 1 | not yet drafted | Phase 1: `backend/app/schemas/negotiation.py`, `backend/app/negotiation/` |
| C5 | `C5_errors.md` — API error format (per-slice API models come in Phase 3) | Dev 1 | Dev 2 | DRAFT | `backend/app/core/`, `backend/app/api/` |
| C6 | `C6_agent_state.md` — agent state JSON shapes | Dev 1 | Dev 2 | DRAFT | Phase 2 ORM (`agent.agent_state`), Phase 4 `backend/app/agents/base` |
| C7 | Audit record shape | Dev 2 | Dev 1 | not yet drafted | Phase 4 agents, Phase 7 decision log |

C3, C8 and C9 are drafted later, as scheduled in the roadmap.

Status values: `DRAFT` (author's proposal) → `REVIEWED` (other developer explained it back
and agreed) → `STABLE` (merged to `master` at the Phase 0 gate).

## Rules

- A portion marked **PENDING** depends on an open decision (D1–D13 in the roadmap or an
  item in `docs/decisions/phase0_coordination.md`). Implementation must not guess it.
- Implementation follows the contract. If code needs a different shape, change the contract
  first in a small reviewed PR (roadmap Section 8, "Contract rule").
- Cost/price is out of scope for the 25% milestone and must not appear in any contract.
- Contracts reference each other instead of duplicating shapes (e.g. C6 refers to C4 offer terms).
