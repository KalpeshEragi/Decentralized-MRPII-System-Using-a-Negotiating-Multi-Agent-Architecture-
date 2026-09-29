# C6 — Agent State JSON Shapes

**Status:** DRAFT · **Drafted by:** Dev 1 · **Reviewed by:** Dev 2 (pending)
**Implemented in:** Phase 2 ORM for `agent.agent_state` (Dev 2, C2), Phase 4 `backend/app/agents/base` (paired).

Defines the JSON stored in the `agent.agent_state` JSONB columns (`database_schema.md` §7) for the
three 25% agents: `PRODUCTION_PLANNING_AGENT`, `INVENTORY_AGENT`, `PURCHASING_AGENT`.

Agent state holds **decision and negotiation context only**. Business truth (stock, BOM, supplier
data, plans, negotiation records) stays in its owning tables and services.

---

## 1. Rules

1. **One owner.** Each row is read and written only by its own agent, through the agent state
   service in `agents/base` (Phase 4). No agent reads or writes another agent's state.
2. **No duplication of business tables.** Store references (`order_id`, `negotiation_id`, `item_id`)
   and the few numbers the agent negotiates with. Do not copy inventory balances, BOMs or supplier lists.
3. **Validated before write.** LLM output is never written directly. It is parsed into a structured
   proposal, validated deterministically, and only the resulting decision is stored.
4. **Concise rationale only.** `dialogue_history` stores short summaries, never chain-of-thought.
5. **No cost/price** fields anywhere.
6. **Bounded history.** Offer and dialogue histories cover the **current** negotiation only (at most
   3 supplier rounds). Past sessions are read from `negotiation.*` tables, not kept here.
7. **Not here:** the planning-attempt counter and approval state (**PENDING C8**; roadmap proposes the plan record).

## 2. Common field shapes

| Column | Shape |
| --- | --- |
| `current_goal` | `{ "goal_type": string, "description": string, "refs": Refs }` |
| `current_task` | `{ "task_type": string, "status": "IDLE" \| "IN_PROGRESS" \| "WAITING" \| "DONE", "refs": Refs, "started_at": datetime \| null }` |
| `preferred_terms` | C4 `OfferTerms` — **PENDING C4** |
| `reserved_limits` | Agent-specific hard limits (§3). |
| `initial_proposal` | C4 `OfferTerms` — **PENDING C4** — or `null`. |
| `own_offer_history` | list of `OfferRecord` |
| `opponent_offer_history` | list of `OfferRecord` |
| `dialogue_history` | list of `DialogueEntry` |
| `negotiation_rules` | `{ "max_rounds": 3, "policy": { agent-specific policy, §3 } }` |

```text
Refs         = { "order_id"?: uuid, "mps_entry_id"?: uuid, "item_id"?: uuid, "negotiation_id"?: uuid }
OfferRecord  = { "negotiation_id": uuid, "message_id": uuid, "round": 1..3,
                 "message_type": C4 message type, "terms": C4 OfferTerms, "at": datetime }
DialogueEntry = { "round": 1..3 | null, "counterpart": "PLANNING" | "INVENTORY" | "PURCHASING" | "SUPPLIER_INTERFACE",
                  "summary": string, "at": datetime }
```

`SUPPLIER_INTERFACE` is the supplier communication interface (the tester in the demo), not an agent.

**PENDING P0-09 (with C2):** agent-specific policy items live inside `negotiation_rules.policy`
(proposed; no extra columns). `max_rounds` = 3 is finalized in `DECISIONS.md`.

## 3. Agent-specific content

Terms fields below are written as they are expected to appear in C4; they are **PENDING C4** and
will be renamed to C4's field names if they differ.

### 3.1 Production Planning Agent

- `reserved_limits`: `{ "latest_completion_date": date, "min_quantity": number }`
- `negotiation_rules.policy`: `planning_preferences`, `planning_constraints`, `priority_policy`, `decision_context`

```json
{
  "current_goal": { "goal_type": "FULFIL_ORDER", "description": "Fulfil SO-0001 by due date",
                    "refs": { "order_id": "6f1c0e2a-0000-4000-8000-000000000100" } },
  "current_task": { "task_type": "AWAIT_NEGOTIATION_RESULT", "status": "WAITING",
                    "refs": { "negotiation_id": "6f1c0e2a-0000-4000-8000-000000000500" },
                    "started_at": "2026-10-01T09:00:00Z" },
  "preferred_terms": { "quantity": 100, "required_date": "2026-10-05" },
  "reserved_limits": { "latest_completion_date": "2026-10-08", "min_quantity": 100 },
  "initial_proposal": null,
  "own_offer_history": [],
  "opponent_offer_history": [],
  "dialogue_history": [],
  "negotiation_rules": { "max_rounds": 3,
                         "policy": { "priority_policy": "minimize production delay",
                                     "planning_preferences": {}, "planning_constraints": {},
                                     "decision_context": {} } }
}
```

