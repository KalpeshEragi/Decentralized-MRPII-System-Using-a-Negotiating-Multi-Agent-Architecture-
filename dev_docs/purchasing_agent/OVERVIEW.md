# Purchasing Agent: Manual Test Guide

For a tester who tries the Purchasing Agent by hand and plays the suppliers in the chat.
Status: standalone build (branch `purchasing-agent`, 2026-10-18).

## 1. What this is

The **Purchasing Agent** is the system's buyer. You send it a **Procurement Request** ("we need 500 Display Panels
by date X"). It picks the best supplier (or a mix of suppliers), sends each one an offer in a chat, reads the replies,
and when all agree it proposes one agreement that a human approves or rejects.

Three parts work together:

| Part | Role |
| --- | --- |
| Purchasing Agent (`backend/app/purchasing_agent/`) | Makes every decision: which suppliers, quantities, dates, agree / counter / fail. |
| Supplier Service (`backend/app/supplier_service/`) | Read-only supplier data (lead time, minimum order, stock). **Not an agent.** |
| Negotiation Engine (`backend/app/negotiation_engine/`) | Stores chat sessions, messages, rounds and deadlines. Decides nothing. |
| Supplier chat (test channel) | A web page where **you** play the supplier. |

The AI model (local Ollama, `qwen3.5:4b`) only reads supplier replies, rewords Purchasing's messages and writes a
short explanation. Code checks its output; it never decides suppliers, quantities, dates or prices. Without it,
everything still works, but replies must use the strict format.

Not built yet: connection to the other agents (Planning, Inventory, Warehouse, ...). You act as the requester through
the API.

## 2. Key terms

| Term | Meaning |
| --- | --- |
| Procurement Request | Item, shortage quantity, required date, priority. Identified by your `request_ref`. |
| Leg | One supplier's part of a request. One chat conversation per Leg. |
| SINGLE / COST_SAVING_SPLIT / NECESSARY_SPLIT | One supplier / several suppliers because it is ≥ 10% cheaper / several because no single one can cover it. |
| Effective availability, hold | Supplier stock minus what other open requests already hold with that supplier. Stops double-booking. |
| Response deadline | 24 h after each Purchasing message that waits for a reply. Checked only when someone reads or acts (no timer). |
| AGREEMENT_PROPOSED | Every Leg agreed; waiting for a human. Nothing is ordered yet. |
| COMMITTED | A human approved; each Leg becomes a **scheduled receipt** (supplier, item, quantity, delivery date). |
| Not Registered | No valid price contract on that day. Price unknown, never zero. Shown as "cost ranking unavailable". |
| Constrained Quantity | On failure: how much could have been covered by the required date. |

## 3. Setup (once)

Commands for Git Bash on Windows, from the repository root (use `.venv/bin/python` on macOS/Linux).

1. Create `.env` in the **repository root** (copy `.env.example`). Set `DATABASE_URL` to the normal app database.
   Do **not** use `TEST_DATABASE_URL`: automated tests wipe it.
2. Install and migrate:

   ```bash
   cd backend
   python -m venv .venv
   .venv/Scripts/python -m pip install -r requirements.txt
   .venv/Scripts/python -m alembic upgrade head
   ```

3. Optional AI model: install Ollama, then `ollama pull qwen3.5:4b`. Defaults: `OLLAMA_BASE_URL=http://localhost:11434/v1`,
   `OLLAMA_MODEL=qwen3.5:4b`. Without Ollama only the strict reply format works (§13).

## 4. Run

From `backend/`:

```bash
.venv/Scripts/python -m app.purchasing_agent.seed          # reset test data
.venv/Scripts/python -m uvicorn app.main:app --reload       # start the server
```

- The seed **empties and reloads only** the `supplier_service`, `purchasing_agent` and `negotiation_engine` schemas.
  Other data (Sales, legacy) is untouched. Re-run it to start over.
- API (send requests here): <http://localhost:8000/docs>
- Supplier chat: <http://localhost:8000/purchasing/test-channel>

## 5. How to test the changes

For checking what this branch (`purchasing-agent`) changed. Do §3 and §4 first.

### 5.1 What changed

