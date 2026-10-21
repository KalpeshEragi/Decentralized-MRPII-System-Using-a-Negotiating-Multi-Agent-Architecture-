# Purchasing Agent vs Real ERP Practice: Gap Analysis

**Status:** Analysis for developer review (2026-10-19). It changes no decision, doc or code.
**Compares:** the Purchasing Agent as built (`dev_docs/purchasing_agent/purchasing_agent_architecture.md`, code in
`backend/app/purchasing_agent/`) plus the re-sourcing decisions agreed on 2026-10-19 (not yet written as ADR-003),
against `dev_docs/research/purchasing_supplier_practice_research.md` (citations `[S..]` and `§` numbers refer to that
report).

Priorities: **P1** = small, fixes a real correctness or trust problem, do soon. **P2** = worth doing in or right after
the re-sourcing ticket. **P3** = later, mostly at integration. **Out** = deliberately out of scope (spec), listed so
the choice stays visible.

---

## 1. Verdict

The core is close to industry practice: deterministic supplier choice from master data, contract prices with
validity dates, MOQ, lead-time arrival, a supplier reply treated as a proposal that code validates, a full message
history, human approval before commitment, and audit of every decision. Re-sourcing (agreed 2026-10-19) also matches
practice: alternatives come from the same master data, and a failed supplier is excluded like a request-scoped block.

The weakest area is **what the supplier is told and when**. Two messages are missing or premature (§3, G1–G2), and
the reply model is narrower than what suppliers actually send (G3–G5).

---

## 2. Where we already match practice

| Practice (research) | Ours |
| --- | --- |
| Supplier choice is deterministic master data, not free choice (§1) | `selection.py`, pure, fixed ranking and tie-breakers |
| Contract prices are time-dependent; outside validity is not used (§1 [S5][S6]) | Purchasing Contracts with `valid_from/until`; Not Registered never priced as zero |
| Blocked / inactive suppliers get no new orders (§1 [S2]) | Inactive suppliers excluded; failed supplier excluded per request (re-sourcing) |
| MOQ shapes the order quantity after the need (§2) | MOQ-first allocation, surplus counted in cost |
| Arrival is calculated from lead time, not guessed (§3) | today (configured timezone) + `lead_time_days` |
| A supplier response is a proposal; the order changes only after the buyer accepts (§4 [S31][S33][S37]) | Every reply is interpreted, validated and echoed; only Purchasing decides |
| Suppliers may change quantity/date but not price (§4 [S31]) | Price is never shown or negotiated (ADR-002) |
| Changes are versioned, history kept (§4 [S31][S32]) | Engine keeps every message; audit keeps every decision |
| Missing answers do not wait silently (§4 [S27][S37]) | 24 h response deadline per message awaiting a reply |
| No external commitment before internal approval (§5 [S47]) | Legs COMMITTED only after human approval of the whole agreement — **but see G1** |
| Re-sourcing uses the same ranked source data as normal sourcing (§7) | Re-sourcing reuses the selection rules over all eligible suppliers |

---

## 3. Gaps in Purchasing ↔ supplier communication

### G1 (P1). The supplier is told "Agreed" before the human approves

- **Practice:** an unreleased PO cannot be sent; the order becomes binding only when it is confirmed after approval
  (§5 [S47], §4 [S30]: D365 sets *Confirmed* only after approval and vendor agreement).
- **Ours:** when a Leg agrees, the supplier gets "Agreed: 500 units, delivered by …. Thank you."
  (`messages.agreed_text`). Approval may still reject it, or re-sourcing may drop the supplier (`no_longer_needed`).
  The supplier believes it has an order that does not exist yet.
- **Fix:** word the Leg agreement as **"agreed, subject to our approval"** (a *tentative* agreement), and keep the
  firm wording for G2. Small change in `messages.py` + its guardrail tests.

### G2 (P1). No order release message after approval

- **Practice:** after approval the PO is sent/confirmed to the supplier; it is a separate state from "acknowledged"
  (§4: sent ≠ confirmed ≠ received; X12 850/855, EDIFACT ORDERS/ORDRSP).
- **Ours:** `approval.approve` commits the Legs but sends the supplier nothing; the Engine session stays AGREED.
  Rejection *does* send `APPROVAL_REJECTED_TEXT`, so the two outcomes are asymmetric.
