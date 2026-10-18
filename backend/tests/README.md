# backend/tests

pytest suite for the backend. Configuration is in `backend/pytest.ini` (test path `tests/`,
`backend/` on the import path, importlib import mode so test files in different folders may share names).

## Layout

Subfolders mirror `backend/app/`. Tests are written in the same phase as the code they test (roadmap Section 2, phase gate).

| Folder | Contents |
| --- | --- |
| `core/` | `test_config.py`: settings defaults and environment overrides. |
| `llm/` | `test_structured_output.py`: structured-output parsing and retry with a fake model. |
| `api/` | No database: RFC 9457 error format and correlation id, A2A agent cards, A2A refusals. |
| `mrpii/test_planning_calculations.py` | Step 2, no database: research phone example (multi-level MRP + capacity) exact, ATP with a supplier delay, PL-6 ranking. |
| `platform/` | **Needs `TEST_DATABASE_URL`**; each test empties the infrastructure, agent and reference tables. Step 1: work runner, event channel. Step 3: negotiation v2 over A2A. Step 4: Inventory (the 5000 → 3000 example with an exact ledger; no double booking) and HR (absence cover: move, overtime, AT_RISK). Step 5: S1 end to end (`test_s1_order_flow.py`, about 10 minutes on the remote test database). `conftest.py` has `pump` (runs queued work like the background workers: one query per round finds the queues with work, only those are drained, and any item left unfinished fails the test; `PUMP_TRACE=1` prints each round) and a FAKE Planning starter. |
| `purchasing_agent/` | The Purchasing Agent's own tests (another contributor). No database: selection, validation, LLM guardrails, settings. `db/` needs `TEST_DATABASE_URL` and resets only the `supplier_service`, `purchasing_agent` and `negotiation_engine` schemas. |
| `sales_agent/` | The Sales Agent's own tests (its `db/` folder needs `TEST_DATABASE_URL`). |

The old 25% tests (`db/`, `agents/`, `negotiation/`, X1 fixture tests) were retired with the old code in step 4.

`conftest.py` (top level) switches the background work runner off for all tests (`BACKGROUND_WORKERS=false`).

Tests of deterministic logic assert exact values. LLM behaviour is tested with a fake model, never a live one,
except for one bounded smoke test planned later.

## Run

```bash
cd backend
.venv/Scripts/python -m pytest
```

Removed 2026-10-18: `contracts/test_contract_examples.py` (read the deleted `docs/contracts/`), the legacy supplier-route tests `db/test_phase3_workflow.py` and `db/test_phase4_approval.py`, and the supplier-response cases in `db/test_api_flow.py` and `db/test_negotiation_persistence.py`.
