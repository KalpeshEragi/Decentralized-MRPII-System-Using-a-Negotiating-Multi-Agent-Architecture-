# Purchasing Agent Architecture

Last updated: 2026-10-18 (code review, ticket 11). Terms follow `GLOSSARY.md`; tables follow `dev_docs/OVERALL_DATABASE_SCHEMA.md` §5 and §8; test data follows `dev_docs/purchasing_agent/seed_data.md`; the price decision is `dev_docs/adr/ADR-002-price-in-supplier-selection.md`.

# 1. Purpose
Turns a **Procurement Request** into a feasible **Procurement Agreement** by evaluating supplier options and negotiating quantity and delivery date with suppliers through the supplier-facing chat.

## Main responsibility
Decide what quantity to procure, from which supplier or combination of suppliers, and by when it can be delivered. Select only feasible solutions that give the best overall result under the agreed purchasing rules.

# 2. Works With
- **Requester:** submits Procurement Requests through the Purchasing API (`requested_by`). Which agent is the requester in the integrated system is decided at integration (HA-3). Purchasing replies to the requester only. Standalone: a test API. (Future Integration)
- **Production Planning Agent:** learns outcomes later through a Pub/Sub outcome event, not a direct call from Purchasing. (Future Integration)
- **Negotiation Engine** (`backend/app/negotiation_engine/`, schema `negotiation_engine`): holds session state, participants, chat messages, round counts and response deadlines. Built now; currently it hosts only Purchasing ↔ supplier sessions. Agent-to-agent sessions are added later. It makes no business decisions.
- **Supplier Service** (`backend/app/supplier_service/`, schema `supplier_service`): owns supplier master data: procurable items, suppliers, supplier items, lead time, MOQ and available quantity. In standalone mode an item is valid only if the Supplier Service knows it. Purchasing reads it through its interface and never writes to it.
- **Supplier-facing chat:** a WhatsApp-like, free-text test-channel page served by the Purchasing API (`purchasing_agent/test_channel/supplier_chat.html`, like Sales). It has one conversation per Leg, and the tester plays any supplier. It is an interface, not an MRPII agent.
- **Simulation / Scenario Manager:** supplier-change handling is **future scope**. (§8)

## Separation
Purchasing does not control inventory, production plans or supplier master data. It owns its Purchasing Contracts, Procurement Requests, requisitions (Legs) and decision audit in schema `purchasing_agent` (`backend/app/purchasing_agent/`, structured like `sales_agent`). The legacy `purchasing` and `negotiation` schemas and the legacy agent code are untouched and unused.

# 3. Core Flow
```text
Procurement Request (idempotent by request_ref; same ref + different data → 409 Conflict)
      ↓
Read supplier options (Supplier Service) and valid Purchasing Contracts on the selection date
      ↓
Compute effective availability (minus Purchasing's own holds), under a per supplier-item lock
      ↓
Select: single, Necessary Split or Cost-Saving Split (§6), deterministic
      ↓
Create one requisition (= Leg) + one Engine session per selected supplier
      ↓
Free-text chat per Leg: offer → supplier reply → interpret → validate (§7)
      ↓
Counteroffer? → reallocate across the already-selected suppliers (§7)
      ↓
All Legs AGREED? ── No (a Leg failed / no valid allocation) → request FAILED, abort all other Legs, report Constrained Quantity
      │
      Yes
      ↓
Request AGREEMENT_PROPOSED (combined Procurement Agreement)
      ↓
Human approves → all Legs COMMITTED in one transaction (one scheduled receipt per Leg)
Human rejects  → request APPROVAL_REJECTED, all Legs ABORTED
      ↓
Outcome returned to the requester
```

# 4. Tools / Services
- `submit_procurement_request(...)` (idempotent)
- `get_supplier_options(...)` (Supplier Service, read-only)
- `get_valid_contract(...)` (returns price, Not Registered or `contract_overlap`)
- `compute_effective_availability(...)`
- `select_suppliers(...)` (pure: singles, combinations, allocation, ranking)
- `reallocate(...)` (pure: same rules, restricted to the selected suppliers and their caps)
- `open_leg_session(...)`, `send_offer(...)`, `record_supplier_message(...)` (Engine)
- `interpret_supplier_message(...)` (LLM extraction, fallback parser)
- `validate_supplier_terms(...)`
- `approve_procurement(...)`, `reject_procurement(...)`, `abort_leg(...)`
- `record_decision(...)` (audit)

