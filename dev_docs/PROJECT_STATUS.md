# Project Status

What is **actually in the repository** (branch `purchasing-agent`), not what is planned.
Plan: `ROADMAP.md`. Decisions: `DECISIONS.md`, `adr/`. Doc index: `README.md`.

Last updated: 2026-10-18.

## 1. Summary

| Part | State |
| --- | --- |
| Sales Agent | Implemented (`backend/app/sales_agent/`, schema `sales_agent`, migration `003`). Planning is a fake connector. |
| Purchasing Agent | Implemented standalone, tickets 01–11 done (`backend/app/purchasing_agent/`, schema `purchasing_agent`). Test inputs replace other agents. |
| Supplier Service | Implemented: read-only supplier data (`backend/app/supplier_service/`, schema `supplier_service`) + supplier-facing test chat (Purchasing test channel). **Not an agent.** Docs: `supplier/`. |
| Negotiation Engine | Implemented: shared protocol state only (`backend/app/negotiation_engine/`, schema `negotiation_engine`). Hosts only Purchasing ↔ supplier sessions. |
| Planning, Inventory, Warehouse, HR (new architecture) | Not built. |
| Multi-agent integration | Not built. |
| Shared code used by the new modules | `backend/app/core/` (settings, database, C5 errors) and `backend/app/llm/` (shared Ollama client). |

Migrations `004` (the three new schemas) and `005` (Engine message type `CONFIRMATION`) touch only the new schemas.

## 2. Purchasing Agent: what it can do

Rules: `purchasing_agent/purchasing_agent_architecture.md`. Routes and files: `backend/app/purchasing_agent/README.md`.

| Capability | What is built |
| --- | --- |
| Procurement Requests | `POST/GET /purchasing/procurement-requests`. Idempotent by `request_ref` (same data → existing request, different data → 409). Whole units only. Unknown item refused. |
| Purchasing Contracts | Register and list. Price in INR > 0. An active contract that overlaps another for the same supplier-item → 409. Price on a date: exactly one valid contract; none → Not Registered (never zero); overlap → supplier excluded (`contract_overlap`). |
| Supplier selection | Pure, deterministic code. Options: priced single, Cost-Saving Split (≥ 10% cheaper, configurable), Necessary Split, unpriced fallbacks ("cost ranking unavailable"), or FAILED with the Constrained Quantity. Every option and combination is audited. Price is never negotiated (ADR-002). |
| Effective availability | Supplier quantity minus other requests' holds. Advisory lock per supplier-item, so two requests can't double-book a supplier. Other requests' overdue Legs are timed out before availability is calculated. |
| Supplier chat | Test-channel page with one conversation per Leg. Free text, read by the LLM or a strict fallback parser. Purchasing echoes how it read each reply, then agrees, counters, asks for clarification (max 2) or fails the Leg. Max 3 rounds. A past or late delivery date is never agreed. Duplicate `message_id` is ignored. |
| Splits, reallocation and re-sourcing | A quantity counter-offer caps that supplier and is reallocated among the open Legs; a failed Leg excludes its supplier. If nothing fits, the request is re-sourced over every eligible supplier (threshold re-checked; a dropped supplier may return within its per-request round budget; ADR-003, ticket 12). Only if nothing is feasible does the request fail and cancel the other Legs. |
| Deadlines and abort | 24h response deadline, checked lazily (no scheduler). A Leg past it fails with `timeout`; a read only records it, re-sourcing runs on the next reply or `POST .../re-source`. A tester can abort a request while it is NEGOTIATING (never re-sourced). |
| Approval | A human approves (all Legs COMMITTED in one transaction → scheduled receipts) or rejects (all Legs ABORTED, suppliers told). |
| LLM (shared Ollama client, never required) | Reads supplier replies, rewrites the offer text, explains the selection. Guardrails fall back to the parser, the template or no explanation. **No lock is held during LLM calls** (`wording.py`). A reply to an offer that changed meanwhile → 409 `offer: superseded`. |
| Audit | `decision_audit`: selection, response validation, reallocation, re-sourcing, deadline, approval, manual abort. The LLM explanation is stored apart from the deterministic rationale. |

