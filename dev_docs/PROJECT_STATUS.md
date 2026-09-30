# Decentralized MRPII — Project Status

Describes what is **actually in the repository**, not what is planned. Planned work and its order are in
`dev_docs/implementation_25%/single_developer_roadmap.md` (single developer since 2026-09-30). Decisions: summary in `dev_docs/DECISIONS.md`, detailed record in
`docs/DECISIONS.md`.

Last updated: 2026-09-30.

## Current phase

**Phase 0 — foundation and decisions. Gate NOT passed.** No application logic exists.
Commit `b1f42da` removed the earlier prototype. Phase 1 must not start until the gate items below are closed.

## Implemented

| Area | State |
| --- | --- |
| Specifications | `dev_docs/` and `dev_docs/implementation_25%/`, including the three agent architecture docs (aligned with P0-02, no cost/price). |
| Decisions | P0-01 to P0-17 confirmed (`dev_docs/DECISIONS.md` summary, `docs/DECISIONS.md` detail). Phase 1 prerequisites: P1-02, P1-03, P1-04, P1-08 confirmed; P1-05, P1-07 (except supplier-message storage) and the `COMMIT` ownership rule confirmed; P1-01 fixture proposed; P1-06 open. |
| Contracts (`docs/contracts/`) | C1, C2, C5, C6, C7 CONFIRMED (open items stay PENDING). C4 CONFIRMED (open items stay PENDING). |
| Configuration | `backend/requirements.txt` (pinned direct dependencies), `backend/pytest.ini`, root `.env.example` (Neon `DATABASE_URL` placeholder), `backend/app/core/config.py`. |
| Tests | `backend/tests/core/test_config.py` (settings), `backend/tests/contracts/test_contract_examples.py` (contract JSON examples parse, no cost/price keys). |

## Phase 1 and Phase 2 code (written, mostly not yet executed)

| Area | State |
| --- | --- |
| Phase 1 | `schemas/`, `mrpii/` (finished-goods netting, MPS, MRP, capacity, validator, supplier feasibility), `negotiation/` (state machine, 3 rounds, REJECTED / FAILED, COMMIT only from the approval workflow), `llm/` (Ollama client, structured-output validation), X1 fixture. Tests and `scripts/verify_phase1.py` written; **not executed**. |
| Phase 2 | 24-table ORM, migrations 001 / 002, X1 seed / reset, services, orders / plans / negotiations API (C5 errors), negotiation persistence, audit writes, A2A transport spike (three endpoints, same app), Agents SDK + Ollama spike. **Executed so far:** module import checks, route listing, and offline HTTP calls (health, agent cards, validation error format, a refused A2A envelope). **Not executed:** migrations, seed, any database code, the DB tests, a live Ollama call. |
| Working values | See `docs/DECISIONS.md` P2-01 ("Working values, not yet decided"). |

## Not implemented

| Area | State |
| --- | --- |
| Agents, agent orchestration, simulation / Scenario Manager, approval workflow (C8) | None (Phases 3-4). |
| Frontend | None. `frontend/` holds only a README (Phase 5). |

## Open Phase 0 gate items

1. Approve the SmartPhone X1 fixture (P1-01) and write it to `docs/`.
2. Merge by PR, tag `phase-0`, tick roadmap §1.