These are responsibility-level names; final names follow repository conventions.

# 5. Separation of Responsibilities
- **Purchasing Agent:** supplier selection, allocation and reallocation, response validation, Leg and request business status, combined outcome, approval handling, audit.
- **Supplier Service:** deterministic supplier data. It never chooses suppliers.
- **Purchasing repository (`purchasing_agent`):** contracts, Procurement Requests, requisitions (one row per Leg), decision audit.
- **Negotiation Engine (`negotiation_engine`):** sessions, participants (`participant_type` AGENT or SUPPLIER plus `participant_ref`, validated to exist), messages, rounds, deadlines. Session statuses: `OPEN`, `AGREED`, `REJECTED`, `TIMED_OUT`, `CANCELLED`. These are separate from Purchasing's Leg statuses (`PENDING`, `AGREED`, `FAILED`, `ABORTED`, `COMMITTED`).
- **Supplier chat:** shows text only. It never shows or asks for a price.

# 6. Multi-Factor Decision Making
Inputs: required quantity and date, supplier arrival (selection date + lead time), effective availability, MOQ, Purchasing Contract price, and Total Purchasing Cost including MOQ surplus. Request **priority** affects only processing order and urgency, never supplier ranking.

## 6.1 Dates
- **Selection date** = the server's date in the configured timezone (working default `Asia/Kolkata`). Tests use a fixed clock.
- **Arrival** = selection date + `lead_time_days`, in calendar days.

## 6.2 Purchasing Contracts
Table `purchasing_agent.purchasing_contracts`: `id, supplier_id, item_id, unit_price, valid_from, valid_until, is_active, created_at`.
- One supplier-item pair, a unit price in INR > 0. A pair may have historical and future contracts.
- **Write rule:** creating or modifying an active contract whose validity overlaps another active contract for the same pair is rejected.
- **Read rule (on the selection date):** exactly one active, valid contract → price. None → **Not Registered** (never zero, estimated or invented). More than one (data error) → the supplier-item is **excluded** with reason `contract_overlap`, shown in the options and audit; other suppliers are still evaluated.
- Price is used for supplier selection only. It is never negotiated, never sent in offer terms, and never shown in the supplier chat.

## 6.3 Usable supplier and effective availability
- **Effective availability** = supplier `available_qty` − quantity held by Purchasing's own `PENDING`, `AGREED` and `COMMITTED` Legs for that supplier-item. `FAILED` and `ABORTED` Legs release their hold.
- Only **other** requests' Legs hold: a request's own Legs are what its reallocation re-decides, so they never reduce its own effective availability (confirmed 2026-10-18, ticket 08; consistent with the Constrained Quantity rule in §7.5).
- Selections and reallocations for the same supplier-item run one at a time under a transaction-safe lock. Implementation: a PostgreSQL transaction-scoped advisory lock per supplier-item, held until commit; each selection or reallocation locks all of the item's supplier-items in a fixed order, so concurrent ones can't deadlock.
- A supplier is **usable** if it is active, not excluded, arrives by the required date, and its effective availability ≥ MOQ.
- A single supplier **covers alone** if usable and effective availability ≥ shortage quantity. Order quantity = max(shortage, MOQ).

## 6.4 Selection rules
1. **Priced single exists** (a covering supplier with a price): take the best priced single (lowest Total Purchasing Cost → earliest arrival → larger effective availability → name). Compare it with the best fully priced combination. If the combination costs **≤ 90%** of the single, choose a **Cost-Saving Split**; otherwise choose the single.
2. **Only unpriced singles cover:** choose the fallback single (earliest arrival → larger effective availability → name), labelled `cost ranking unavailable`.
3. **No single covers:** **Necessary Split.** Prefer the best fully priced combination. Otherwise choose the best combination that includes an unpriced supplier, labelled `cost ranking unavailable`.
4. **Nothing feasible:** request FAILED, with Constrained Quantity = total effective availability of the usable suppliers.

The 10% threshold is one named, configurable value. It applies only to the initial choice of a Cost-Saving Split.