| Change | What to check | Expected result |
| --- | --- | --- |
| Purchasing Agent, tickets 01–11: selection, splits, negotiation, reallocation, holds, deadlines, abort, approval, LLM reading/wording with guardrails, no locks during LLM calls | Run the scenarios in §7, then look at the results as in §8 | Each scenario ends as its "Expected" column says; the audit explains every decision |
| Supplier chat (test channel) and its new hint | Open <http://localhost:8000/purchasing/test-channel>; read the hint; reply in normal words, then with Ollama stopped, in strict format | Hint says write naturally; strict format (`ACCEPT` / `COUNTER <qty> <yyyy-mm-dd>` / `REJECT`) only if the AI model is unavailable. Both ways work (natural text only with the model) |
| Ollama "thinking" off (`reasoning_effort: "none"` in `backend/app/llm/client.py`) | With Ollama running, time a request submit and a chat reply (see below) | Seconds, not minutes: about 18 s to submit, 8–14 s per reply (2026-10-18). Minutes or fallback-only text means something is wrong |
| Legacy supplier routes removed | <http://localhost:8000/docs>: look for `/supplier-interface/...` and `/negotiations/{id}/supplier-responses`; open <http://localhost:8000/a2a/supplier-interface/.well-known/agent-card.json> | Neither route is listed; the agent card gives **404** (for contrast, `/a2a/purchasing/.well-known/agent-card.json` still answers). The old three-agent demo stops at its first offer (expected) |
| Docs moved from `docs/` to `dev_docs/` | Open `dev_docs/README.md` (index) and `dev_docs/PROJECT_STATUS.md` | All current docs are under `dev_docs/`; the old `docs/` folder is gone |

**Timing a call** (Git Bash, server running; use a new `request_ref` each time):

```bash
curl -s -o /dev/null -w "%{time_total} s\n" -X POST http://localhost:8000/purchasing/procurement-requests \
  -H "Content-Type: application/json" \
  -d '{"request_ref":"T-TIME-1","item_id":"17b19502-e17e-5721-b38a-43fb4e5d88ed","shortage_quantity":500,"required_date":"2026-11-05","priority":3,"requested_by":"tester"}'
```

For a chat reply, count from "Send" until Purchasing's answer appears (the page polls every 2 s).

### 5.2 Automated tests

From `backend/` in Git Bash:

| Run | Command | Notes |
| --- | --- | --- |
| Fast, no database | `.venv/Scripts/python -m pytest --ignore=tests/db --ignore=tests/purchasing_agent/db --ignore=tests/sales_agent/db` | About 170 tests, seconds |
| Purchasing incl. database | `.venv/Scripts/python -m pytest tests/purchasing_agent` | Needs `TEST_DATABASE_URL` in `.env` (a **separate** Neon database; it is wiped). About 25 min. Without it the DB tests are skipped |
| Everything | `.venv/Scripts/python -m pytest` | Last full run (2026-10-18): 304 passed, 1 failed, 1 skipped |

Warnings:
- Never run two pytest processes at once on the same test database: they wipe each other's data and fail randomly.
- Neon sometimes drops connections (503 / setup errors). Rerun before reporting.
- Known, unrelated failure: `tests/sales_agent/db/test_manager.py::test_a_customer_with_many_accepted_delays_gets_exactly_the_same_request_and_options_as_a_new_one`
  (a Sales test bug: an unordered query picks history rows without a planning request). Don't report it.
- The 1 skip is the live-model Sales test (`tests/sales_agent/db/test_live_model.py`, runs only with `RUN_LIVE_MODEL=1`).

### 5.3 Checklist

- [ ] Setup, migrations and seed ran without errors
- [ ] Fast tests pass
- [ ] Purchasing tests pass (or only Neon connection errors that pass on rerun)
- [ ] Chat page opens; hint text as described
- [ ] A1 + N1 + approve → scheduled receipt
- [ ] N4 late date countered; N5 unclear ×3 fails; N6 reject fails
- [ ] B2 split: both accept → AGREEMENT_PROPOSED; reject → APPROVAL_REJECTED
- [ ] E1 + N2 reallocation (with the model)
- [ ] E2 holds: second request picks EchoTech
- [ ] A4 / B4 fail at once with the right Constrained Quantity
- [ ] Abort, duplicate `request_ref`, duplicate `message_id` behave as described
- [ ] No price anywhere in the chat
- [ ] Natural replies understood with Ollama; strict format works without it
- [ ] Replies take seconds, not minutes
- [ ] Legacy supplier routes gone (404)

