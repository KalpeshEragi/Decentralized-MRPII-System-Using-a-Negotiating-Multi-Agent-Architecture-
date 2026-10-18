# purchasing_agent

The new Purchasing Agent (schema `purchasing_agent`). Rules: `dev_docs/purchasing_agent/purchasing_agent_architecture.md`.
Tables: `dev_docs/OVERALL_DATABASE_SCHEMA.md` §5.2. Test data: `dev_docs/purchasing_agent/seed_data.md`. Work plan: `.scratch/purchasing-agent/`.
Manual testing: `dev_docs/purchasing_agent/OVERVIEW.md`.
The legacy `app/agents/purchasing` code and the legacy `purchasing` / `negotiation` schemas are not used.

Works with two sibling modules, each with its own schema and declarative base:
- `app/supplier_service/`: read-only supplier master data (items, suppliers, supplier items).
- `app/negotiation_engine/`: sessions, participants, messages, rounds, deadlines. No business decisions.

## Connection to the six-agent platform (PI-1 to PI-6, step 6)

Added next to Purchasing's own code; Purchasing's rules and tables are unchanged.

| File | What it does |
| --- | --- |
| `a2a.py` | The adapter: Purchasing's inbox on the negotiation layer. Planning's `REQUEST SUPPLY` becomes a Procurement Request (on the simulated clock; `core.items` matched to Supplier Service items by SKU). When the request reaches AGREEMENT_PROPOSED it OFFERs to Planning; Planning's ACCEPT gets AGREEMENT_PROPOSED (the hold is the AGREED Legs); Planning's COMMIT is the approval (`decided_by = PLANNING`) → ACCEPT + `ProcurementCommitted`; ABORT rejects / aborts the request. Purchasing's functions commit on their own, so they run as queued long-mode jobs (`SUBMIT`, `CHECK`, `COMMIT`, `ABORT`), never in the inbox transaction. It follows a request after a supplier reply (hook in `api.py`) and every simulated morning. |
| `link_models.py` | Schema `purchasing_link` (migration `011`): links between Planning's sessions and Procurement Requests, the adapter's work queue, event versions. |
| `reads.py` | Read module for Planning (IB-2): the Supplier Service item of a factory item, and an estimate of the supply lead time. |

Simulated suppliers answer automatically (`app/simulation/suppliers.py`); the supplier chat page still works for a person.
Not yet: Purchasing negotiating a receiving slot with Warehouse before committing (WH-1, PI-5: step 8); supplier delays
after commitment (S2).

## Built so far (tickets 01–11)

A Procurement Request picks a single supplier, a Cost-Saving Split (fully priced, saves ≥ 10%) or a Necessary Split
(any number of suppliers), with unpriced fallbacks (`cost ranking unavailable`); if nothing is feasible it is FAILED
with the Constrained Quantity. Per selected supplier: one Leg (PENDING, with the price snapshot, empty when Not
Registered), one Engine session (OPEN) and a template OFFER (quantity and required date, never a price). The audit
lists every option and combination. Purchasing Contracts can be registered and listed.

Supplier chat: the tester replies as the supplier on the test-channel page (`dev_docs/supplier/2_supplier_interface.md`).
The LLM reads the reply, else the strict-format fallback parser; Purchasing validates it, echoes its reading, then agrees (Leg + Engine AGREED; request
AGREEMENT_PROPOSED once every Leg agreed), counters with the Leg quantity by the required date, asks for the format
again (unclear, no round), or fails the Leg (`supplier_rejected`, `round_limit_exceeded`). All or nothing: a failed
Leg fails the request with the Constrained Quantity; every other Leg is ABORTED `split_failed` (CANCEL message, Engine
session CANCELLED, even if AGREED). At most 2 clarification requests per pending offer; the next unclear reply fails
the Leg (`unclear_response`).

LLM (ticket 10, shared `OllamaClient`, never required): it reads supplier replies into terms (a term must be written in the reply; otherwise the fallback parser reads it), words offers, counter-offers and clarifications behind guardrails (template on failure), and explains the selection (`llm_explanation`, separate from the deterministic `reasoning_summary`). Every call runs with thinking off (`reasoning_effort: "none"`, `test_llm_no_thinking.py`; measured ~4–9 s per call). No lock is held while the LLM runs (ticket 11, `wording.py`): the decision is committed with template texts first, and the wording or explanation is applied afterwards only while still valid.

