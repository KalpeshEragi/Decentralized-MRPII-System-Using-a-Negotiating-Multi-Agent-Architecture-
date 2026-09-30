# C4 — Negotiation Protocol

## Status

**Status:** CONFIRMED (2026-09-30) · open items stay PENDING

**Owner:** Project developer

**Reviewed:** 2026-09-30 (see Review)

## Purpose

Defines the negotiation envelope, offer terms, message types and session statuses (including `FAILED`)
that agents and the Negotiation Engine exchange and persist.

## Scope

- Negotiation participants and who initiates.
- Message types, session statuses and the session lifecycle.
- The message envelope.
- Offer terms (the finalized negotiation factors).
- The supplier round limit and supplier responses.
- Agreement criteria.
- What the Negotiation Engine may and must not do.
- Where protocol facts are persisted.

**Implemented in (Phase 1):** `backend/app/schemas/negotiation.py`, `backend/app/negotiation/`. Transport: official A2A Python SDK over HTTP.

## Does Not Define

- How an agent decides to accept, reject or counter. That is each agent's own logic.
- Table and column definitions (C2, `database_schema.md`).
- Agent state (C6) or audit records (C7).
- Supplier response API request/response models (C5, Phase 2).
- Approval, replanning and the attempt counter (C8).
- Cost or price in any form (out of scope for the 25%).

## Specification

Items marked **PENDING** must not be guessed during implementation. See `docs/DECISIONS.md` for each `P0-xx` item.

### 1. Participants and Initiation

- The **Inventory Agent** detects a shortage and initiates procurement negotiation with the **Purchasing Agent** over A2A, sending the shortage/procurement context (P0-02).
- The **Purchasing Agent** handles supplier interaction through the supplier communication interface, sender type `SUPPLIER_INTERFACE`.
  **Supplier = data/service/interface. Supplier Agent = not part of the 25% implementation.** In the demo the tester acts as the supplier through the form.
- **COMMIT is not an agent decision** (see §6): only the application/approval workflow (sender type `APPROVAL_WORKFLOW`, not an agent) sends it.
- The **Production Planning Agent** receives the result (agreement or `FAILED`) and uses it for plan evaluation and replanning.
- Planning's MRP net requirement and Inventory's shortage detection both come from the same deterministic services (P0-02).

Sources: `dev_docs/DECISIONS.md` (Shortage flow, Supplier), P0-02.

### 2. Message Types

```text
REQUEST
OFFER
COUNTER_OFFER
ACCEPT
REJECT
AGREEMENT_PROPOSED
COMMIT
```

Message types are separate from session statuses (P0-05). `WITHDRAW` and `ABORT` are possible extensions and are not part of the 25% (`system_spec.md` §5.1).

### 3. Session Statuses and Lifecycle

```text
INITIATED
NEGOTIATING
AGREEMENT_PROPOSED
COMMITTED
REJECTED
ABORTED
EXPIRED
FAILED
```

Lifecycle (`system_spec.md` §5.4):

```text
INITIATED → NEGOTIATING → (OFFER / COUNTER_OFFER)* → AGREEMENT_PROPOSED → COMMITTED
End statuses: COMMITTED, REJECTED, ABORTED, EXPIRED, FAILED
```

- `FAILED` means no feasible agreement was reached within the round limit. It is a distinct end status, not `REJECTED`, `ABORTED` or `EXPIRED`.
- After `FAILED` the shortage stays unresolved, the plan is not updated, and the failure is recorded and visible in the dashboard/decision log.
- `completed_at` is set only when the session reaches an end status (P0-04).

Sources: P0-05, `dev_docs/DECISIONS.md` (Failure).

### 4. Envelope

Field list proposed in `system_spec.md` §5.2. The final serialized schema is **PENDING**.

```text
protocol_version
message_id
negotiation_id
sender        { agent_id, agent_type }
receiver      { agent_id, agent_type }
message_type  (§2)
sequence_number
timestamp
correlation_id
payload
```

### 5. Offer Terms

`OfferTerms` has exactly these fields (P1-05, final):

| Field | Type | Notes |
| --- | --- | --- |
| `quantity` | Decimal > 0 | Material quantity. |
| `required_date` | date | Latest acceptable delivery (the shortage `required_by`). Required in `REQUEST`. |
| `delivery_date` | date | The negotiated delivery commitment. Required in `OFFER`, `COUNTER_OFFER`, `AGREEMENT_PROPOSED`. |
| `priority` | integer 1–5 | `1` = highest (P0-15). |

Not offer terms: **lead time** (comes from supplier data; `delivery_date` is the commitment), **inventory impact**
(calculated by deterministic application logic) and **price/cost** (out of scope). Unknown fields are rejected.
Dates are whole days (P0-16). The five finalized negotiation *factors* (`dev_docs/DECISIONS.md`) still guide agent
reasoning; only the four fields above travel in offers.

### 6. Message Flow

One negotiation session per shortage (P0-02, P1-04, P1-07):

1. The **Inventory Agent** sends `REQUEST` to the **Purchasing Agent** with the shortage/procurement context. Session → `NEGOTIATING`.
2. Purchasing negotiates with the supplier interface in rounds (§7).
3. When a supplier response is acceptable to Purchasing, **Purchasing sends `AGREEMENT_PROPOSED`** to Inventory.
   Session → `AGREEMENT_PROPOSED`.
4. The agreed terms are validated deterministically (`negotiation_agreements.validated`). The result goes to Planning.
5. `AGREEMENT_PROPOSED` → human approval → the application/approval workflow performs `COMMIT`. Session → `COMMITTED`.
   `COMMIT` is an approval/lifecycle action, not a negotiation decision: Inventory and Purchasing must not commit an
   agreement themselves. The protocol accepts `COMMIT` only from sender type `APPROVAL_WORKFLOW` and only from status
   `AGREEMENT_PROPOSED`. The state change (e.g. reservation) happens through the owning service, never by the LLM or the engine.
   The approval workflow itself, and what happens to an uncommitted agreement when the plan is rejected: **PENDING C8** (Phase 4).