### 3.2 Inventory Agent

- `reserved_limits`: `{ "minimum_reserve": number, "max_allocation": number }` —
  `max_allocation` is copied from the inventory service result for the current request, never estimated.
- `negotiation_rules.policy`: `allocation_policy`, `safety_stock_policy`, `minimum_reserve`, `acceptable_allocation_range`

```json
{
  "current_goal": { "goal_type": "ALLOCATE_WITHIN_CONSTRAINTS", "description": "Allocate Component A for SO-0001",
                    "refs": { "order_id": "6f1c0e2a-0000-4000-8000-000000000100",
                              "item_id": "6f1c0e2a-0000-4000-8000-000000000001" } },
  "current_task": { "task_type": "ASSESS_AVAILABILITY", "status": "IN_PROGRESS",
                    "refs": { "item_id": "6f1c0e2a-0000-4000-8000-000000000001" },
                    "started_at": "2026-10-01T09:00:00Z" },
  "preferred_terms": { "quantity": 100 },
  "reserved_limits": { "minimum_reserve": 40, "max_allocation": 100 },
  "initial_proposal": { "quantity": 100 },
  "own_offer_history": [],
  "opponent_offer_history": [],
  "dialogue_history": [],
  "negotiation_rules": { "max_rounds": 3,
                         "policy": { "allocation_policy": "priority then required date",
                                     "safety_stock_policy": "never allocate below safety stock",
                                     "minimum_reserve": 40,
                                     "acceptable_allocation_range": { "min": 80, "max": 100 } } }
}
```

### 3.3 Purchasing Agent

- `reserved_limits`: `{ "latest_acceptable_delivery": date, "min_quantity": number, "max_quantity": number }`
- `negotiation_rules.policy`: `procurement_strategy`, `delivery_preferences`, `supplier_evaluation_policy`, `acceptable_quantity_range`, `latest_acceptable_delivery`

```json
{
  "current_goal": { "goal_type": "SECURE_MATERIAL", "description": "Procure 50 Component A by 2026-10-05",
                    "refs": { "item_id": "6f1c0e2a-0000-4000-8000-000000000001",
                              "negotiation_id": "6f1c0e2a-0000-4000-8000-000000000500" } },
  "current_task": { "task_type": "EVALUATE_SUPPLIER_RESPONSE", "status": "IN_PROGRESS",
                    "refs": { "negotiation_id": "6f1c0e2a-0000-4000-8000-000000000500" },
                    "started_at": "2026-10-01T09:05:00Z" },
  "preferred_terms": { "quantity": 50, "delivery_date": "2026-10-05" },
  "reserved_limits": { "latest_acceptable_delivery": "2026-10-07", "min_quantity": 50, "max_quantity": 60 },
  "initial_proposal": { "quantity": 50, "delivery_date": "2026-10-05" },
  "own_offer_history": [
    { "negotiation_id": "6f1c0e2a-0000-4000-8000-000000000500",
      "message_id": "6f1c0e2a-0000-4000-8000-000000000601", "round": 1,
      "message_type": "REQUEST", "terms": { "quantity": 50, "delivery_date": "2026-10-05" },
      "at": "2026-10-01T09:05:00Z" }
  ],
  "opponent_offer_history": [
    { "negotiation_id": "6f1c0e2a-0000-4000-8000-000000000500",
      "message_id": "6f1c0e2a-0000-4000-8000-000000000602", "round": 1,
      "message_type": "OFFER", "terms": { "quantity": 50, "delivery_date": "2026-10-09" },
      "at": "2026-10-01T09:20:00Z" }
  ],
  "dialogue_history": [
    { "round": 1, "counterpart": "SUPPLIER_INTERFACE",
      "summary": "Supplier offers full quantity but delivery is 2 days after the latest acceptable date.",
      "at": "2026-10-01T09:20:00Z" }
  ],
  "negotiation_rules": { "max_rounds": 3,
                         "policy": { "procurement_strategy": "meet required date first",
                                     "delivery_preferences": { "prefer_earliest": true },
                                     "supplier_evaluation_policy": "lead time, then available quantity, then reliability",
                                     "acceptable_quantity_range": { "min": 50, "max": 60 },
                                     "latest_acceptable_delivery": "2026-10-07" } }
}
```

All numbers and policy strings above are **illustrative**, not fixture values (D1).

## 4. Open items affecting C6

C4 `OfferTerms` field names and message types (Dev 2), P0-09 policy storage, C8 attempt counter,
who sends `AGREEMENT_PROPOSED` / `COMMIT` (D9).
