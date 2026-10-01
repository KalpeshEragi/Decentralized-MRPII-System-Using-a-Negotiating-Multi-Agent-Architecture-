# docs/contracts

Contracts for the 25% milestone (see `dev_docs/implementation_25%/single_developer_roadmap.md`, Section 6).

A contract fixes a shape or rule that more than one part of the system depends on (for example the MRPII core,
the services and the agents), so each part can be built and tested against it. Contracts here are **Markdown with
JSON examples**. They are specifications, not code: nothing in this folder is imported or executed.

## Contracts

| # | File | Status | Needed by | Implemented in (planned) |
| --- | --- | --- | --- | --- |
| C1 | `C1_domain.md` — domain data shapes and enums | CONFIRMED (open items stay PENDING) | Phase 1 | `backend/app/schemas/domain.py`, `backend/app/mrpii/` |
| C2 | `C2_database_schema.md` — database schema subset and migration order | CONFIRMED (open items stay PENDING) | Phase 2 | `backend/app/models/`, `backend/alembic/` |
| C4 | `C4_negotiation_protocol.md` — negotiation envelope, offer terms, message types, statuses | CONFIRMED (open items stay PENDING) | Phase 1 | `backend/app/schemas/negotiation.py`, `backend/app/negotiation/` |
| C5 | `C5_errors.md` — API error format (per-router API models added from Phase 2) | CONFIRMED | Phase 2 | `backend/app/core/`, `backend/app/api/` |
| C6 | `C6_agent_state.md` — agent state JSON shapes | CONFIRMED (`OfferTerms` fields follow C4 §5) | Phase 3 | Phase 2 ORM (`agent.agent_state`), Phase 3 `backend/app/agents/base` |
| C7 | `C7_audit_record.md` — audit record shape | CONFIRMED (open items stay PENDING, needed by Phase 3) | Phase 3 | Phase 2 audit service, Phase 3 agents, Phase 5 decision log |
| C8 | `C8_approval_replan.md` — plan approval states, attempt counter, reject → replan | DRAFT | Phase 4 | Phase 4 approval service and API |
| C9 | `C9_simulation_events.md` — simulation event types and parameters | DRAFT | Phase 4 | Phase 4 `backend/app/simulation/` |

C3 (service signatures) is written when needed. D8 (what approve does) is `docs/DECISIONS.md` P4-01 (PROPOSED).

C2, C4 and C7 use the sections Status, Purpose, Scope, Does Not Define, Specification. C1, C5 and C6 use a compact
header followed by the specification. Each contract ends with its open items.

Status values: `DRAFT` (proposal) → `CONFIRMED` (reviewed and agreed by the developer) → `APPLIED` (implemented in code).

## Rules

- A portion marked **PENDING** depends on an open decision (roadmap Section 5, or a `P0-xx` / `P1-xx` item in
  `docs/DECISIONS.md`). Implementation must not guess it.
- Implementation follows the contract. If code needs a different shape, change the contract first (roadmap Section 2).
- Cost/price is out of scope for the 25% milestone and must not appear in any contract.
- Contracts reference each other instead of duplicating shapes (e.g. C6 refers to C4 offer terms).