**When reporting a problem, include:** scenario ID, request `id` and `request_ref`, Leg `id`, the exact message text you
sent, the full response body (status code + JSON), the server log lines around it, the date/time and your timezone
(the server uses `Asia/Kolkata`), and whether Ollama was running.

## 6. Fixture cheat sheet

Full data and reference results: `seed_data.md`. Item IDs (fixed):

| SKU | Item | `item_id` | Suppliers (lead days / MOQ / stock / price INR) | Good for |
| --- | --- | --- | --- | --- |
| DSP-100 | Display Panel | `17b19502-e17e-5721-b38a-43fb4e5d88ed` | Alpha 10/200/1000/1200 · Beta 6/100/800/1250 · Gamma 4/50/2000/Not Registered · Dormant (inactive) | Single supplier, chat basics, failure |
| BAT-200 | Battery Pack | `fb71680e-878c-5c03-8a91-10a9d1f1d971` | Volt 7/100/400/800 · Cell Works 9/200/500/900 · Ion 12/300/1500/1000 | Splits |
| MBD-300 | Main Board | `31962a4b-ab45-59ce-9ff6-a3aae8d97680` | Nova 5 · Orbit 6 · Pixel 8 · Quartz 15 (contract edge cases) | Contract dates (date-dependent) |
| CAM-400 | Camera Module | `b3877720-e627-53a8-9a99-df159635c17d` | Lumen 6 · Focal 5 (Not Registered) · Prism 20 | Split with an unpriced supplier |
| SPK-500 | Speaker | `dfab372b-9607-5d77-a80e-14551a1a2b23` | Sonic 4/100/500/300 · EchoTech 5/100/300/320 · Wave 6/100/300/340 | Three-supplier split, reallocation, holds |
| CHP-600 | Charging Port | `d30e6edf-6e2a-5d0a-a95b-436b0c2f6ac2` | PlugCo 5/100/1000/100 · ConnectRite 5/100/400/87.50 | Saving of exactly 10% |

MOQ = minimum order quantity. Arrival = today + lead days.

## 7. Test scenarios

### About dates (read first)

The server uses the **real clock**: "today" is the current date in `Asia/Kolkata` (after 18:30 UTC it is already the
next day there). `seed_data.md` assumes today = 2026-11-02, so its dates don't match a live run.

Below, each required date is written as **today + N days**, with the value for **today = 2026-10-18** in brackets.
Recompute for your day. With these offsets the outcomes below stay the same on any day **up to 2026-12-31**, except
MBD-300 (contract dates; not used here). After 2026-12-31 Beta's contract ends and DSP-100 results may change.

### How to send a request

In `/docs`, open `POST /purchasing/procurement-requests` → "Try it out". Body:

```json
{
  "request_ref": "T-A1-1",
  "item_id": "17b19502-e17e-5721-b38a-43fb4e5d88ed",
  "shortage_quantity": 500,
  "required_date": "2026-11-05",
  "priority": 3,
  "requested_by": "tester"
}
```

Use a **new `request_ref`** for every new request. Copy the returned `id`; you need it for approve / reject / abort.
In the chat, pick the conversation by supplier name and `request_ref`.

