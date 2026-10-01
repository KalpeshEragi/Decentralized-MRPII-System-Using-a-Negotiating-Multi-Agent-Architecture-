# backend/tests

pytest suite for the backend. Configuration is in `backend/pytest.ini` (test path `tests/`,
`backend/` on the import path, importlib import mode so test files in different folders may share names).

## Layout

Subfolders mirror `backend/app/`. Tests are written in the same phase as the code they test (roadmap Section 2, phase gate).

| Folder | Contents |
| --- | --- |
| `core/` | `test_config.py`: settings defaults and environment overrides. |
| `contracts/` | `test_contract_examples.py`: every JSON example in `docs/contracts/` parses and has no cost/price key (Phase 0 check). |
| `mrpii/`, `negotiation/`, `llm/` | Phase 1: X1 baseline and scenario numbers, finished-goods netting, protocol state machine, structured-output validation. |
| `llm/test_agents_spike.py` | Phase 2: Agents SDK configuration (`reasoning.effort = "none"`, base URL / model), offline. |
| `api/` | Phase 2, no database: C5 error format, A2A agent cards, A2A refusals. |
| `db/` | Phase 2, **needs `TEST_DATABASE_URL`** (skipped without it): migrations, X1 seed / reset, persisted plan, persisted negotiation (agreement, REJECTED, FAILED after 3 rounds, refused messages), HTTP flow with A2A delivery. These reset the test database. |
| `agents/` | Phase 3, no database: Purchasing policy and LLM-proposal validation on the X1 fixture (`test_purchasing_policy.py`), C6 state shapes and offer-history rebuilding (`test_agent_state.py`). |
| `db/test_phase3_workflow.py` | Phase 3, **needs `TEST_DATABASE_URL`**: order → Planning → Inventory → A2A → Purchasing → supplier interface → AGREEMENT_PROPOSED / REJECTED / FAILED → Inventory → Planning, through the API with A2A routed in-process (TestClient) and a fake LLM. |
| `db/test_phase4_approval.py` | Phase 4, **needs `TEST_DATABASE_URL`**: approve → COMMIT and reservation; FAILED shortage not approvable; reject → ABORT + attempt 2; rejecting attempt 2 → human intervention; COMMIT/ABORT refused on message routes. The shared `api` fixture is in `db/conftest.py`. |
| `simulation/` | Empty (C9 Scenario Manager not implemented). |

Tests of deterministic logic assert exact values. LLM behaviour is tested with a fake model, never a live one,
except for one bounded smoke test planned later.

## Run

```bash
cd backend
.venv/Scripts/python -m pytest
```
