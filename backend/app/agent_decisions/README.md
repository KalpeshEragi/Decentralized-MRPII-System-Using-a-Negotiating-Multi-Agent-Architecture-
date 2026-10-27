# agent_decisions

The shared think loop for agents that decide (`dev_docs/architecture/quotes_and_agent_decisions.md`, QD-1 to QD-11).
Built: the loop, the record and the timeline rows (step 1); used by Planning's decision point D7
(`planning_agent/decisions.py`, step 2). The other decision points follow in steps 3–6.

| File | What it does |
| --- | --- |
| `think.py` | `think(situation, validate, fallback, client)`: one prompt with the agent's goal, facts, actions and hints; the model answers JSON (`thinking`, `need_facts`, `action`, `params`, `reason`); at most one lookup round (`Situation.lookups`) and one revision after the agent's own `validate` refuses; otherwise the deterministic fallback, with the reason (`AI_OFF`, `TIMEOUT`, `ERROR`, `INVALID`, `NOT_VALID`). At most 3 model calls. No database, no lock. |
| `record.py` | `decision_client(db)`: the shared Ollama model (hidden thinking mode off, the agent's reasoning is in its answer; timeout 90 s), or `None` when `ai_enabled` is 0 or more than `ai_decision_max_orders` orders are open (QD-5). `record(db, audit_model, situation, decision)`: one `DECISION` row in the deciding agent's own `audit_log` plus one `observability.llm_calls` row per call. `rows(...)`: decisions as timeline rows (`source = "decision"`), used by each agent's `reads.decisions`. |

How an agent will use it (step 2 on): reach a decision point → build the `Situation` from its own trusted reads →
run `think` outside any transaction (a long-mode work item) → in a new transaction re-check, apply and `record`.

Tests: `tests/llm/test_think_loop.py` (fake model, no database).