## 3. Legacy / provisional code

These exist in the repo but are **not part of the new architecture**. They are not verified against it and must not be depended on without approval.

| Code | What it is |
| --- | --- |
| `backend/app/agents/` (planning, inventory, purchasing), `services/`, `negotiation/`, `mrpii/`, `schemas/` | Earlier three-agent prototype: legacy schemas `purchasing` / `negotiation`, legacy approval workflow, A2A spike. |
| `backend/app/services/supplier_service.py` | Legacy supplier lookup (legacy `purchasing` tables). Not the new Supplier Service. The legacy supplier routes and `supplier_interface_service.py` were removed 2026-10-18, so the legacy agent flow stops at its first offer. |
| `backend/app/models/production.py`, `models/machine.py` (empty), `OVERALL_DATABASE_SCHEMA.md` §6 `production` | Legacy placeholders; no migration creates a `production` schema. No Production agent (O-9). |
| `backend/app/simulation/` | Legacy simulation for the SmartPhone X1 flow. |
| `frontend/` | Legacy Next.js demo console for the old X1 flow (its supplier form was removed with the legacy supplier routes). |

## 4. Not built yet

- Planning, Inventory, Warehouse and HR in the new architecture.
- A2A between agents, the Pub/Sub event channel, cross-agent commit, a Warehouse receiving step (WH-1).
- Scenario Manager / supplier disruptions (Invalidated Agreements), replanning.
- RFC 9457 errors (API-1). The backend returns the C5 error body today.
- Contract modification endpoint; using up scheduled receipts (COMMITTED Legs hold supplier quantity indefinitely).

## 5. Known risks

| Risk | Note |
| --- | --- |
| No access control | Approve, reject, abort, contracts and the test channel are open. Test build only; must be added before any real use. |
| Negotiation Engine hard-codes Purchasing | `SESSION_TYPES = PURCHASING_SUPPLIER`, `KNOWN_AGENTS = PURCHASING`. Generalise when other agents use it. |
| Two migrations | `005` is a second migration; the spec said one migration for the new schemas. |
| `message_id` reuse | A `message_id` already used on another Leg → 409 CONFLICT. |
| Brief template text | A supplier may briefly see the template offer before the LLM wording replaces it. |

## 6. Open decisions

Decided 2026-10-18: no separate Production agent; the roster is the six agents of `adr/ADR-001.md` §2 (`DECISIONS.md` O-9).

- Which agent submits Procurement Requests in the integrated system (HA-3).
- Message broker, final event catalogue, A2A contract, priority algorithm, recovery/consistency strategy (`adr/ADR-001.md` §10).

## 7. Tests

Purchasing tests: `backend/tests/purchasing_agent/` (pure tests, plus `db/` API tests that need `TEST_DATABASE_URL`). Run one suite at a time: parallel runs on the shared test DB interfere.

Full purchasing suite (2026-10-18, after ticket 11): **174 passed** in one run, alone on the test DB (`TEST_DATABASE_URL`). An earlier run hit Neon connection drops (503 / setup errors), not code failures. Parallel runs on the same DB interfere.

Live Ollama check (2026-10-18, qwen3.5:4b, Ollama 0.40.6, thinking off via `reasoning_effort: "none"`): N1 ("ok, 500 by
12 Nov works") → AGREEMENT_PROPOSED and N4 (late date) → counter-offer with the required date, both correct; 4–9 s per
model call, ~18 s to submit a request (offer wording + explanation). With thinking on (check run with a raised 300 s timeout; the app's default is 60 s, so they would time out and fall back), calls took 128–300+ s and
N1 was misread. `tests/purchasing_agent/test_llm_no_thinking.py` keeps thinking off.
