---
status: accepted
date: 2026-10-20
---

# Re-sourcing during negotiation

Until now, Purchasing negotiated only with the suppliers it selected first. A quantity counteroffer was reallocated among them, and any failed Leg failed the whole procurement. Real ERP/MRPII buying re-sources from the same supplier data when a source drops out (`dev_docs/research/purchasing_supplier_practice_research.md`). So a single supplier saying "max 450" of 500 failed a request that another priced supplier could cover.

We now **re-source**: when the suppliers already selected can no longer cover the shortage, Purchasing re-runs the selection rules over **every eligible supplier of the item** and continues negotiating. It still never changes the requester's quantity or required date, never commits anything before human approval, and keeps every decision deterministic (the LLM only words messages).

Decided in grilling sessions on 2026-10-19 (`answers.md`, `answers1.md`, `answers2.md`). Supersedes: "new suppliers are never added during negotiation", "a dropped `no_longer_needed` Leg never returns" and "a failed Leg fails the procurement; no replacement supplier is chosen automatically" (architecture §7.4–7.5, spec stories 65, 71–74).

## Rules

1. **Order of attempts:** reallocate among the open Legs (threshold not re-checked) → if nothing fits, re-source (threshold re-checked) → if nothing fits, counter the countering supplier back while it has rounds left → else the request FAILS with the Constrained Quantity.
2. **Triggers:** a quantity counteroffer the open Legs can't cover, and a Leg that FAILS (reject, round limit, unclear after 2 clarifications, timeout). A failed Leg no longer fails the request by itself. A date-only late counter is still countered with the required date first (the supplier is asked to expedite); only if its rounds run out does its Leg fail and trigger re-sourcing.
3. **Eligible supplier:** passes the selection rules (active, no `contract_overlap`, arrives by the required date, effective availability ≥ MOQ), has rounds left in its per-request budget, and has not failed in this request. A supplier whose Leg failed is excluded for the rest of the request.
4. **Returning supplier:** a supplier dropped `no_longer_needed` may come back. It gets a new Leg and Engine session (the old ABORTED Leg stays for the audit), and a fresh offer it must accept again. Its round budget is **3 per request, shared across its sessions** (never reset). Its latest stated cap and delivery date are remembered and limit its eligibility (cap < MOQ, or a remembered date after the required date → ineligible); they are never treated as a commitment.
5. **Prices:** existing Legs keep their price snapshot; new and returning Legs use the current valid contract price. The audit records both.
6. **No supplier limit:** any number of suppliers may be combined, as in the first selection. Every subset is evaluated, so this grows exponentially with the number of suppliers of one item; fine for the fixture (≤ 4 per item), to be measured before real data.
7. **Constrained Quantity** counts only the Legs in the final allocation attempt (the open Legs plus the Leg whose failure ended it), as before. Dropped or merely considered suppliers don't count.
8. **Manual abort** stays immediate and final: no re-sourcing.
9. **Timeouts and reads:** a read (GET) only **records** a missed deadline: session TIMED_OUT, Leg FAILED `timeout`, hold released, request still NEGOTIATING with `re_sourcing_needed: true`. It never creates Legs or sends offers. Re-sourcing runs on the next write for that request (a supplier reply on it) or on the new idempotent `POST /purchasing/procurement-requests/{id}/re-source`.
10. **Audit:** decision type `RE_SOURCING` (candidates, exclusions with reasons, returning suppliers with remembered terms, both prices, every option and combination, the outcome and what changed). Offers to new Legs go through the existing writer (LLM wording behind guardrails, template fallback).

## Why not the alternatives

- **Fail and let the requester resubmit** (the old rule): simple, but it fails requests the supplier base can cover, and a resubmission loses the negotiation history and holds.
- **Re-run the whole selection from scratch:** drops agreed suppliers whenever a slightly cheaper option appears and restarts every negotiation. Re-sourcing only happens when the current allocation can't cover the shortage.
- **Ask a human to pick the replacement** (how ERP exception messages usually work): keeps a person in the loop, but the procurement then waits on a person for a deterministic choice. Here the choice is rule-based, audited and bounded by round budgets, and a human still approves before anything is committed. This is a deliberate difference from typical ERP practice.

## Consequences

- A request can now have several FAILED and ABORTED Legs while it is still NEGOTIATING. The agreement and approval consider only the open Legs (PENDING/AGREED).
- An agreed supplier can be dropped by re-sourcing (e.g. N9: Alpha capped at 450, re-sourcing picks Beta 500 because the split saves only 3.2%). It is sent the existing "no longer needed" cancel message.
- No scheduler is added. Future callers of `POST .../re-source`: a Purchasing deadline worker (recommended, once background jobs exist) or the requesting Inventory Agent nudging a stuck request at integration.
