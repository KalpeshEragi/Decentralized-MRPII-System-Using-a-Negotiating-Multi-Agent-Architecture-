# backend/tests

pytest suite for the backend. Configuration is in `backend/pytest.ini` (test path `tests/`,
`backend/` on the import path, importlib import mode so test files in different folders may share names).

## Layout

Subfolders mirror `backend/app/`. Tests are written in the same phase as the code they test (roadmap Section 2, phase gate).

| Folder | Contents |
| --- | --- |
| `core/` | `test_config.py`: settings defaults and environment overrides. |
| `mrpii/`, `negotiation/`, `llm/` | Phase 1: X1 baseline and scenario numbers, finished-goods netting, protocol state machine, structured-output validation. |
| `llm/test_agents_spike.py` | Phase 2: Agents SDK configuration (`reasoning.effort = "none"`, base URL / model), offline. |
| `api/` | Phase 2, no database: C5 error format, A2A agent cards, A2A refusals. |
| `db/` | Phase 2, **needs `TEST_DATABASE_URL`** (skipped without it): migrations, X1 seed / reset, persisted plan, persisted negotiation (opening, early REJECT, refused messages), HTTP flow. These reset the test database. |
| `agents/` | Phase 3, no database: Purchasing policy and LLM-proposal validation on the X1 fixture (`test_purchasing_policy.py`), C6 state shapes and offer-history rebuilding (`test_agent_state.py`). |
| `purchasing_agent/` | New Purchasing Agent (174 passed, 2026-10-18). No database: `test_selection.py`, `test_validation.py`, `test_llm_guardrails.py`, `test_settings_and_dates.py`, `test_llm_no_thinking.py`. `db/`, **needs `TEST_DATABASE_URL`**: the Purchasing API (requests, contracts, supplier chat, splits, reallocation, availability, deadlines/abort, approval, LLM); each test resets only the `supplier_service`, `purchasing_agent` and `negotiation_engine` schemas to the PA-v1 fixture (`dev_docs/purchasing_agent/seed_data.md`). Scenario map: `dev_docs/purchasing_agent/3_purchasing_agent_backend.md` §E. |
| `sales_agent/` | Sales Agent tests. |
| `simulation/` | Empty (C9 Scenario Manager not implemented). |

Tests of deterministic logic assert exact values. LLM behaviour is tested with a fake model, never a live one,
except for one bounded smoke test planned later.

## Run

```bash
cd backend
.venv/Scripts/python -m pytest
```

Removed 2026-10-18: `contracts/test_contract_examples.py` (read the deleted `docs/contracts/`), the legacy supplier-route tests `db/test_phase3_workflow.py` and `db/test_phase4_approval.py`, and the supplier-response cases in `db/test_api_flow.py` and `db/test_negotiation_persistence.py`.