| ID | Request (item, qty, required date) | What you do | Expected |
| --- | --- | --- | --- |
| A1 + N1 | DSP-100, 500, today+18 (2026-11-05) | Chat as **Alpha Displays**: "ok, that works" (strict: `ACCEPT`) | SINGLE, Alpha 500 = 600,000 INR (cheapest; Gamma is faster but Not Registered). Alpha gets an offer: 500 by 2026-11-05. Reply → echo "Understood: you accept our offer." + "Agreed: 500 units, delivered by 2026-11-05". Request `AGREEMENT_PROPOSED`. |
| …approve | same request | `POST /purchasing/procurement-requests/{id}/approve` with `{"decided_by": "tester"}` | Request + Leg `COMMITTED`. `GET /purchasing/scheduled-receipts` shows Alpha 500 by 2026-11-05. |
| N4 | A1 again (new ref) | Alpha: "500 but delivery 25 Nov" (strict: `COUNTER 500 2026-11-25`) | Late date → Purchasing counters: 500 by the required date, "this date cannot change". Round 2/3. Then reply `ACCEPT` → agreed. |
| N5 | A1 again | Alpha: "hmm let me see", three times | 1st and 2nd: clarification request (no round used). 3rd: Leg `FAILED` `unclear_response`, request `FAILED`. |
| N6 | A1 again | Alpha: "no, we can't" (strict: `REJECT`) | Leg `FAILED` `supplier_rejected`, request `FAILED`. |
| Rounds | A1 again | Alpha: a late date three times (e.g. `COUNTER 500 2026-11-25`) | After round 3: Leg `FAILED` `round_limit_exceeded`. |
| B2 + N8 | BAT-200, 800, today+18 (2026-11-05) | Accept in **both** chats (Cell Works 400, Volt Power 400), then `POST .../reject` with `{"decided_by": "tester"}` | COST_SAVING_SPLIT 680,000 vs best single Ion 800,000 (15% saving). After both accept: `AGREEMENT_PROPOSED`. After reject: `APPROVAL_REJECTED`, both Legs `ABORTED` `approval_rejected`, each supplier gets a cancel message. |
| Split fails | B2 again | Cell Works accepts, Volt Power rejects | Request `FAILED`; Cell Works' Leg `ABORTED` `split_failed` (cancel message) even though it agreed. All or nothing. |
| E1 + N2 | SPK-500, 1000, today+10 (2026-10-28) | **Needs the AI model.** EchoTech: "we can only do 250" | Start: NECESSARY_SPLIT Sonic 500 + EchoTech 300 + Wave 200. After the reply: EchoTech capped at 250, reallocated to Sonic 500 + EchoTech 250 + Wave 250. Wave gets a revised offer (250); EchoTech gets 250 by the required date and must accept it. Accept in all three chats → `AGREEMENT_PROPOSED`. Without the model, send `COUNTER 250 2026-10-24` instead: EchoTech is agreed at once, Wave still gets the revised 250. |
| E2 (holds) | SPK-500, 400, today+10, then **while it is still negotiating** SPK-500, 300, today+10 | Don't reply to the first one | First: SINGLE Sonic 400. Second: SINGLE EchoTech 300, because Sonic has only 100 left after the first request's hold. |
| A4 | DSP-100, 300, today+3 (2026-10-21) | Nothing | `FAILED` right away: no active supplier arrives in time, Constrained Quantity 0. No chat. |
| B4 | BAT-200, 1000, today+10 (2026-10-28) | Nothing | `FAILED`, Constrained Quantity 900 (Volt 400 + Cell 500; Ion too late). |
| Abort | Any request still `NEGOTIATING` | `POST .../abort` with `{"aborted_by": "tester", "reason": "test"}` | Request `FAILED`, open Legs `ABORTED` `manually_aborted`, suppliers told. A second abort → 409. |
| N11 duplicate request | Send exactly the same body twice | — | 2nd call: **200** with the same `id`, no new Legs. Same `request_ref` with another quantity → **409**. |
| N10 duplicate message | In `/docs`: `POST /purchasing/test-channel/conversations/{leg_id}/messages` twice with the same `{"message_id": "<any UUID>", "text": "..."}` | — | 1st: 201 `received`. 2nd: 200 `duplicate`, nothing changes. (The chat page makes a new ID for every send, so use `/docs`.) |

Other ideas: A2 (DSP-100, 150, today+18 → Beta 150: Alpha's MOQ of 200 makes it dearer), A3 (DSP-100, 300,
today+5 → Gamma, "cost ranking unavailable"), F1 (CHP-600, 500, today+18 → ConnectRite 400 + PlugCo 100, exactly 10%
saving), D1 (CAM-400, 500, today+8 → Focal 300 + Lumen 200, unpriced).