- **Fix:** on approval, send each committed Leg's supplier an **order release** message (final quantity, date,
  Purchasing's order reference = Leg id). A new agent message type (e.g. `ORDER_RELEASE`) needs an Engine
  message-type addition; it carries no round. Small.

### G3 (P2). A supplier cannot partially confirm (confirm part now, backorder the rest)

- **Practice:** suppliers split a line into **confirm / backorder / reject** quantities (§4 [S36]); X12 has codes
  for partial shipment + backorder (BP) and backordered (IB) (§4 [S41]).
- **Ours:** one Leg = one quantity + one date. "300 by 12 Nov and 200 by 18 Nov" can only be read as a COUNTER of
  300 (cap), losing the 200.
- **Fix options:** (a) keep one delivery per Leg and read the reply as "cap 300", plus echo that the backordered part
  was not used (cheap, honest); (b) support multiple delivery lines per Leg (schedule lines) — a real model change
  (schema, allocation, receipts). **Recommend (a) now**, (b) only if a scenario needs it.

### G4 (P2). Reply vocabulary is not aligned with standard response codes

- **Practice:** line status codes: accepted (IA), accepted with changes (IC), quantity changed (IQ), date
  rescheduled (DR), rejected (IR), backordered (IB), substitution (IS) (§4 [S41]); EDIFACT ORDRSP accept / amend /
  reject (§4 [S44]).
- **Ours:** ACCEPT / COUNTER / REJECT. COUNTER mixes quantity change and date change; the code already separates
  them internally (quantity counter → reallocation/re-sourcing; date-only counter → expedite, decided 2026-10-19).
- **Fix:** document a mapping (ACCEPT↔IA, COUNTER quantity↔IQ, COUNTER date↔DR, both↔IC, REJECT↔IR) in the supplier
  interface doc and store the derived code in the audit. No behaviour change; makes a future EDI/portal adapter
  a mapping, not a redesign. Substitution (IS) stays unsupported (item is fixed).

### G5 (P2). No reminders before a deadline fails the Leg

- **Practice:** unconfirmed orders get **timed reminders**, typically up to three levels, before escalation
  (§3 [S26], §4 [S27][S37]).
- **Ours:** silence for 24 h → Leg FAILED `timeout` (then re-sourcing, per 2026-10-19). One missed message costs the
  supplier the order.
- **Fix:** one or two reminder messages (e.g. at 50% and 90% of the deadline) that do not use a round. Needs
  something that runs on time; with no scheduler it fits the future Purchasing deadline worker that will also call
  `/re-source`. **Recommend: design now in the re-sourcing ADR as future work; build with the worker.**

### G6 (P2). No tolerance for small changes

- **Practice:** supplier changes within a configured **tolerance** are auto-accepted; default tolerance is 0
  (§4 [S33][S35]); SAP recommends ≥ 10% quantity tolerance on the network (§4 [S37]).
