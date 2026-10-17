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

## Phase 1 and Phase 2 code

| Area | State |
| --- | --- |
| Phase 1 | `schemas/`, `mrpii/`, `negotiation/`, `llm/`, X1 fixture. Tests pass (46 offline tests: Phase 1 plus config and contract examples). |
| Phase 2 | 24-table ORM, migrations 001 / 002 applied to Neon, X1 seed / reset, services, orders / plans / negotiations API (C5 errors), negotiation persistence, audit writes, A2A transport spike (three endpoints, same app), Agents SDK + Ollama spike. Tests pass: 27 tests (DB tests on the Neon `test` branch, HTTP / A2A flow, Agents SDK configuration). |
| Phase 3 (implemented, **tests not run**) | Planning, Inventory and Purchasing Agents (`app/agents/`): C6 state per agent, C7 decision records, Inventory → Purchasing negotiation over the A2A endpoints, supplier interface service (not an agent), Purchasing LLM proposer with deterministic validation and own-policy fallback, requisitions owned by Purchasing, results AGREEMENT / FAILED passed to Planning. Agents API (`/agents/...`, `/supplier-interface/...`). No COMMIT, reservation, approval or replanning (Phase 4). New tests: `tests/agents/`, `tests/db/test_phase3_workflow.py`; script `scripts/verify_phase3.py`. Interim choices: `docs/DECISIONS.md` P3-01. |
| Phase 4 (minimum, **tests not run**) | C8 approval workflow (`approval_service`, not an agent): attempts stored as Planning audit records; approve → `COMMIT` (approval workflow) → re-plan with committed receipts → Inventory reserves stock (D8); reject → `ABORT` of uncommitted agreements → Planning replans as attempt 2 → rejecting attempt 2 gives `HUMAN_INTERVENTION_REQUIRED`. API `/plans/{order_id}/attempts[/n/approve|/n/reject]`. Not done: C9 Scenario Manager / simulation events, requisition `COMMITTED`, split procurement. Tests: `tests/db/test_phase4_approval.py`; script `scripts/verify_phase4.py`. |
| Not verified | A live Ollama call (the Agents SDK / Ollama spike is only checked for configuration); the A2A spike client script against a running server. |
| Working values | See `docs/DECISIONS.md` P2-01 ("Working values, not yet decided"). |

## New Purchasing Agent (branch `purchasing-agent`, 2026-10-17)

Built from scratch per `.scratch/purchasing-agent/spec.md`; legacy agent code and schemas untouched.

| Area | State |
| --- | --- |
| Ticket 01 (tracer) | Done. Migration `004` creates only `supplier_service`, `purchasing_agent`, `negotiation_engine` (own declarative base each). Supplier Service read interface + fixture seed/reset. `POST/GET /purchasing/procurement-requests`: idempotent by `request_ref`, unknown item refused, best **priced single** supplier, one PENDING Leg with price snapshot, one OPEN Engine session (AGENT Purchasing + SUPPLIER, refs validated), template OFFER (quantity + required date, no price), selection audit. Injectable clock, configurable timezone. |
| Interim (until later tickets) | No splits / unpriced fallback (request FAILED instead, no Constrained Quantity), no holds (uses `available_qty`), no contract API, chat, approval or LLM. |
| Tests | `tests/purchasing_agent/`: 6 pure + 4 API tests pass (API run on a local PostgreSQL; the Neon test host did not resolve on 2026-10-17). |

## Not implemented

| Area | State |
| --- | --- |
| Simulation / Scenario Manager (C9), approval workflow and COMMIT (C8), plan update and replanning | None (Phase 4). |
| Frontend | None. `frontend/` holds only a README (Phase 5). |

## Open Phase 0 gate items

1. Approve the SmartPhone X1 fixture (P1-01) and write it to `docs/`.
2. Merge by PR, tag `phase-0`, tick roadmap §1.