A reply timeout (N7) needs 24 h of waiting. To shorten it, set `PURCHASING_RESPONSE_DEADLINE_HOURS=1` in `.env`
(minimum 1) and restart the server; it applies to messages sent after the restart. After 1 h without a reply, the
next read of the request (or chat) fails the Leg with `timeout` and the request `FAILED`.

## 8. What to check

| Where | Look at |
| --- | --- |
| `GET /purchasing/procurement-requests/{id}` | `status`, `status_reason`, `split_type`, `cost_ranking_available`, `constrained_quantity`; each Leg's `status`, `status_reason`, `allocated_quantity`, `quantity_cap`, `agreed_*`; `negotiation.messages` (type, round, text, `terms`, `interpretation_source` = `LLM` or `FALLBACK_PARSER`); `selection` (every option and why it won or lost). |
| `GET /purchasing/procurement-requests/{id}/audit` | Every decision, oldest first: `SUPPLIER_SELECTION`, `RESPONSE_VALIDATION`, `REALLOCATION`, `RESPONSE_DEADLINE`, `APPROVAL`, `MANUAL_ABORT`, with `reasoning_summary` and the AI's `llm_explanation` (may be empty). |
| `GET /purchasing/scheduled-receipts` | Only approved Legs. Agreed-but-not-approved never appear. |
| Chat page | **No price ever** in the chat. Each Purchasing answer starts with "Understood: …" (how it read your reply). The text box locks when the negotiation is closed. |

The API views show prices (for the tester); the chat never does.

## 9. Business rules

Files are in `backend/app/purchasing_agent/` unless stated.

### Supplier selection

| Rule | What it means | Where |
| --- | --- | --- |
| Usable supplier | Active, no `contract_overlap`, arrives (today + lead days) by the required date, effective availability ≥ MOQ. Otherwise excluded with a reason (`inactive_supplier`, `contract_overlap`, `arrives_too_late`, `availability_below_moq`). | `selection.py` `_unusable_reason` |
| Covers alone | A usable supplier with less stock than the shortage is `cannot_cover_alone`: not a single option, but can join a split. | `selection.py` `_choose` |
| Price on a date | Exactly one active contract valid today → priced. None → **Not Registered** (never zero). More than one → `contract_overlap`, excluded. | `selection.py` `price_state` |
| MOQ | A single supplier orders max(shortage, MOQ); the surplus is paid for and counted in the cost. In a split every Leg starts at its MOQ. | `selection.py` `_choose`, `_combination` |
| Total Purchasing Cost | Unit price × quantity ordered. | `selection.py` |
| Order of choice | 1) cheapest priced single, unless a priced split is cheaper by ≥ threshold → **COST_SAVING_SPLIT**; 2) else an unpriced single (earliest arrival) → SINGLE, "cost ranking unavailable"; 3) else a priced **NECESSARY_SPLIT** (cheapest); 4) else a split with an unpriced supplier (earliest); 5) else **FAILED**. | `selection.py` `_choose` |
| Tie-breakers | Single: cost → arrival → more stock → name. Unpriced single: arrival → more stock → name. Priced split: cost → latest arrival → fewer suppliers → more stock → names. | `selection.py` `_single_rank`, `_fallback_rank`, `_combination_rank` |
| Cost-Saving Split | Only priced suppliers; must cost ≤ (1 − threshold) × best priced single. Exactly 10% qualifies. | `selection.py` `_choose` |
| Effective availability | Supplier stock − holds of **other** requests' Legs (PENDING: allocated qty; AGREED/COMMITTED: agreed qty). FAILED/ABORTED hold nothing. Never below 0. | `availability.py` `effective_availability` |
| Stale holds | Before a selection or a reply, other requests' overdue Legs on the item are timed out first. | `deadlines.py` `expire_holds_on_item`, `expire_holds_for_leg` |
| Failure | FAILED with the Constrained Quantity (what usable suppliers could cover). | `selection.py` |
| Priority | Stored only; never used for ranking. | `service.py` |

### Negotiation and approval