## 6.5 Combinations
- Every subset of ≥ 2 usable suppliers is evaluated; there is no fixed maximum. Each Leg is MOQ ≤ quantity ≤ effective availability (or cap), and the sum is ≥ shortage.
- **Allocation (deterministic):** start every Leg at its MOQ, then fill the remainder from the cheapest unit price first (priced combinations) or the earliest arrival first (combinations with an unpriced supplier), up to each Leg's limit. This gives the minimum Total Purchasing Cost for the subset, with surplus only where MOQ forces it. Fill order, priced (confirmed 2026-10-18): lower price → earlier arrival → larger effective availability → supplier name. With an unpriced supplier: earlier arrival → larger effective availability → supplier name.
- **Ranking, priced:** total cost → latest Leg arrival (earlier is better) → fewer suppliers → larger total effective availability → supplier names.
- **Ranking, with an unpriced supplier:** latest Leg arrival → fewer suppliers → smaller total ordered quantity → larger total effective availability → supplier names.
- An extra supplier therefore only wins when it makes the ranking strictly better.
- A Cost-Saving Split must be fully priced. No cost claims are made about an unpriced supplier.
- **Explainability:** the audit records every option and combination considered, its price or `Not Registered` or `contract_overlap`, quantities, cost where known, arrivals, and why the result won. Every combination, including one that can't reach the shortage, lists each supplier's effective availability, MOQ, arrival and price state; an infeasible one also says why it falls short (confirmed 2026-10-18).

The deterministic backend selects. The LLM may explain but cannot override, and cannot fabricate prices.

# 7. Negotiation
## 7.1 Rounds and messages
- One round = one Purchasing offer/counter-offer + the supplier's reply. **Max 3 rounds per supplier** (Leg). The round count rises when Purchasing sends an offer or counter-offer: the first offer starts round 1 and the supplier's reply completes it (confirmed 2026-10-17).
- Offer terms (quantity, delivery date) are computed deterministically. The **LLM writes only the message text**; if it fails, a predefined template is used.
- Each Leg has a **response deadline** (working default 24h, configurable). It is checked when the session is next read or acted on, with no background scheduler. Past the deadline: Engine `TIMED_OUT`, Leg `FAILED` (`timeout`). A manual abort endpoint also exists.

