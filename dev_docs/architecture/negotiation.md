# Private Negotiation

**Status:** APPROVED by the developer (2026-10-17). Nothing new here is implemented.
**Related:** `high_level_architecture.md` §6 (who negotiates with whom), `pubsub_event_channel.md` (events stay
separate), `quantity_accounting.md` (how holds and commitments change numbers), `../DECISIONS.md`.

## 1. Purpose

A negotiation is a private conversation between the agent that has a problem (the **starter**) and the agent that
owns the resource that can fix it (the **owner**). They exchange offers until they agree or stop. Only the agreed
outcome becomes public, as an event published by the owner.

## 2. Decisions (2026-10-17)

| ID | Decision |
| --- | --- |
| NG-1 | Keep A2A over HTTP as the interface between agents; add database-backed storage and delivery tracking underneath (§10). |
| NG-2 | Offers are non-binding. On agreement the owner places a **hold** (tentative reservation with expiry). |
| NG-3 | Owner queue order: dependencies ready → smallest deadline slack → waiting-time aging → first come, first served. |
| NG-4 | The starter sends `COMMIT` once its own dependencies are met and a deterministic execution policy passes. The owner re-checks and commits atomically, then publishes the event. Defined exceptions go to a human. |

## 3. Participants

| Role | Who | Does |
| --- | --- | --- |
| Starter | The agent with the problem (`high_level_architecture.md` §6) | Sends REQUEST, ACCEPT / COUNTER_OFFER / REJECT, COMMIT or ABORT |
| Owner | The agent that owns the resource | Sends OFFER / COUNTER_OFFER / REJECT, AGREEMENT_PROPOSED (with hold); performs the commit |
| Supplier interface | The simulated supplier adapter (not an agent) | Only in Purchasing's supplier sessions; designed with the Purchasing doc |

The negotiation layer (shared infrastructure) stores sessions and messages, checks message order, rounds and
timeouts. It never judges whether terms are acceptable.

## 4. Messages and session lifecycle

Message types (unchanged from the existing code): `REQUEST`, `OFFER`, `COUNTER_OFFER`, `ACCEPT`, `REJECT`,
`AGREEMENT_PROPOSED`, `COMMIT`, `ABORT`. Session statuses (unchanged): `INITIATED`, `NEGOTIATING`,
`AGREEMENT_PROPOSED`, `COMMITTED`, `REJECTED`, `ABORTED`, `EXPIRED`, `FAILED`.

```
Starter REQUEST ──> NEGOTIATING
  Owner OFFER | COUNTER_OFFER | REJECT
  Starter ACCEPT | COUNTER_OFFER | REJECT          (one round = one owner proposal + starter answer; max 3 rounds)
  after ACCEPT: Owner places hold, sends AGREEMENT_PROPOSED(hold id, expires_at) ──> AGREEMENT_PROPOSED
  Starter COMMIT ──> owner re-checks and commits atomically, then answers ACCEPT ──> COMMITTED  (owner publishes the event)
  Starter ABORT  ──> hold released ──> ABORTED
  hold expires (owner sends REJECT with HOLD_EXPIRED), or no answer within the response timeout ──> EXPIRED
  REJECT by either side ──> REJECTED;  3 rounds without agreement ──> FAILED
```

If the owner's re-check at `COMMIT` fails (facts changed, hold gone), it answers `REJECT` with reason `STALE` or
`UNAVAILABLE`; the session ends `REJECTED` and the starter replans or opens a new negotiation.