| Rule | What it means | Where |
| --- | --- | --- |
| Offer | Each Leg's first offer: its quantity by the **required date**. Never a price. | `service.py` `_open_leg`, `messages.py` |
| On-time date | Agreeable only if today ≤ delivery date ≤ required date. | `negotiation.py` `on_time` |
| ACCEPT | Leg AGREED on the current offer. | `negotiation.py` `validate` |
| COUNTER, same quantity, on-time date | Leg AGREED on the supplier's date. | `validate` |
| COUNTER, same quantity, late or past date | Purchasing counters: same quantity by the required date (new round). No rounds left → FAILED `round_limit_exceeded`. | `validate` |
| COUNTER, other quantity | Becomes the supplier's **Quantity Cap**; the procurement is reallocated. | `validate`, `_reallocate` |
| COUNTER missing a term | Treated as unclear: asks for both quantity and date. | `validate` |
| Unclear reply | Clarification request (no round). After 2 for the same offer → FAILED `unclear_response`. | `validate` |
| REJECT | Leg FAILED `supplier_rejected`. | `validate` |
| Reallocation | Selection rules re-run over the **already-selected** suppliers only, with caps; threshold not re-checked; no new supplier. Unneeded Leg → ABORTED `no_longer_needed`. Changed Leg → revised offer (an AGREED Leg is reopened). Countering supplier agreed at once if the new quantity equals its counter with an on-time date, else countered. | `negotiation.py` `_reallocate`, `selection.reallocate` |
| Nothing fits the caps | Countering supplier is countered back with its current quantity; no rounds left → FAILED. | `_reallocate` |
| Revision without rounds | A Leg that must be revised but has no rounds left fails `round_limit_exceeded`, and the procurement with it. | `_fail_revision` |
| All or nothing | One Leg FAILED → request FAILED (+ Constrained Quantity); every other PENDING/AGREED Leg ABORTED `split_failed`, told, session CANCELLED. | `negotiation.py` `fail_procurement` |
| Proposal | Every Leg (except `no_longer_needed`) AGREED → request AGREEMENT_PROPOSED. | `negotiation.py` `_propose_if_all_agreed` |
| Approve | Only when AGREEMENT_PROPOSED and every Leg AGREED. All Legs + request COMMITTED in one transaction → scheduled receipts. | `approval.py` `approve` |
| Reject | Same check. Request APPROVAL_REJECTED; Legs ABORTED `approval_rejected`; suppliers told; sessions CANCELLED. | `approval.py` `reject` |
| Abort | Only when NEGOTIATING. Request FAILED; open Legs ABORTED `manually_aborted`. | `abort.py` `abort` |
| Timeout | A PENDING Leg past its deadline: session TIMED_OUT, Leg FAILED `timeout`, request FAILED (all or nothing). | `deadlines.py` `expire_overdue` |
| Echo | Every answer starts with how Purchasing read the reply ("Understood: …"). | `messages.py` `understood_text` |

## 10. Constraints and limits

| Constraint | Value / default | Setting or source | What it means |
| --- | --- | --- | --- |
| Max rounds | 3 (≥ 1) | `PURCHASING_MAX_ROUNDS` | A round = one Purchasing OFFER/COUNTER_OFFER + the reply. |
| Max clarifications | 2 per pending offer (≥ 0) | `PURCHASING_MAX_CLARIFICATIONS` | Clarifications don't use rounds. |
| Response deadline | 24 h (≥ 1) | `PURCHASING_RESPONSE_DEADLINE_HOURS` | Reset by each message awaiting a reply; checked only on reads/actions. |
| Cost-saving threshold | 0.10 (0 ≤ x < 1) | `PURCHASING_COST_SAVING_SPLIT_THRESHOLD` | A split must save at least this share. |
| Timezone | `Asia/Kolkata` | `PURCHASING_TIMEZONE` | "Today" for selection and on-time checks. |
| Whole units | quantity > 0, no fractions (500.0 ok, 500.5 → 422) | `api.py` `Quantity` | Booleans refused too. |
| Unit price | > 0, ≤ 2 decimals, INR | `api.py` `UnitPrice` | Contracts only. |
| Text lengths | `request_ref`/`requested_by`/`decided_by` 1–100; abort reason 1–500; chat text 1–2000 | `api.py` | Longer → 422. |
| Priority | any integer | `api.py` | Not range-checked; not used for ranking. |
| Price never sent | — | `messages.py`, `views.py`, `writer.py` guardrails | No price in offer terms, chat text or chat views. |
| LLM never decides | — | `interpretation.py`, `writer.py`, `wording.py` | It reads replies and words text; code validates; fallback to parser/template. |
| LLM call timeout | 60 s per call | `app/llm/client.py` | Then the fallback is used. |
| `request_ref` idempotency | unique | `service.py` `_existing` | Same item, quantity, date, priority → 200 existing; different → 409. |
| `message_id` uniqueness | unique across all sessions | `negotiation_engine/service.py` `append_message` | Same session → ignored (200 duplicate); another session → 409 CONFLICT. |
| Overlapping contracts | one active contract per supplier-item and period | `contracts.py` `register` | Overlap → 409 (seed bypasses it on purpose for Pixel Boards). |
| Lock order | request → its Legs; supplier-item advisory locks in key order | `availability.py`, `deadlines.py` | Same order everywhere, so no deadlocks; no lock held during LLM calls. |
| Stale offer | reply to an offer that changed meanwhile → 409 `offer: superseded` | `negotiation.py` `receive_supplier_message` | Answer the current offer. |

