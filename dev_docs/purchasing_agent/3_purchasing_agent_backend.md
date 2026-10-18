# Purchasing Agent: Backend Design

**Status:** implemented standalone (branch `purchasing-agent`, 2026-10-18).
**Stack:** FastAPI, PostgreSQL on Neon, SQLAlchemy + Alembic (migrations `004`, `005`).
**Code:** `backend/app/purchasing_agent/` (file table and full route list in its `README.md`).
**Related notes:** `1_purchasing_agent_high_architecture.md`, `2_purchasing_agent_functions.md`, `4_purchasing_agent_database.md`.
**Diagrams:** `diagrams/Purchasing Agent Backend Architecture Diagram.png`, `diagrams/Purchasing Agent API Endpoints Chart.png`.

## A. Layers

| # | Layer | Files | Job |
| --- | --- | --- | --- |
| 1 | API doors | `api.py` | Routes only. Clock (`get_clock`) and LLM client (`get_llm_client`) are dependencies, so tests can replace them. |
| 2 | Orchestration | `service.py`, `negotiation.py`, `approval.py`, `abort.py`, `deadlines.py`, `contracts.py` | One action = one transaction. |
| 3 | Pure decisions | `selection.py`, `negotiation.validate` | No database, no clock. |
| 4 | LLM helpers | `interpretation.py`, `writer.py`, `wording.py` | Read replies, word messages, explain; guardrails; applied after the commit. |
| 5 | Data | `models.py`, `views.py`, `availability.py` | Own tables, read views, holds + locks. |
| 6 | Sibling modules | `supplier_service/`, `negotiation_engine/` | Read supplier data; store protocol state. Used only through their `service.py`. |
| Side | Templates, seed | `messages.py`, `seed.py`, `test_channel/` | Message templates (never a price), fixture reset, chat page. |

## B. API doors

| Door | Returns / refuses |
| --- | --- |
| `POST /purchasing/procurement-requests` | 201 new; 200 existing (same `request_ref`, same data); 409 different data; 422 bad input / unknown item |
| `GET /purchasing/procurement-requests/{id}` (+ `/audit`) | Status, Legs, negotiation, selection audit / every audit record |
| `POST .../{id}/approve`, `.../{id}/reject` | 409 unless AGREEMENT_PROPOSED with every Leg AGREED |
| `POST .../{id}/abort` | 409 unless NEGOTIATING |
| `GET /purchasing/scheduled-receipts` | One per committed Leg, optional `item_id` |
| `POST/GET /purchasing/contracts` | 201; 409 overlapping active contract; 422 bad input |
| `GET /purchasing/test-channel` (+ `/conversations`, `/conversations/{leg_id}/messages`) | Chat page and conversations (no price) |
| `POST .../conversations/{leg_id}/messages` | 201 handled; 200 duplicate; 409 closed / past deadline / `offer: superseded`; 409 `message_id` used on another Leg |

Errors use the C5 body `{"error": {code, message, details}}` (`app/core/errors.py`). RFC 9457 (API-1) is a future target.

## C. Flows

### Flow 1: submit a request
1. Idempotency check on `request_ref`.
2. Other requests' overdue Legs on the item are timed out (stale holds released).
3. In one transaction: lock the item's supplier-items → effective availability → `select_suppliers` → one Leg,
   Engine session and template OFFER per supplier → SUPPLIER_SELECTION audit → commit.
4. Outside any transaction: the LLM words the offers and explains the selection. The text is applied only while still valid.

### Flow 2: a supplier reply
1. Duplicate `message_id` → 200, nothing changes (checked before any LLM call).
2. Deadline check (overdue → Leg FAILED `timeout`, request FAILED).
3. The reply is read by the LLM (or parser) with **no transaction open**.
4. Lock request and Leg and check again: closed → 409; offer changed meanwhile → 409 `offer: superseded`.
5. Validate → agree / counter / reallocate / clarify / fail → echo → audit → commit.
6. The LLM words the new messages afterwards (`wording.py`).

### Flow 3: reallocation (a quantity counter)
The counter becomes the Leg's cap. `reallocate` re-runs the rules over the selected suppliers. An unneeded Leg →
ABORTED `no_longer_needed`. A changed Leg → revised offer (a new round; an AGREED Leg is reopened). Nothing fits → the
supplier is countered back with its current quantity.

### Flow 4: failure, approval, abort
- Any Leg FAILED → request FAILED + Constrained Quantity; other Legs ABORTED `split_failed`, CANCEL sent, session CANCELLED.
- Approve → all Legs + request COMMITTED. Reject → APPROVAL_REJECTED, Legs ABORTED `approval_rejected`.
- Abort → request FAILED, open Legs ABORTED `manually_aborted`.

### Locks
A PostgreSQL transaction-scoped advisory lock per supplier-item, taken in key order (no deadlock), held until commit.
No lock is held while waiting for the LLM.

## D. Settings

`PURCHASING_TIMEZONE` (Asia/Kolkata), `PURCHASING_RESPONSE_DEADLINE_HOURS` (24, ≥ 1), `PURCHASING_MAX_ROUNDS` (3, ≥ 1),
`PURCHASING_MAX_CLARIFICATIONS` (2, ≥ 0), `PURCHASING_COST_SAVING_SPLIT_THRESHOLD` (0.10), plus the shared
`OLLAMA_BASE_URL` / `OLLAMA_MODEL`. Naive datetimes are refused for the selection date.

## E. Errors and tests

| Situation | What happens | Covered by |
| --- | --- | --- |
| Same request twice | Existing request returned | N11, `db/test_procurement_api.py` |
| Same message twice | Ignored, no extra round | N10, `db/test_supplier_chat_api.py` |
| LLM down or invalid | Parser / template / no explanation | N9, `test_llm_guardrails.py`, `db/test_llm_api.py`, `db/test_supplier_chat_api.py` |
| LLM invents a term or a price | Rejected by guardrails | `test_llm_guardrails.py` |
| Slow LLM, concurrent requests | No lock held; stale results discarded | `db/test_llm_outside_locks_api.py` |
| Competing requests | Holds reduce availability | E2, `db/test_effective_availability_api.py` |
| Late / unclear / rejecting supplier | Counter / clarify / fail | N4, N6, `db/test_supplier_chat_api.py`; N5, `db/test_deadlines_abort_api.py` |
| No reply | Timeout fails the procurement | N7, `db/test_deadlines_abort_api.py` |
| Split Leg fails | Others aborted, nothing committed | N3, `db/test_split_negotiation_api.py` |
| Quantity counter | Reallocation | N2, `db/test_reallocation_api.py` |
| Approve / reject | All or nothing | N1, N8, `db/test_approval_api.py` |
| Contract rules | Overlap 409; overlap at selection excluded | C1, C2, `db/test_contracts_api.py` |

Scenario IDs: `seed_data.md`. Tests are in `backend/tests/purchasing_agent/`. The `db/` tests need `TEST_DATABASE_URL`;
run one suite at a time.

## F. Open or later

- Access control on approve, reject, abort, contracts and the test channel (none today).
- A2A intake, Pub/Sub outcome events, cross-agent commit, Warehouse step.
- A contract modification endpoint; using up scheduled receipts.
- A live Ollama run of the prompts (tested with fakes only).