Deadlines and abort (ticket 09): every message awaiting a reply moves the Leg's response deadline to now + 24h. Every
route that reads or acts on a request or Leg first checks it (`deadlines.py`, no scheduler): a PENDING Leg past it is
told, its Engine session TIMED_OUT and the Leg FAILED `timeout`, failing the procurement. A tester can abort a
NEGOTIATING request (`abort.py`; a proposed agreement is rejected through approval instead): FAILED with the reason; every open Leg ABORTED
`manually_aborted`, told, Engine session CANCELLED.

Effective availability (ticket 08, `availability.py`): selection, reallocation and the Constrained Quantity use the
Supplier Service quantity less other requests' holds (PENDING: allocated; AGREED/COMMITTED: agreed; FAILED/ABORTED
release), read under per supplier-item advisory transaction locks so competing allocations run one at a time.

Flexible Legs (ticket 07): a COUNTER with another quantity caps that supplier (`quantity_cap`), and pure `reallocate`
re-runs the selection rules over only the still-selected suppliers (caps applied, price snapshot, no threshold
re-check). An unneeded supplier's Leg is ABORTED `no_longer_needed` (CANCEL, Engine CANCELLED); a Leg whose quantity
changes gets a revised offer (an AGREED one is reopened, Engine AGREED → OPEN), a new round; the countering supplier is
agreed when the new allocation is its counter by an on-time date, else countered. A revision with no rounds left fails
the procurement. No allocation fits → the countering supplier is countered back with its current quantity; accepting
lifts its cap. REALLOCATION audit: allocation before/after, caps, every option/combination, actual saving against the
original best priced single.

Approval: a human approves (every Leg and the request COMMITTED in one transaction) or rejects (APPROVAL_REJECTED,
every Leg ABORTED `approval_rejected`, each supplier told and its Engine session CANCELLED) a proposed agreement. Committed Legs are the scheduled receipts, one per Leg.

| File | What it does |
| --- | --- |
| `selection.py` | Pure decisions, no database or clock: contract price state on a date, singles, splits (every subset, MOQ-first allocation), fallbacks, failure; why every option and combination won or lost; `reallocate` over the selected suppliers with caps. |
| `contracts.py` | Contract write rules (price, dates, supplier-item exists, no active overlap) and the contract list. |
| `service.py` | Orchestration (the selection in one transaction; LLM wording after it): idempotent intake, Supplier Service and contract reads, selection, one Leg + Engine session + offer per selected supplier, audit. |
| `interpretation.py` | Supplier reply text → action and terms: LLM extraction checked against the text, else the strict-format fallback parser. |
| `writer.py` | LLM-written message text and selection explanation, with guardrails; template / NULL on failure. |
| `negotiation.py` | One supplier reply: interpret (outside any lock), then in one locked transaction re-check, validate (pure `validate`), agree / counter / reallocate / clarify / fail, echo, audit; `cancel_leg` for every cancelled Leg. |
| `wording.py` | LLM wording of committed messages and the selection explanation, applied only while still valid (Leg PENDING, message unanswered). |
| `approval.py` | A human's approve / reject in one transaction: only while AGREEMENT_PROPOSED with every Leg AGREED; audit. |
| `deadlines.py` | Lazy response-deadline check: time out an overdue Leg and fail the procurement, in one transaction; audit. Also other requests' overdue Legs on an item before a selection or reply (stale holds). |
| `abort.py` | A tester's manual abort in one transaction: only while NEGOTIATING; audit. |
| `messages.py` | Template text (offer, echo, counter, confirmation, clarification) and offer terms. Never a price. |
| `test_channel/supplier_chat.html` | The WhatsApp-like supplier chat page. |
| `views.py` | Read-only views: request (Legs, negotiation, selection audit), audit list, scheduled receipts, chat conversations (no price). |
| `api.py` | Routes only. Clock is a dependency (`get_clock`) so tests fix the date. |
| `models.py` | Tables, and the status/reason constants (`RequestStatus`, `LegStatus`, `LegReason`). Logical references to the other two schemas (no database foreign keys). |
| `seed.py` | Resets the three new schemas and loads the fixture: `python -m app.purchasing_agent.seed` (uses `DATABASE_URL`). |