Timeouts (P1-04): no timers, background jobs or automatic expiry in the 25% milestone. The session is bounded by the
3-round limit. `negotiation_sessions.deadline` holds the shortage's required-by date (latest acceptable delivery) and is
used for validation only. `negotiation_offers.valid_until` stays `NULL`. `EXPIRED` is not produced automatically.

### 7. Supplier Rounds

- One **round** = one Purchasing `OFFER` (round 1) or `COUNTER_OFFER` (rounds 2–3) to the supplier interface + the supplier's
  response. Maximum 3 rounds per session, shown as "Round N of 3" (P1-07).
- The supplier responds once per round through the structured form: `ACCEPT`, `COUNTER_OFFER` (quantity, delivery date /
  lead time, optional message) or `REJECT`. No price/cost field.
- The tester provides supplier-side responses only and does not otherwise end the negotiation.
- The Purchasing Agent alone decides whether a supplier response is acceptable (→ `AGREEMENT_PROPOSED`) or whether to send
  a `COUNTER_OFFER` in the next round.
- `REJECT` may be sent by the supplier interface, or by Purchasing on its turn at any time before the round limit
  (Purchasing is not forced to continue to round 3 when it has no acceptable proposal). Either produces status
  `REJECTED`, which is terminal.
- No acceptable supplier response after round 3 (a further Purchasing `COUNTER_OFFER` would be round 4) → the session ends `FAILED`.
- `REJECTED` = explicit participant rejection. `FAILED` = round limit reached without agreement.
- **Outcome reported to Planning:** agreement, or the normalized result `FAILED` whenever no agreement is reached
  (session `REJECTED` or `FAILED`). After `FAILED` the shortage stays unresolved and the plan is not updated.

Source: `dev_docs/DECISIONS.md` (Supplier UI, Round limit), `docs/DECISIONS.md` P1-04, P1-07.

### 8. Agreement

An agreement requires that:

- the agents accept;
- hard constraints are satisfied;
- preferences/bounds are satisfied;
- the shortage is feasibly resolved;
- the agreement is recorded by the negotiation system.

Deterministic validation is the authority on feasibility. Committed agreements (agreed quantity and delivery date) are the scheduled receipts used for projected availability (P0-12).

Source: `dev_docs/DECISIONS.md` (Agreement).

### 9. Negotiation Engine Boundary

From `system_spec.md` P3:

| The engine MAY | The engine MUST NOT |
| --- | --- |
| Create sessions, register participants, track state | Choose a winner |
| Validate messages, sender, receiver and sequence | Decide outcomes |
| Route messages | Override agent preferences or constraints |
| Manage timeouts (none in the 25%, P1-04) | Replace agent autonomy |
| Persist messages, offers and agreements | |
| Enforce state transitions and the round limit | |

### 10. Persistence

| Protocol fact | Table |
| --- | --- |
| Session | `negotiation.negotiation_sessions` |
| Participants | `negotiation.negotiation_participants` |
| Messages | `negotiation.negotiation_messages` (`sender_type` / `receiver_type` plus nullable agent ids; supplier interface and approval workflow messages have no agent id, P2-01) |
| Offers and counter-offers | `negotiation.negotiation_offers` (`valid_until` nullable, P0-06) |
| Agreements | `negotiation.negotiation_agreements` (`validated`, `committed`) |

### 11. Open Items

- **Decided (P1-05):** `OfferTerms` fields (§5). The envelope is the Phase 1 model in `backend/app/schemas/negotiation.py` (`protocol_version` "1.0", string ids, `sequence_number` from 1, `timestamp`, optional `correlation_id`, `payload` = optional `terms` + optional `message`); how it is carried in an A2A message waits for the Phase 2 spike (D13).
- **Decided (P1-07):** Purchasing may `REJECT` early; sender type `SUPPLIER_INTERFACE` is the supplier form, not an agent.
- **Decided (P2-01):** supplier-side messages are stored with `sender_type` / `receiver_type` and a null agent id. The offers table holds every OFFER / COUNTER_OFFER that opens or answers a round (a Purchasing counter that trips the round limit is stored as a message only). The envelope travels as one data part of an A2A `SendMessage` (three endpoints, same app). Earlier open question, now answered: how supplier-side messages are stored while `negotiation_messages` sender/receiver reference `agent.agents` (Phase 2).
- **Decided (P1-04):** `COMMIT` is sent only by the approval workflow after human approval. **PENDING C8:** the approval workflow itself and the fate of an uncommitted agreement after plan rejection (Phase 4).
- **PENDING (Phase 3):** content of the shortage-context message sent by Inventory to Purchasing.
- **PENDING P0-12:** read path from committed agreements to scheduled receipts (with C2).
- **PENDING P1-06:** whether Planning ↔ Inventory allocation uses a negotiation session (Phase 3).
- **To confirm:** values of `negotiation_type` and participant `role`.
- **PENDING D13:** A2A SDK compatibility with the OpenAI Agents SDK and Ollama no-reasoning mode (Phase 2 spike).

## Review

**2026-09-30 — CONFIRMED.** Final decisions closing the Phase 1 items: `OfferTerms` fixed to four fields (P1-05);
`SUPPLIER_INTERFACE` is the supplier form, not an agent; Purchasing may `REJECT` early and either participant's
`REJECT` gives `REJECTED` (P1-07); `COMMIT` belongs to the approval workflow (P1-04).