- **Ours:** tolerance is effectively 0: any different quantity caps and reallocates/re-sources.
- **Assessment:** an *under*-quantity tolerance would silently change the requester's quantity, which the
  2026-10-19 decisions forbid. A small *date* tolerance would change the required date, also forbidden.
  **Recommend: keep 0 (matches Oracle's default) and record it as a conscious choice.** Over-quantity within MOQ or
  pack rounding is covered by G8.

### G7 (P3). No supplier-initiated change after agreement

- **Practice:** sellers send changes on their own (X12 865, EDIFACT ORDRSP amendments) and the buyer accepts or
  rejects them (§4 [S42][S44]); confirmations with new dates/quantities feed MRP (§7 [S27]).
- **Ours:** after a Leg agrees the chat input closes; supplier changes are future scope (Scenario Manager,
  Invalidated Agreements).
- **Fix later:** treat a post-agreement supplier change as reopening the Leg (Engine AGREED → OPEN already exists)
  and run the normal reply rules (reallocate → re-source → counter-back → fail). After commitment it becomes an
  Invalidated Agreement and a Pub/Sub event (`SupplierDeliveryDelayed`), owned by the integration work.

### G8 (P3). Supplier quantity rules beyond MOQ

- **Practice:** min, max and **multiple (pack size)** per supplier, rounding up (§2 [S13]–[S16]).
- **Ours:** MOQ only; whole units.
- **Fix later:** add `order_multiple` (and optionally `max_order_qty`) to supplier items and round each Leg up in
  allocation (surplus counted in cost, as with MOQ). Touches Supplier Service schema, selection, seed data.

### G9 (P3). Lead time has no receiving/processing time

- **Practice:** buyer processing + supplier delivery + **goods-receipt processing** time, back-scheduled from the
  need (§3 [S21]); safety time buffers (§3).
- **Ours:** "arrives by the required date" = supplier lead time only. Material that arrives on the required date is
  not yet usable.
- **Fix at integration:** the receiving buffer belongs to the **Warehouse Agent** (receiving capacity) and the
  required date's meaning to the requester. Agree whether `required_date` is "arrive by" or "available by" before
  integration. No change now.

### G10 (P3). Approval has no authority limits or segregation of duties

- **Practice:** approval by amount and document type; changes above a threshold re-trigger approval; SoD separates
  ordering, receiving and paying (§5 [S47][S48][S49]).
- **Ours:** any `decided_by` string approves any amount; no identity check.
- **Fix later:** value-based approval levels (the agreement's Total Purchasing Cost is already known when priced)
  and real user identity once authentication exists. Note that an unpriced agreement has no value to check.

### G11 (P3). Supplier identity and access in the chat

- **Practice:** supplier portals and EDI identify the trading partner (§4 [S30][S36]).
- **Ours:** the test channel shows every supplier's conversation to anyone (documented test-build limit).
- **Fix at integration:** per-supplier access (authentication, a supplier sees only its Legs).

---

## 4. Other gaps (not supplier communication)

| # | Gap | Practice | Ours | Priority |
| --- | --- | --- | --- | --- |
| G12 | Contract target quantity / value and consumption | Contracts have targets; releases consume them; over target warns/blocks (§1 [S6]) | Unit price + validity only | P3 |
| G13 | Quantity price scales | Conditions with price scales by quantity (§1 [S5]) | One unit price per contract | P3 |
| G14 | Quota arrangements / planned dual sourcing | Split by explicit % with history (§1 [S3][S7]) | Splits only for necessity or ≥ 10% saving | P3 (risk policy, needs a decision) |
| G15 | Supplier performance in selection | Scores from on-time and quantity reliability; inform the buyer, not automatic (§6 [S50]) | None | **Out** (spec: no reliability ratings). Practice supports keeping them out of automatic ranking. |
| G16 | Price negotiation | Price changes are restricted, often forbidden in portals (§4 [S31]) | Never negotiated (ADR-002) | **Out**, and consistent with practice |
| G17 | Firm / frozen zones | Near-term plans protected; changes suggested, a person decides (§3 [S23]) | Not applicable until Planning integration | **Out** for Purchasing |

---

## 5. One divergence worth keeping, deliberately

**Practice:** exceptions produce *suggestions* and a person decides (§3 [S16], §7).
**Ours (2026-10-19):** re-sourcing runs automatically.
**Why it is acceptable:** the project's goal is autonomous agents; every automatic step is deterministic, audited,
bounded (per-supplier round budget, failed suppliers excluded) and nothing is committed without human approval of
the final agreement. Recommend stating this trade-off explicitly in ADR-003.

---

## 6. Recommended next steps

1. **Into the re-sourcing ticket (ticket 12):** G1 (tentative agreement wording) and G2 (order release on
   approval) — both small, and re-sourcing makes G1 more urgent because agreed suppliers can now be dropped more
   often (N9).
2. **Write into ADR-003:** G5 reminders as future work for the deadline worker; G6 tolerance = 0 by choice; §5's
   divergence.
3. **Supplier interface doc:** G3 option (a) behaviour and the G4 response-code mapping.
4. **Integration backlog:** G7, G9, G10, G11; product backlog: G8, G12–G14.

## 7. Open decisions for the developer

- G1/G2: accept "subject to approval" wording + an order release message in ticket 12?
- G3: one delivery per Leg (recommended) or schedule lines?
- G6: confirm tolerance = 0?
- G9: is `required_date` "arrive by" or "available by"? (Integration question; involves Warehouse.)
- G14: is planned dual sourcing (risk spreading) a goal, or only necessity/cost splits?

## Decision (2026-10-20)

Gaps to cover, after ticket 12 (re-sourcing): G1, G2, G3, G4, G5, G8, G12, G13, G14. Not now: G6 (tolerance stays 0), G7, G9, G10, G11.
