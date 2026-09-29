# Decentralized MRPII — Project Status

Describes what is **actually in the repository**, not what is planned. Planned work and its order are in
`dev_docs/implementation_25%/two_developer_roadmap.md`; decisions are in `dev_docs/DECISIONS.md`.

Last updated: 2026-09-30 (Phase 0, branch `dev1/phase-0-contracts`).

## Current phase

**Phase 0 — collaborative architecture and contracts.** No phase gate has been passed yet.
Commit `b1f42da` removed the earlier prototype. No application logic exists.

## Implemented

| Area | State |
| --- | --- |
| Specifications | `dev_docs/` and `dev_docs/implementation_25%/` are complete for the 25% milestone. |
| Decisions | `DECISIONS.md` includes the Phase 0 decisions P0-01 to P0-17. |
| Contracts | Drafts of C1 (domain shapes), C5 (error format) and C6 (agent state) in `docs/contracts/`. C2, C4, C7 (Dev 2) not yet drafted. |
| Coordination | `docs/decisions/phase0_coordination.md` (all items confirmed). |
| Configuration | `backend/requirements.txt` (pinned direct dependencies), `backend/pytest.ini`, root `.env.example`, `backend/app/core/config.py` (database URL, Ollama URL and model). |
| Tests | `backend/tests/core/test_config.py` (settings defaults and environment overrides). |

## Not implemented

Everything in the application:

| Area | State |
| --- | --- |
| Backend code | `backend/app/` has the folder scaffold; apart from `core/config.py` its `.py` files are empty placeholders. The parked Sales/Production/Warehouse agent stubs were removed (P0-01). |
| MRPII core, negotiation, LLM client, agents, A2A, simulation, audit | None (Phases 1–7). |
| Database | None. PostgreSQL on Neon is decided (P0-03); no models or migrations exist (Phase 2). |
| Frontend | None. `frontend/` holds only a README (Phase 2 skeleton). |

## Open decisions

D1 (fixture data), D2, D3, D5–D11, D13 in roadmap Section 14 are still open, plus the C2 sub-choices
for P0-11 and P0-16. See `docs/decisions/phase0_coordination.md`.