## 11. States

### a) Procurement Request (`RequestStatus`)

| State | Meaning | Can change to |
| --- | --- | --- |
| `RECEIVED` | Just stored; selection runs in the same transaction (normally not seen from outside). | NEGOTIATING, FAILED |
| `NEGOTIATING` | Legs open, chats running. | AGREEMENT_PROPOSED, FAILED |
| `AGREEMENT_PROPOSED` | Every Leg agreed; waiting for a human. Chats are closed for replies. | COMMITTED, APPROVAL_REJECTED |
| `COMMITTED` | Approved; Legs are scheduled receipts. | — (final) |
| `APPROVAL_REJECTED` | Human rejected. | — (final) |
| `FAILED` | No feasible option, a Leg failed, timeout, or manual abort. | — (final) |

### b) Leg (`LegStatus`, `LegReason`)

| State | Meaning | Can change to |
| --- | --- | --- |
| `PENDING` | Offer sent; waiting for the supplier. Holds allocated qty. | AGREED, FAILED, ABORTED |
| `AGREED` | Supplier agreed. Holds agreed qty. Not a receipt yet. | COMMITTED, ABORTED, PENDING (reopened by reallocation), FAILED (revision without rounds) |
| `COMMITTED` | Approved; a scheduled receipt. | — (final) |
| `FAILED` | This Leg failed; fails the request. | — (final) |
| `ABORTED` | Cancelled because of something else. | — (final) |

| Reason | Status | Meaning |
| --- | --- | --- |
| `supplier_rejected` | FAILED | Supplier said no. |
| `round_limit_exceeded` | FAILED | No agreement within 3 rounds (or a needed revision had no rounds left). |
| `timeout` | FAILED | No reply by the response deadline. |
| `unclear_response` | FAILED | Still unreadable after 2 clarifications. |
| `split_failed` | ABORTED | Another Leg failed the procurement. |
| `no_longer_needed` | ABORTED | Dropped by reallocation. |
| `manually_aborted` | ABORTED | Tester aborted the request. |
| `approval_rejected` | ABORTED | Human rejected the agreement. |

### c) Negotiation Engine session

| State | Meaning | Can change to |
| --- | --- | --- |
| `OPEN` | Chat running; supplier can reply. | AGREED, REJECTED, TIMED_OUT, CANCELLED |
| `AGREED` | Leg agreed. Stays AGREED after approval. | OPEN (explicit reopen), CANCELLED |
| `REJECTED` | Ended without agreement (reject, round limit, unclear). | — |
| `TIMED_OUT` | Deadline passed. | — |
| `CANCELLED` | Purchasing cancelled it (split failed, no longer needed, abort, approval rejected). | — |

### d) Message types

