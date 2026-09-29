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
| C1 | `C1_domain_data_shapes.md` — domain data shapes and enums | Dev 1 | Dev 2 | DRAFT | Phase 1: `backend/app/schemas/domain.py`, `backend/app/mrpii/` |
| C2 | `C2_database_schema.md` — database schema subset and migration order | Dev 2 | Dev 1 | DRAFT | Phase 2: `backend/app/models/`, `backend/alembic/` |
| C4 | `C4_negotiation_protocol.md` — negotiation envelope, offer terms, message types, statuses | Dev 2 | Dev 1 | DRAFT | Phase 1: `backend/app/schemas/negotiation.py`, `backend/app/negotiation/` |
| C5 | `C5_api_error_format.md` — API error format (per-slice API models come in Phase 3) | Dev 1 | Dev 2 | DRAFT | `backend/app/core/`, `backend/app/api/` |
| C6 | `C6_agent_state.md` — agent state JSON shapes | Dev 1 | Dev 2 | DRAFT | Phase 2 ORM (`agent.agent_state`), Phase 4 `backend/app/agents/base` |
| C7 | `C7_audit_record.md` — audit record shape | Dev 2 | Dev 1 | DRAFT | Phase 4 agents, Phase 7 decision log |

C3, C8 and C9 are drafted later, as scheduled in the roadmap.

Every contract uses the same sections: Status, Purpose, Scope, Does Not Define, Specification.

Status values: `DRAFT` (author's proposal) → `CONFIRMED` (the other developer reviewed,
explained it back and agreed) → `APPLIED` (implemented in code).

## Rules

- A portion marked **PENDING** depends on an open decision (D1–D13 in the roadmap or a
  `P0-xx` item in `docs/DECISIONS.md`). Implementation must not guess it.
- Implementation follows the contract. If code needs a different shape, change the contract
  first in a small reviewed PR (roadmap Section 8, "Contract rule").
- Cost/price is out of scope for the 25% milestone and must not appear in any contract.
- Contracts reference each other instead of duplicating shapes (e.g. C6 refers to C4 offer terms).
