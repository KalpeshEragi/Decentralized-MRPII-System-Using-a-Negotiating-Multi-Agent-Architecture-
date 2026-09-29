# backend/tests

pytest suite for the backend. Configuration is in `backend/pytest.ini` (test path `tests/`,
`backend/` on the import path, importlib import mode so test files in different folders may share names).

## Layout

Subfolders mirror `backend/app/`. Each developer writes tests for what they implement (roadmap Section 7).

| Folder | Contents |
| --- | --- |
| `core/` | `test_config.py`: settings defaults and environment overrides. |
| `mrpii/`, `agents/`, `negotiation/`, `simulation/` | Empty; filled in their phases. |

Tests of deterministic logic assert exact values. LLM behaviour is tested with a fake model, never a live one,
except for one bounded smoke test planned later.

## Run

```bash
cd backend
.venv/Scripts/python -m pytest
```
