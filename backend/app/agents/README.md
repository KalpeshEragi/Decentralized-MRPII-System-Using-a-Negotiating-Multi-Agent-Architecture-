# backend/app/agents

The three 25% agents (Phase 3). Agents call services, never tables (except their own C6 state row through `base.py`).
Business figures come from deterministic services; the LLM only proposes, and deterministic rules decide.

| File | Purpose |
| --- | --- |
| `base.py` | C6 state shapes (`AgentStateData`, no cost/price keys, max 3 rounds) and the per-agent state store; `offer_history` (rebuilt from stored session messages); `build_message` (next C4 envelope); LLM client hook (`llm_client`, `set_llm_client`); `Agent` with `audit` (C7, through `audit_service`) and `send` (A2A, commits first). |
| `planning/planning_agent.py` | Production Planning Agent: `handle_order` (plan through `planning_service`, requirements to Inventory), `on_procurement_result` (records AGREEMENT or FAILED), `procurement_results`. |
| `inventory/inventory_agent.py` | Inventory Agent: `assess_requirements` (availability through `inventory_service`, allocation proposal, one session + A2A `REQUEST` per shortage), `on_negotiation_result`. |
| `purchasing/purchasing_agent.py` | Purchasing Agent: pure policy (`limits_for`, `policy_decision`, `validate_proposal`, `decide`) and `PurchasingAgent.on_message` (requisition, LLM proposal, validation, `OFFER` / `COUNTER_OFFER` / `AGREEMENT_PROPOSED` / `REJECT` over A2A). |
| `workflow.py` | Routing only: an accepted A2A message to Purchasing makes Purchasing react; the message that ends the session (or proposes the agreement) makes Inventory receive the result and pass it to Planning. |

## Flow

```text
POST /agents/planning/orders/{id}
  Planning  -> planning_service.run_plan (MPS, capacity, BOM, MRP)
  Planning  -> Inventory.assess_requirements            (in-process; P1-06 still open)
  Inventory -> open session, REQUEST  --A2A-->  /a2a/purchasing
  Purchasing: requisition, LLM proposal -> validation -> OFFER to the supplier interface   (round 1 of 3)
```
**Broken since 2026-10-18:** the supplier interface (`/a2a/supplier-interface`, `/supplier-interface/...` and
`/negotiations/{id}/supplier-responses`) was removed, so the OFFER can't be delivered and no supplier can answer; this
legacy flow stops at the first offer. The new supplier chat is the Purchasing test channel.

Everything runs synchronously inside the HTTP request that started it (no event bus, no background jobs).

Phase 4 (C8, D8): each planning run is an attempt (at most 2). `POST /plans/{id}/attempts/{n}/approve` → approval
workflow COMMIT → Planning re-plans with the committed receipts → Inventory `reserve_for_order`.
`.../reject` → ABORT of uncommitted agreements → Planning `replan` as attempt 2 (Inventory opens new sessions for the
remaining shortages); rejecting attempt 2 → `HUMAN_INTERVENTION_REQUIRED`. Agents never approve, commit or abort.

## Rules kept here

- Inventory starts procurement; Purchasing owns requisitions (`requisition_service` refuses other agents) and all
  supplier-side decisions; Planning only receives results. No Supplier Agent: `SUPPLIER_INTERFACE` is a service.
- Purchasing limits come from supplier data and the shortage: quantity in `[max(shortage, MOQ), available_qty]`;
  own delivery dates in `[planning date + lead time, required_by]`; supplier dates accepted up to `required_by`.
  After round 3 an unacceptable response gets the round-limit counter, so the session ends `FAILED`; explicit `REJECT`
  (supplier, or Purchasing before the limit) ends it `REJECTED`.
- An LLM proposal that is unusable or breaks a limit is recorded (`LLM_PROPOSAL_REJECTED`) and replaced by the agent's
  own deterministic policy. `OfferTerms` carry only quantity, required date, delivery date, priority: no price.
- `AGREEMENT_PROPOSED` is not committed and nothing is reserved; human approval and `COMMIT` are Phase 4 (C8).
- C6 has one state row per agent: it describes the negotiation (or order) the agent handled last.

Tests: `tests/agents/` (policy and state, no database), (the end-to-end `tests/db/test_phase3_workflow.py` was removed 2026-10-18 with the supplier routes).