Implementation clarifications (ticket 09, **confirmed 2026-10-18**):
- Every Purchasing message awaiting a reply (offer, counter-offer, revised offer, **clarification request**) moves the deadline to now + the configured hours, so each clarification request gives a fresh 24h (bounded by the 2-clarification limit). "Past" means strictly after the deadline.
- Checked before every read or action on a request or Leg (request and audit reads, the supplier chat's conversation list and conversation, a supplier reply, abort). **Also before availability is calculated** for a selection or reallocation (confirmed 2026-10-18, code review): overdue PENDING Legs of other requests holding the item's supplier-items are timed out first, releasing their holds and applying the failure rules (§7.5). Still lazy; no background scheduler. A timed-out Leg fails the procurement (§7.5); the supplier gets a closing `CONFIRMATION`. A reply after the deadline is refused (409) and not stored.
- Manual abort (`POST /purchasing/procurement-requests/{id}/abort`, `aborted_by` + `reason`): only while `NEGOTIATING`; a proposed agreement is rejected through approval instead. Request `FAILED` with the reason, no Constrained Quantity; every `PENDING`/`AGREED` Leg told (`CANCEL`), `ABORTED` (`manually_aborted`), its Engine session `CANCELLED`, hold released. The deadline is checked first, so aborting a request whose Leg is already past its deadline gets 409 and the request ends FAILED `timeout`. A repeated abort gets 409 (tester endpoint; not idempotent).
- Duplicate deliveries of the same `message_id` are ignored.

## 7.2 Interpreting free-text supplier replies
1. The **LLM extracts** `action` (ACCEPT / COUNTER / REJECT), `quantity` and `delivery_date` where present. It never invents missing terms.
2. If the LLM is unavailable or its output is invalid, a **fallback parser** reads the strict format `ACCEPT`, `COUNTER <qty> <yyyy-mm-dd>`, `REJECT`. Purchasing's template messages tell the supplier this format.
3. Purchasing **validates** the extracted terms and **echoes its interpretation** in its reply (e.g. "Understood: 300 units by 12 Nov"). When the reply agrees or ends the Leg, the echo goes in a `CONFIRMATION` message (no round).
4. If the reply is unclear, Purchasing sends a **clarification request**. Clarifications don't count as rounds and don't reset the limit. Max **2 clarifications per pending offer**; then the Leg FAILS (`unclear_response`).

A supplier's acceptance alone never establishes feasibility.

Implementation clarifications (ticket 10, confirmed 2026-10-18):
- A term the LLM reports is used only if it is written in the reply (quantity as a number; the date's day as a number and its month as a number or name; its year written, else the first such day on or after the selection date). Otherwise the output counts as invalid and the fallback parser reads the reply.
- Ticket 11 (code review 2026-10-18): the quantity must be written *as a quantity*: a number inside a date ("12 Nov", "12/11"), after a reference word ("order 300", "PO #4411") or in a code (DSP-100) never counts. A year counts only when written inside a date, so a 4-digit quantity ("2500 by 15 Nov") never forces a year.
- An ACCEPT that states terms different from the current offer is a COUNTER on those terms (e.g. "ok, 500 by 12 Nov" against an offer of 500 by 20 Nov → agreed on 12 Nov under §7.3).
- A COUNTER may state only one term (e.g. "we can only do 250"); the other stays empty, never invented. Another quantity → reallocation (§7.4); the countering supplier is never agreed without a stated date, so it is countered with its quantity by the required date. A late date → countered with the required date. Otherwise the missing term decides the outcome → a clarification request asking for both (same limit as unclear replies).

## 7.3 Validating a reply
- **ACCEPT** of the current offer → Leg AGREED with the offered quantity and date.
- **COUNTER with the offered quantity and a date no later than required** → Leg AGREED on the supplier's terms (clarified in ticket 04, pending review). Any other quantity is handled as below.
- **Delivery date later than required** → never accepted. Purchasing counters with the required date (or the Leg fails when rounds run out). The requester's deadline is never changed.
- **Delivery date in the past** (before today in the configured timezone) → never accepted (confirmed 2026-10-18, code review). Purchasing never agrees to an impossible or expired date; it is handled like a late date: countered with the required date, or the Leg fails when rounds run out.
- **COUNTER with quantity Q** → Q becomes that supplier's **cap** for this procurement (also limited by effective availability). Then reallocate (§7.4).
- **REJECT** → Leg FAILED (`supplier_rejected`).

## 7.4 Flexible Legs: reallocation
After a quantity counteroffer, Purchasing re-runs §6.4–6.5 **using only the already-selected suppliers**, with their caps, MOQs, effective availability and arrival.
- Any subset of them, including a single supplier, may win if it ranks better. The 10% threshold is not re-checked; the revised allocation and actual saving are audited.
- A selected supplier that is no longer needed → its Leg is ABORTED (`no_longer_needed`) and its Engine session CANCELLED, even if it had agreed (nothing is committed yet).
- A Leg whose quantity changes → reopened with a revised offer (Engine `AGREED → OPEN` only on this explicit reopen). This **counts as a new round** for that supplier.
- **No allocation fits the caps:** while the capping supplier has rounds left, Purchasing counters back with the quantity it needs (this also covers a single-supplier procurement). If the supplier accepts, its cap is lifted to that quantity.
- New suppliers are **never** added, and supplier selection is never restarted.

Implementation clarifications (ticket 07, 2026-10-18, **pending review**):
- "Selected suppliers" = the request's PENDING or AGREED Legs; a Leg dropped as `no_longer_needed` never returns, and is not part of the agreement, approval or Constrained Quantity.
- Prices come from each Leg's price snapshot; arrival = the agreed delivery date for an AGREED Leg, else today (configured timezone) + lead time (the same rule as the Constrained Quantity). **Confirmed 2026-10-18 (code review):** a PENDING Leg's arrival uses the current date, so time passing can make a supplier too late.
- A COUNTER above the offered quantity also caps, but leaves the allocation unchanged, so the supplier is countered with its current quantity (a round, as before ticket 07).
- When a priced single covers, it is ranked against the priced splits as a one-supplier combination (no threshold); otherwise §6.4 rules 2–4 apply unchanged.
- Only a COUNTER whose quantity differs from the current offer caps and reallocates. The countering supplier's Leg is AGREED when its new quantity equals its counter and the date is on time; otherwise it is countered with its new quantity by the required date.
- "The quantity it needs" on counter-back = that Leg's current allocated quantity (the last feasible allocation), so no other Leg changes.
- A Leg that must be revised but has no rounds left FAILS `round_limit_exceeded` (an AGREED one is reopened first so its session ends REJECTED); the procurement then fails as in §7.5.
- After reallocation the request's `split_type` is updated (SINGLE / NECESSARY_SPLIT / COST_SAVING_SPLIT); the actual saving is audited against the original selection's best priced single.

## 7.5 Failure (all-or-nothing)
Any Leg ends FAILED (reject, round limit → Engine `REJECTED` with `round_limit_exceeded`, timeout, unclear response), or no valid allocation remains →
- the request is FAILED with a reason and the **Constrained Quantity** (the most the selected suppliers could still supply under their caps);
  - computed (confirmed 2026-10-18), counting only quantities deliverable by the required date: the failed Leg's supplier counts the quantity of its last valid (on-time) counter-offer, within its availability and cap, else 0 if it never offered one; every other selected supplier counts its feasible quantity: availability less other requests' holds, limited by its cap, counted only if ≥ its MOQ and it delivers by the required date (agreed date, else today in the configured timezone + lead time); the total is capped at the original shortage. B1 with Cell Works rejecting without an offer → 400 (Volt only); N3 → 700;
- every other Leg (PENDING or AGREED) is ABORTED (`split_failed`), sent a CANCEL message, its Engine session CANCELLED (also from AGREED) and its hold released;
- no Leg is committed or counted as a scheduled receipt;
- no replacement supplier is chosen automatically. The requester decides whether to submit a new request.

## 7.6 Approval
- The combined outcome is proposed only when every Leg is AGREED (request `AGREEMENT_PROPOSED`).
- A **human** approves or rejects through the Purchasing API. The approver (`decided_by`) is recorded in the APPROVAL audit.
- Approve → all Legs COMMITTED in one transaction; Engine sessions stay AGREED. A read API exposes committed Legs as scheduled receipts, one per Leg (optionally filtered by item).
- Reject → `APPROVAL_REJECTED`, all Legs ABORTED (`approval_rejected`), each supplier told and its Engine session CANCELLED (`approval_rejected`), like every other aborted Leg (confirmed 2026-10-18).
- Approval checks only that the request is still `AGREEMENT_PROPOSED` and every Leg is still AGREED. Supplier-data changes after agreement are disruptions (future scope).
- Cross-agent approval and commit replace this during integration.

# 8. Simulation / Replanning (Future Scope)
Not implemented now. Later, a supplier event (delay, quantity reduction) will make Purchasing re-check committed agreements and record **Invalidated Agreements**. Any re-selection or re-negotiation rule will be decided then; the Scenario Manager must never edit Purchasing records or select suppliers.

# 9. LLM Role
- Writes offer, counter-offer and clarification message text.
- Extracts terms from supplier free text (validated, with a fallback parser).
- Explains the deterministic selection.

## Keep these deterministic
- Contract lookup, validity and overlap checks, Not Registered handling
- Effective availability, feasibility, combination search, allocation, reallocation, cost and ranking
- MOQ, cap, availability and deadline checks; validation of supplier terms
- Leg/request state transitions, approval and persistence

## Guardrails
Implementation (ticket 10, confirmed 2026-10-18): the LLM rewords offers, counter-offers, revised offers and clarification requests; the echo, the reply-format line, confirmations and cancellations stay templates. Wording is rejected (template sent) if it drops or changes a quantity or date, adds any other number, date, code or month, mentions price, payment, free or zero, or names another supplier of the item; also (ticket 11) if it writes a quantity or date in words ("two hundred", "Friday", "next month"), uses a money word (fee, amount, sum, bill, rate, cost, lakh, crore, ₹), or says an allowed number more often than the template or with "more"/"extra" ("500 more units later"). The selection explanation is stored as `llm_explanation` only for SUPPLIER_SELECTION; it is dropped (NULL) if it states a number not in the decision, calls a Not Registered supplier free or zero or gives it a price (also through "it"/"its" in the following sentence, e.g. "it would be 1200 a unit", "its price is zero"), makes a cost or value comparison ("cheapest", "better-value", "economical") when cost ranking is unavailable, or mentions negotiating price. The deterministic `reasoning_summary` is always stored.

## Locks and LLM calls (confirmed 2026-10-18, code review)
Supplier-item locks still serialize availability checks and hold updates, but no lock is held while waiting for the LLM:
1. Lock, check availability, record the decision/holds, commit (locks released).
2. Call the LLM outside any locked transaction.
3. Re-lock and revalidate the request, offer and availability before applying the LLM result. If the state changed, the stale result is handled safely (discarded or the template/fallback used; never applied to changed state).

Example: Supplier A has 500; two requests each need 400. Only one may reserve 400, but a request waiting for the LLM must not block the other longer than necessary.

Implementation (ticket 11, 2026-10-18; `wording.py`):
- Messages awaiting a reply are stored with their template text and committed; the LLM's wording replaces it afterwards only while the Leg is still PENDING and the message is still its session's latest, unanswered message (Engine `reword_message`). Terms are stored with the message and never change. Otherwise the template stays. A supplier may see the template for a moment before the wording replaces it.
- The selection explanation is added to the SUPPLIER_SELECTION audit after the commit, while it has none; the audited decision never changes, so it cannot go stale.
- A supplier reply: a duplicate `message_id` is skipped before any LLM call; the reply is read with no transaction open; the request and Leg are then locked and checked again. Leg or request closed meanwhile → 409; Purchasing's offer changed meanwhile (e.g. a revised offer after another Leg's reallocation) → 409 `offer: superseded`, nothing stored, and the supplier answers the current offer (**decision for review:** not treated as unclear, so it never uses up a clarification).

The LLM must never change suppliers, quantities, dates, prices or allocations; negotiate price; treat Not Registered as zero; or invent a price or a missing term. Its explanation is stored as explanation, not evidence. Unsupported price claims are rejected and the deterministic summary or template is used.

# 10. Independent Development Scope and Integration
## Build now
- `supplier_service`: models, read interface, seed and reset
- `purchasing_agent`: contracts (with write validation), Procurement Requests (idempotent), selection and reallocation logic, requisitions (Legs), effective availability and locking, approval, audit, API, supplier chat test channel, seed and reset
- `negotiation_engine`: sessions, participants, messages, rounds, deadlines, statuses
- LLM message writing and term extraction, with templates and a fallback parser
- Alembic migration for the three new schemas only; legacy schemas are untouched
- Tests (§11)

## Connect during multi-agent integration
- A2A requests from the requesting agent; Pub/Sub outcome events to Planning; Message Broker
- Agent-to-agent Engine sessions
- Cross-agent approval/commit and scheduled-receipt consumption by Planning
- Supplier-change handling and Invalidated Agreements (§8)

# 11. Testing and Definition of Done
Fixture: `dev_docs/purchasing_agent/seed_data.md` (scenario IDs below). Fixed clock and timezone in all tests.
- **Contracts:** active, inactive, expired, future, boundary dates, missing; overlap rejected on write; seeded overlap excluded at selection (C1, C2).
- **Selection (pure):** cost with MOQ surplus (A1, A2), unpriced fallback (A3, C1), no feasible supplier (A4, B4), Necessary Split priced (B1) and with an unpriced supplier (D1), Cost-Saving Split (B2), at exactly 10% (F1) and just below (B3, unit), three suppliers (E1), tie-breakers.
- **Effective availability:** competing requests (E2), holds released on fail/abort, lock prevents double-booking.
- **Negotiation:** accept (N1), reallocation and reopen counts a round (N2), counter-back and round limit (N3), late date (N4), clarification cap (N5), reject (N6), timeout (N7), approval reject (N8), fallback parser (N9), duplicate message (N10), duplicate request (N11), leg dropped as `no_longer_needed` (unit).
- **All-or-nothing:** no proposal until all Legs agree; a failed Leg aborts the others; nothing committed or counted as a receipt.
- **Approval:** approve commits all Legs atomically, one receipt per Leg.
- **LLM:** cannot change selection, quantities, dates or prices; invalid or unsupported output → template/deterministic fallback; tests run without Ollama.
- **API and persistence** against a test database; test doubles for other agents.
