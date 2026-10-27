# backend/app/rules

The rule editor's backend (`dev_docs/architecture/rules_events_replenishment.md` §2; RE-1, RE-5, RE-6). Business rules
are factory settings with an owner, plain words, a unit and safe bounds; agents read them live with `setting(db, key)`.

| File | What it does |
| --- | --- |
| `registry.py` | `RULES`: every business rule once — key (a setting in `simulation/settings.py`), owner (`GENERAL` or an agent), label, description, kind and unit, bounds, whole numbers or not, `in_use` (False = in the design, no code reads it yet: shown, not editable), the decision behind it. `check_value` (bounds), `cross_checks` (rules that must fit together, e.g. overtime per week ≥ per day). Settings not listed are system settings and never shown. |
| `service.py` | `list_rules` (grouped by owner, with value, default, changed, last change), `change_rule` / `reset_rule` (validate, write the setting, keep the user's value in the rule profile `simulation.rule_values`, record `simulation.rule_changes`), `history`, `reapply_profile` (called by `simulation/states.restore`: the profile survives scenario starts, RE-6). |
| `api.py` | Doors: `GET /rules`, `GET /rules/history?key=`, `PUT /rules/{key}` (`{value, note}`; header `X-Changed-By` optional), `DELETE /rules/{key}` (reset). Writes need the simulator door key. Frontend page `/rules`. |

The simulator's generic `POST /simulation/settings` also enforces the registry's bounds for business keys, but only the
rule doors keep a change in the profile and the history.

**Adding a rule:** add the setting with its default to `simulation/settings.py`, a `Rule` to `registry.py`, and read it
in the agent with `setting(db, key)`. The registry test fails if a rule marked in use is not read by any code.

**Tests:** `tests/core/test_rule_registry.py`, `tests/platform/test_rule_editor.py`.