| Sender | Type | Meaning |
| --- | --- | --- |
| Purchasing | `OFFER` | First offer (opens round 1). |
| Purchasing | `COUNTER_OFFER` | Counter or revised offer after reallocation (opens a new round). |
| Purchasing | `CLARIFICATION_REQUEST` | "Could not read your reply" (no round). |
| Purchasing | `CONFIRMATION` | Closes the chat: agreed, failed, timeout, or revision without rounds. No round. |
| Purchasing | `CANCEL` | Order cancelled (only message allowed on an AGREED session). |
| Supplier | `ACCEPT` / `COUNTER_OFFER` / `REJECT` | How the reply was read. |
| Supplier | `UNCLEAR` | Reply could not be read. |

### e) Transitions

| Record | From → To | Trigger | Notes |
| --- | --- | --- | --- |
| Request | RECEIVED → NEGOTIATING | Selection found suppliers | One Leg + session + OFFER per supplier. |
| Request | RECEIVED → FAILED | No feasible option | Constrained Quantity set; no chat. |
| Request | NEGOTIATING → AGREEMENT_PROPOSED | Last open Leg agreed | `no_longer_needed` Legs ignored. |
| Request | NEGOTIATING → FAILED | A Leg FAILED (reject, rounds, unclear, timeout) or manual abort | Other Legs ABORTED. |
| Request | AGREEMENT_PROPOSED → COMMITTED / APPROVAL_REJECTED | Human approve / reject | One transaction. |
| Leg | PENDING → AGREED | ACCEPT or on-time COUNTER | Session → AGREED. |
| Leg | PENDING → PENDING | Counter, clarification or revised offer | Round count rises except for clarifications. |
| Leg | PENDING → FAILED | Reject / round limit / unclear / timeout | Session → REJECTED (TIMED_OUT for timeout). |
| Leg | AGREED → PENDING | Reallocation changes its quantity | Session AGREED → OPEN; revised COUNTER_OFFER. |
| Leg | PENDING/AGREED → ABORTED | Split failed, no longer needed, abort, approval rejected | Session → CANCELLED; CANCEL message. |
| Leg | AGREED → COMMITTED | Approval | Session stays AGREED. |
| Session | OPEN → AGREED / REJECTED / TIMED_OUT | Purchasing closes it | Engine only records; Purchasing decides. |
| Session | OPEN or AGREED → CANCELLED | Purchasing cancels | Ended sessions never reopen, except AGREED → OPEN. |

Display note: the AI rewording of an offer arrives a few seconds later, so you may first see the plain template text.

## 12. Known limits

- No access control: anyone can approve, reject, abort or open any supplier's chat (test build).
- AI is slow: about 4–9 s per model call; submitting a request ~18 s, a supplier reply ~8–14 s (live check
  2026-10-18, `qwen3.5:4b`, thinking off). Each call times out after 60 s, then the fallback is used.
- The legacy demo (old three-agent flow, old frontend) stops at its first offer; its supplier routes were removed.
  Use only the routes in this guide.
- Not connected to Planning, Inventory or Warehouse. Approved receipts are not used up anywhere.

## 13. Troubleshooting

| Symptom | Meaning / fix |
| --- | --- |
| Natural replies are "not understood" | AI model unavailable. Use `ACCEPT`, `COUNTER <qty> <yyyy-mm-dd>` or `REJECT` (any case). |
| 409, negotiation closed | The Leg already ended, or its response deadline passed. |
| 409, `offer: superseded` | Purchasing changed its offer while your reply was being read. Read the new offer and answer that. |
| 409 CONFLICT on a message | That `message_id` was already used on another Leg. Use a new UUID. |
| 409 on approve / reject | Request is not `AGREEMENT_PROPOSED` with every Leg agreed. |
| 409 on submit | `request_ref` already used with different data. Use a new ref. |
| 422 | Bad input: unknown `item_id`, fractional or ≤ 0 quantity, missing field. Error body: `{"error": {code, message, details}}`. |
| Strange leftovers | Re-run the seed (§4) to start clean. |

## 14. Read more

- `1_purchasing_agent_high_architecture.md` … `4_purchasing_agent_database.md`: boundary, functions, backend, tables.
- `purchasing_agent_architecture.md`: all rules in detail. `seed_data.md`: fixture and reference scenarios.
- `../supplier/`: supplier side (data service and chat). `backend/app/purchasing_agent/README.md`: files and routes.