## API

| Route | What it does |
| --- | --- |
| `POST /purchasing/procurement-requests` | `request_ref`, `item_id`, `shortage_quantity`, `required_date`, `priority`, `requested_by`. `201` new; `200` + the existing request for a known `request_ref` with the same item, quantity, date and priority; `409 CONFLICT` for a known `request_ref` with different data. Quantity in whole units (`500.0` ok, `500.5` refused). Unknown item / bad input: `422 VALIDATION_ERROR`. |
| `GET /purchasing/procurement-requests/{id}` | (Like every route below that reads or acts on a request or Leg, first times out a Leg past its response deadline.) Status, split type, Legs with their negotiation (participants, messages), selection audit. |
| `GET /purchasing/procurement-requests/{id}/audit` | Every decision recorded for the request (selection, response validations, reallocations, approval), oldest first. |
| `POST /purchasing/procurement-requests/{id}/approve` | `decided_by` (the human approver). Every Leg (except those dropped `no_longer_needed`) and the request COMMITTED; `decided_at` set; audited. `409 INVALID_STATE_TRANSITION` unless the request is AGREEMENT_PROPOSED and every Leg AGREED (nothing changes); `404` unknown request. |
| `POST /purchasing/procurement-requests/{id}/reject` | `decided_by`. Request APPROVAL_REJECTED, every Leg ABORTED `approval_rejected`, a CANCEL message to each supplier and its Engine session CANCELLED; same refusals as approve. |
| `POST /purchasing/procurement-requests/{id}/abort` | `aborted_by`, `reason`. Request FAILED (`aborted by <who>: <reason>`); every PENDING/AGREED Leg ABORTED `manually_aborted`, a CANCEL message to its supplier and its Engine session CANCELLED; audited. `409 INVALID_STATE_TRANSITION` unless NEGOTIATING (use reject for a proposed agreement; a repeated abort is also 409); `404` unknown request. |
| `GET /purchasing/scheduled-receipts` | One per committed Leg (supplier, item, agreed quantity, agreed delivery date), earliest delivery first; optional `item_id`. AGREED Legs never appear. |
| `GET /purchasing/test-channel` | The supplier chat page. |
| `GET /purchasing/test-channel/conversations` | One conversation per Leg, newest first: supplier, item, quantity, required date, rounds, Leg and Engine status. Never a price. |
| `GET /purchasing/test-channel/conversations/{leg_id}/messages` | One conversation with its messages. |
| `POST /purchasing/test-channel/conversations/{leg_id}/messages` | `message_id` (UUID, sender-chosen), `text`. `201` handled; `200` `duplicate` for a known `message_id` (nothing changes); `409 INVALID_STATE_TRANSITION` once the negotiation is closed, after the response deadline, or when Purchasing's offer changed while the reply was being read (`offer: superseded`; nothing stored, answer the current offer); `409 CONFLICT` for a `message_id` already used on another Leg; `404` unknown Leg. |
| `POST /purchasing/contracts` | `supplier_id`, `item_id`, `unit_price` (INR, > 0, ≤ 2 decimals), `valid_from`, `valid_until` (empty = open-ended, ≥ `valid_from`), `is_active` (default true). `201` + the contract. Unknown supplier/item or a supplier that doesn't supply the item, bad input: `422 VALIDATION_ERROR`. Active contract overlapping another active one for the pair: `409 CONFLICT`. |
| `GET /purchasing/contracts` | All contracts (incl. inactive and bad seeded ones), optional `supplier_id` / `item_id` filters; grouped by item and supplier, oldest validity first. |

## Settings

`PURCHASING_TIMEZONE` (default `Asia/Kolkata`; the selection date is today there), `PURCHASING_RESPONSE_DEADLINE_HOURS`
(24), `PURCHASING_MAX_ROUNDS` (3), `PURCHASING_MAX_CLARIFICATIONS` (2 per pending offer),
`PURCHASING_COST_SAVING_SPLIT_THRESHOLD` (0.10 = 10%; its only source). Bounds: max rounds ≥ 1, max clarifications ≥ 0,
deadline hours ≥ 1.
