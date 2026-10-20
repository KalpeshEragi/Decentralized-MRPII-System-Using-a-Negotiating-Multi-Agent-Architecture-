# backend/app/negotiation

Private negotiation between a starter (the agent with the problem) and an owner (the agent that owns the resource)
(`dev_docs/architecture/negotiation.md`). Shared infrastructure: it stores sessions and messages, checks the protocol
and moves messages over A2A. It never judges whether terms are acceptable — agents decide.

## Six-agent design (step 3)

| File | Purpose |
| --- | --- |
| `envelope.py` | `Envelope` (one message), `Terms` (multi-factor, `extra` for resource-specific fields; no price, cost or claimed priority), `Hold`, `MessageType`, `ResourceType`, `ReasonCode` (NG-6). |
| `state.py` | Pure session state machine (`apply`): turns, max 3 rounds, ACCEPT → AGREEMENT_PROPOSED with a hold and the same terms, COMMIT → owner ACCEPT (COMMITTED) or REJECT (REJECTED; `HOLD_EXPIRED` → EXPIRED), ABORT by the starter. |
| `models.py` | `negotiation.sessions` (with `case_id`), `negotiation.messages` (stored messages = receivers' inbox queue), `negotiation.outbox`. |
| `layer.py` | `send` (outbox, in the sender's transaction), `reply_to`, `receive` (validate + store + acknowledge; duplicates acknowledged; NG-5 one open negotiation per need), `register_inbox` (an agent's handler + its inbox registration), `send_outbox_item` (long-mode A2A send; with `ai_enabled` the text is reworded once before the first send, `app/llm/wording.py`), `outbox_registration`. |
| `transport.py` | A2A client: JSON-RPC `SendMessage`, envelope in one data part; `set_http_client` for tests. |
| `a2a_endpoints.py` | One official-A2A-SDK endpoint per agent at `/a2a/<agent>` with an agent card; store and acknowledge. Live now: Planning, Warehouse, HR. Inventory and Purchasing switch over when their old endpoints are retired. |

Flow: sender's transaction → `outbox` → (worker) A2A send → receiver's endpoint stores message + session change and
acknowledges → (receiver's inbox worker) agent handler → its replies go to the outbox again.

**Tests:** `backend/tests/platform/test_negotiation.py`.

## Old 25% protocol (retired in step 5)

`protocol.py`, `messages.py`, `session.py` (Inventory → Purchasing → supplier interface, COMMIT by the human approval
workflow) are still used by the old agents, services and `app/api/a2a.py`. Shapes in `app/schemas/negotiation.py`.