**Implementation details (step 3, 2026-10-17):** the owner confirms a commit with `ACCEPT` and reports an expired hold
with `REJECT` + `HOLD_EXPIRED`, so no new message types are needed. Sequence numbers are assigned by the receiving side
when it stores a message (the outbox keeps one session's messages in order), so a sender never has to guess the next
number. A session starts directly in `NEGOTIATING` when the REQUEST is stored.

## 5. Terms (multi-factor, no price)

Common fields in every REQUEST / OFFER / COUNTER_OFFER / AGREEMENT_PROPOSED:

| Field | Meaning |
| --- | --- |
| `resource_type` | `STOCK`, `SUPPLY`, `RECEIVING_SLOT`, `STORAGE_SPACE`, `WORKFORCE`, `PRODUCTION_CAPACITY` |
| `resource_ref` | Item, zone, skill, product |
| `quantity`, `unit` | Pieces, space units, worker-hours |
| `needed_by` / `available_from`, `date_from`–`date_to` | The dates that matter for this resource |
| `case_id`, `order_id` | Links to the cause and the order (for the owner's trusted checks) |
| `facts_version` | The owner's entity version the proposal is based on (stale check) |
| `reason_code` | On REJECT / COUNTER_OFFER: exactly one code from the fixed list (§5.1, NG-6) |

Resource-specific fields (shift, skill level, zone) are defined in each agent's doc. Priority is **not** a term the
starter can claim: the owner computes urgency itself (§7).

### 5.1 Reason codes (NG-6, 2026-10-17)

Every REJECT and COUNTER_OFFER carries exactly one of these. Purchasing may add supplier-specific codes in its doc.

| Code | Meaning |
| --- | --- |
| `INSUFFICIENT` | Not enough of the resource for the requested quantity |
| `TOO_LATE` | Possible only after the needed date |
| `NO_SPACE` | Storage space does not fit (Warehouse) |
| `NO_RECEIVING_CAPACITY` | Receiving capacity does not fit (Warehouse) |
| `NO_WORKFORCE` | Worker-hours of the skill do not fit (HR) |
| `POLICY_LIMIT` | A configured limit stops it (safety-stock release, overtime) |
| `OUTSIDE_HORIZON` | Nothing fits within the search horizon |
| `HARD_CONSTRAINT` | Another hard constraint would be violated |
| `STALE` | The facts the proposal was based on have changed |
| `UNAVAILABLE` | Lost at commit: the resource is no longer there |
| `HOLD_EXPIRED` | The hold expired before `COMMIT` |
| `INVALID_REQUEST` | The request itself is not valid (missing or wrong terms) |

**One at a time (NG-5):** a starter keeps at most one open negotiation per need and resource; if it fails, it opens
the next one. No alternative offers are held "just in case". The need is what the resource is for (`terms.order_id`:
a customer demand or a production order), so one case may ask for the same item or skill for two production orders.
Enforced by a partial unique index on (case, resource type, resource, need, starter, owner) over open sessions.

## 6. How an agent decides inside a negotiation

1. Deterministic code computes what is possible and the agent's limits (`reserved_limits`, hard constraints).
2. The LLM may suggest an offer or counter-offer and a short reason, inside those limits.
3. Code validates the suggestion. Invalid, late or failed model → the agent's deterministic policy answers instead.
4. Every message records who proposed it (policy or LLM) for the timeline.

## 7. The owner's queue and priority

Many starters may ask one owner at the same time. Each owner keeps its own queue of incoming requests:

1. **Ready check:** a request waiting on another result (dependency) is not picked yet. Hard constraints are never
   outweighed by anything below.
2. **Deadline slack:** smallest slack first. `slack_days = latest_start_date − today`, where
   `latest_start_date = needed_by − the owner's own lead time` for that resource (0 for stock on hand, supplier lead
   time for supply, and so on). The owner reads `needed_by` from trusted data (the order / plan via read functions),
   not from the message.
3. **Aging:** a request that has waited longer than a limit (starting value: 5 minutes real time) moves ahead of
   non-aged requests, so nobody starves.
4. **Tie:** first come, first served.

Independent requests (different resources) are handled in parallel. Requests for the same resource are serialized
by the owner's atomic check-and-update, so the same stock, space or hours can never be promised twice.

## 8. Holds and commitments

- A hold is placed only on agreement (`AGREEMENT_PROPOSED`). It reduces what the owner can promise to others
  exactly like a commitment (`quantity_accounting.md`), but it expires.
- Hold expiry: starting value 24 hours (simulated time), matching Sales' offer validity. No silent extension; the
  starter negotiates again.
- On expiry the owner releases the hold, the session becomes `EXPIRED`, and the owner publishes the availability
  change as a normal event.
- `COMMIT` makes the hold binding; the owner publishes its commitment event (`ReservationCommitted`,
  `ProcurementCommitted`, `ReceivingSlotCommitted`, `WorkforceCommitted`).

### Execution policy (when the starter may send COMMIT)

Planning, for a customer order, commits only when all hold:
1. The customer has confirmed (`OrderConfirmed`).
2. Every linked session of the case is in `AGREEMENT_PROPOSED` and not expired.
3. The plan is re-validated deterministically against current facts.

Escalated to a human (with a reason code) instead: a negotiation `FAILED` with no alternative; the follow-up depth
limit reached; a commit refused as `STALE` twice for the same case; repeated invalid LLM proposals.

There is no all-or-nothing transaction across agents. If one owner's commit fails after others succeeded, the
starter replans and releases what it no longer needs through `PlanRevised` (compensation, not rollback).

## 9. Stale information

- Each proposal carries `facts_version`. At `AGREEMENT_PROPOSED` and at `COMMIT` the owner re-checks current facts.
- When an event changes a resource that has open sessions, the owner re-checks them; sessions that can no longer be
  honored end `REJECTED` (`STALE`). Because a new fact arrived, the starter may open a new session (allowed by
  `high_level_architecture.md` §6.4).

## 10. Transport: A2A with durable storage

### 10.1 What exists today (inspected 2026-10-17)

| Part | State |
| --- | --- |
| A2A SDK | Official `a2a-sdk==1.2.0`, JSON-RPC binding, method `SendMessage`, protocol version 1.0 |
| Endpoints | `/a2a/inventory`, `/a2a/purchasing`, `/a2a/supplier-interface`, in the same FastAPI app (`app/api/a2a.py`) |
| Agent cards | One per endpoint at `<path>/.well-known/agent-card.json` |
| Payload | The negotiation envelope as one A2A data part; the acknowledgement comes back as one data part |
| Client | `app/core/a2a_client.py` `send()`; used by `agents/base.py` and `supplier_interface_service.py` |
| Validation and storage | `negotiation/messages.py` + `session.py`; `negotiation_service.submit_message` saves messages (`message_id` unique) |

**Does it follow A2A?** Yes, for a simple message exchange: official SDK, agent cards, JSON-RPC `SendMessage`, data
parts. It does not use A2A Tasks (long-running work states); for an immediate acknowledgement that is allowed and
not needed.

### 10.2 Gaps against the agreed design

| # | Gap | Effect |
| --- | --- | --- |
| G1 | The endpoint waits until the receiving agent has reacted (`workflow.after_delivery`), which can include LLM calls and further A2A calls (timeout 300 s) | One slow model call holds a whole chain of HTTP requests |
| G2 | If the reaction fails or the program restarts, nothing retries (only a log line, `reaction_error`). A failed send is not retried either | Messages can be stored but never acted on |
| G3 | A repeated message is answered as an error (`CONFLICT`) | A safe retry looks like a failure |
| G4 | Routes and participants are fixed to Inventory → Purchasing → supplier interface; `COMMIT` only from the human approval workflow | Does not support any starter/owner pair or starter COMMIT |
| G5 | No endpoints for Planning, Warehouse, HR | They cannot negotiate |

### 10.3 Proposal (smallest change that keeps A2A)

Keep: the SDK, endpoints, agent cards, envelope-in-a-data-part, the client, protocol validation and the existing
negotiation tables. Add durability on both sides:

```
Starter's transaction: own change + row in negotiation_outbox (PENDING)
   → dispatcher sends it with a2a_client.send (A2A HTTP)          [retries on network failure]
   → receiver's A2A endpoint: validate, update session, save message (handle_status PENDING), acknowledge at once
   → dispatcher runs the receiver's handler; handler changes + handle_status DONE in one transaction  [retries]
   → handler may write the next outbox row
```

- **Outbox** (new small table `negotiation_outbox`): envelope, status, attempts, next attempt. Acknowledged or
  "already received" → `SENT`. Network failure → retry with the event channel's waits. Protocol refusal → `FAILED`,
  shown in the timeline, not retried.
- **Inbox**: two columns on the existing `negotiation_messages` (`handle_status`, `attempts`/`next_attempt_at`).
- **Duplicates**: a repeated `message_id` is acknowledged as `accepted, duplicate` (not an error).
- **Separate from events**: own tables and own handler list; never written to `events`. Only the small
  claim-and-retry helper code is shared with the event dispatcher.

| Gains | Losses |
| --- | --- |
| Keeps the A2A standard and the existing code | An HTTP hop inside the same program (small delay per message) |
| Restart-safe, retried, no nested waiting chains | Two durable steps (outbox and inbox) instead of one |
| Agents could later be moved into separate programs without changing the wire | Slightly more to test than a database-only design |

### 10.4 Build steps (later, Phase 3; one step at a time, each tested)

1. Endpoint becomes "store and acknowledge"; the reaction moves to the inbox dispatcher (fixes G1, half of G2).
2. Outbox with retries; duplicates acknowledged as success (fixes G2, G3).
3. Generic starter/owner roles and one endpoint per negotiating agent (fixes G4, G5). Contract change first.
4. Holds on agreement and starter `COMMIT` under the execution policy; the old human-approval `COMMIT` path retires.

## 11. Example: Planning asks Inventory for 500 units of item X

1. Planning (starter) → Inventory: `REQUEST` STOCK, item X, 500, needed_by 2026-11-10, order O-1, case C-1.
2. Inventory checks its queue order (§7), computes available = 1 200, sends `OFFER` 500 by 2026-11-10.
3. Planning `ACCEPT`. Inventory places a 24 h hold of 500 → `AGREEMENT_PROPOSED` (hold H-9). Available to others: 700.
4. Customer confirms (`OrderConfirmed`). Planning's policy passes → `COMMIT`.
5. Inventory re-checks, turns H-9 into reservation R-31, publishes `ReservationCommitted`. Session `COMMITTED`.

## 12. Open

| ID | Question |
| --- | --- |
| NG-O1 | Purchasing ↔ supplier interface session details (with the Purchasing doc). |
| NG-O2 | Resolved 2026-10-17: response timeouts count in real time only to catch stuck work; business deadlines count in simulated days; Play waits for quiet (`demo.md` §6). |
| NG-O3 | Resolved 2026-10-17 (NG-5): one open negotiation per need and resource; no parallel alternative holds. |
| NG-O4 | Resolved 2026-10-17 (NG-6): fixed list in §5.1. |
