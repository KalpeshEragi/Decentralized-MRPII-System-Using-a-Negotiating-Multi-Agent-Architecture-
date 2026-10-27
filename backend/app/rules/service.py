"""Reading and changing business rules (RE-1, RE-6). The value lives in `simulation.settings` (what the agents read);
the user's choice is also kept in the rule profile (`rule_values`, survives restores) and every change in the history
(`rule_changes`). Agents read rules live, so a change applies from the next decision.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.rules import registry
from app.simulation.models import RuleChange, RuleValue
from app.simulation.settings import DEFAULTS, read_settings, update_settings


def _stored(key: str, number: Decimal) -> object:
    return str(number.normalize()) if isinstance(DEFAULTS[key], str) else (
        int(number) if number == number.to_integral_value() else str(number.normalize()))


def rule_view(rule: registry.Rule, value: object, profile: RuleValue | None, last: RuleChange | None) -> dict[str, Any]:
    default = DEFAULTS[rule.key]
    return {
        "key": rule.key, "owner": rule.owner, "label": rule.label, "description": rule.description,
        "kind": rule.kind, "unit": rule.unit, "min": str(rule.min), "max": str(rule.max), "whole": rule.whole,
        "in_use": rule.in_use, "decided_in": rule.decided_in, "value": value, "default": default,
        "changed": Decimal(str(value)) != Decimal(str(default)),
        "last_change": {"by": last.changed_by, "at": last.changed_at.isoformat(), "from": last.old_value["value"],
                        "to": last.new_value["value"], "note": last.note} if last else None,
        "personalised": profile is not None,
    }


def list_rules(db: Session) -> dict[str, Any]:
    values = read_settings(db)["values"]
    profile = {r.key: r for r in db.scalars(select(RuleValue))}
    last: dict[str, RuleChange] = {}
    for change in db.scalars(select(RuleChange).order_by(RuleChange.id)):
        last[change.key] = change
    groups = [{"owner": owner, "label": registry.OWNER_LABELS[owner],
               "rules": [rule_view(r, values[r.key], profile.get(r.key), last.get(r.key))
                         for r in registry.RULES if r.owner == owner]} for owner in registry.OWNERS]
    hidden = [k for k in DEFAULTS if k not in registry.BY_KEY]
    return {"groups": groups, "hidden_system_settings": len(hidden)}


def change_rule(db: Session, key: str, value: object, changed_by: str = "developer", note: str | None = None) -> dict:
    """Validate and apply one business rule change (caller commits)."""
    rule = _rule(key)
    if not rule.in_use:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{rule.label} is not used by any agent yet",
                       [{"field": key, "issue": "not in use"}])
    number, problem = registry.check_value(rule, value)
    if problem:
        raise AppError(ErrorCode.VALIDATION_ERROR, problem, [{"field": key, "issue": "out of bounds"}])
    return _apply(db, rule, _stored(key, number), "CHANGED", changed_by, note)


def reset_rule(db: Session, key: str, changed_by: str = "developer", note: str | None = None) -> dict:
    """Back to the documented default; the rule leaves the profile (caller commits)."""
    rule = _rule(key)
    return _apply(db, rule, DEFAULTS[key], "RESET", changed_by, note)


def history(db: Session, key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    query = select(RuleChange).order_by(RuleChange.id.desc()).limit(limit)
    if key:
        query = query.where(RuleChange.key == key)
    return [{"key": c.key, "label": registry.BY_KEY[c.key].label if c.key in registry.BY_KEY else c.key,
             "from": c.old_value["value"], "to": c.new_value["value"], "action": c.action, "by": c.changed_by,
             "note": c.note, "at": c.changed_at.isoformat()} for c in db.scalars(query)]


def reapply_profile(db: Session) -> int:
    """After a restore: put the user's rule values back into the settings (no history entry). Returns how many."""
    profile = {r.key: r.value["value"] for r in db.scalars(select(RuleValue)) if r.key in registry.BY_KEY}
    if profile:
        update_settings(db, profile)
    return len(profile)


def _apply(db: Session, rule: registry.Rule, new: object, action: str, changed_by: str, note: str | None) -> dict:
    current = read_settings(db)["values"]
    old = current[rule.key]
    problems = registry.cross_checks({**current, rule.key: new})
    if problems:
        raise AppError(ErrorCode.VALIDATION_ERROR, "; ".join(problems), [{"field": rule.key, "issue": "conflict"}])
    update_settings(db, {rule.key: new})
    entry = db.get(RuleValue, rule.key)
    if action == "RESET":
        if entry is not None:
            db.delete(entry)
    elif entry is None:
        db.add(RuleValue(key=rule.key, value={"value": new}, changed_by=changed_by))
    else:
        entry.value, entry.changed_by = {"value": new}, changed_by
    db.add(RuleChange(key=rule.key, old_value={"value": old}, new_value={"value": new}, action=action,
                      changed_by=changed_by, note=note))
    db.flush()
    return {"key": rule.key, "from": old, "to": new, "action": action}


def _rule(key: str) -> registry.Rule:
    rule = registry.BY_KEY.get(key)
    if rule is None:
        raise AppError(ErrorCode.NOT_FOUND, f"no business rule {key}")
    return rule
