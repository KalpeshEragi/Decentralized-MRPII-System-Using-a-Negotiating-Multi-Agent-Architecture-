# C4 — Negotiation Protocol

## Status

**Status:** DRAFT

**Owner:** Dev 2

**Reviewed By:** Pending (Dev 1)

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
- Supplier response API request/response models (C5, Phase 3).
- Approval, replanning and the attempt counter (C8).
- Cost or price in any form (out of scope for the 25%).

## Specification

Items marked **PENDING** must not be guessed during implementation. See `docs/DECISIONS.md` for each `P0-xx` item.

### 1. Participants and Initiation

- The **Inventory Agent** detects a shortage and initiates procurement negotiation with the **Purchasing Agent** over A2A, sending the shortage/procurement context (P0-02).
- The **Purchasing Agent** handles supplier interaction through the supplier communication interface. There is no Supplier Agent; in the demo the tester acts as the supplier.
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

Finalized 25% negotiation factors (`dev_docs/DECISIONS.md`, Factors):

- material quantity
- required date
- delivery date / lead time
- inventory impact
- production priority

Rules:

- No cost or price field.
- Priority is an integer 1–5, `1` = highest (P0-15).
- Dates are whole days (P0-16).

The `OfferTerms` field names are **PENDING**. Existing examples use `quantity`, `delivery_date`,
`priority` (`database_schema.md`) and `quantity`, `required_date`, `delivery_date` (C6, provisional).

### 6. Message Flow

From `system_spec.md` §5.5:

1. The initiator sends a `REQUEST`.
2. The responder sends an `OFFER`, or `REJECT`.
3. Either side sends a `COUNTER_OFFER` within its own `reserved_limits`, or sends `ACCEPT`.
4. A party sends `AGREEMENT_PROPOSED`.
5. The agreed terms are validated deterministically (`validated`).
6. `COMMIT`. The state change happens through the owning service (`committed`). It is never done by the LLM or the engine.

### 7. Supplier Rounds

- Maximum 3 supplier rounds per negotiation session, shown as "Round N of 3".
- One supplier response per round. The structured supplier response has: quantity, delivery date/lead time, and an optional message. No price/cost field.
- The tester provides supplier-side responses only and does not end the negotiation.
- The Purchasing Agent alone decides `ACCEPT`, `REJECT` or `COUNTER`.
- No agreement within 3 rounds → the session ends `FAILED`.

Source: `dev_docs/DECISIONS.md` (Supplier UI, Round limit).

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
| Manage timeouts | Replace agent autonomy |
| Persist messages, offers and agreements | |
| Enforce state transitions and the round limit | |

### 10. Persistence

| Protocol fact | Table |
| --- | --- |
| Session | `negotiation.negotiation_sessions` |
| Participants | `negotiation.negotiation_participants` |
| Messages | `negotiation.negotiation_messages` |
| Offers and counter-offers | `negotiation.negotiation_offers` (`valid_until` nullable, P0-06) |
| Agreements | `negotiation.negotiation_agreements` (`validated`, `committed`) |

### 11. Open Items

- **PENDING D9:** who may send `AGREEMENT_PROPOSED` and `COMMIT`; round and session timeout values.
- **PENDING:** final serialized envelope schema and `OfferTerms` field names, including how "inventory impact" and "lead time" are represented.
- **PENDING (Phase 4):** content of the shortage-context message. Inventory (Dev 2) drafts it; Purchasing (Dev 1) reviews.
- **PENDING P0-12:** read path from committed agreements to scheduled receipts (with C2).
- **To confirm:** whether Planning ↔ Inventory allocation uses a negotiation session. `system_spec.md` §2 shows Planning sending `REQUEST` to Inventory; P0-02 superseded only the Planning → Purchasing path.
- **To confirm:** values of `negotiation_type` and participant `role`.
- **Discrepancy to resolve:** the supplier communication interface is not an agent, but `negotiation_messages` sender/receiver columns reference `agent.agents`. How supplier rounds are represented in messages is not defined (see C2).
- **PENDING D13:** A2A SDK compatibility with the OpenAI Agents SDK and Ollama no-reasoning mode (Phase 2 spike).
