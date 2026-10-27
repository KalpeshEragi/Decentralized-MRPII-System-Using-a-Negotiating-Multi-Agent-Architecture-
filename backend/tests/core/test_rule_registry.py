"""The rule registry (RE-1), no database: every business rule is a real setting with a default inside its bounds, every
rule marked in use is read by some code, bounds and cross-checks refuse what would break the system."""

from decimal import Decimal
from pathlib import Path

from app.rules import registry
from app.simulation.settings import DEFAULTS

APP = Path(__file__).resolve().parents[2] / "app"


def test_every_rule_is_a_setting_with_its_default_inside_its_bounds():
    for rule in registry.RULES:
        assert rule.key in DEFAULTS, rule.key
        value, problem = registry.check_value(rule, DEFAULTS[rule.key])
        assert problem is None, (rule.key, problem)
        assert rule.owner in registry.OWNERS and rule.label and rule.description
    assert len({r.key for r in registry.RULES}) == len(registry.RULES)


def test_a_rule_marked_in_use_is_read_by_the_code_and_one_not_in_use_is_not():
    sources = "\n".join(p.read_text(encoding="utf-8") for p in APP.rglob("*.py")
                        if p.parts[-2:] not in (("simulation", "settings.py"), ("rules", "registry.py")))
    for rule in registry.RULES:
        read = f'"{rule.key}"' in sources or f"'{rule.key}'" in sources
        assert read == rule.in_use, f"{rule.key}: in_use={rule.in_use} but read by code={read}"


def test_values_are_checked_against_bounds_whole_numbers_and_percent():
    overtime = registry.BY_KEY["overtime_max_hours_per_day"]
    assert registry.check_value(overtime, "4") == (Decimal("4"), None)
    assert "between 0 h and 6 h" in registry.check_value(overtime, 9)[1]
    assert "number" in registry.check_value(overtime, "lots")[1]
    reasks = registry.BY_KEY["planning_reask_limit"]
    assert "whole number" in registry.check_value(reasks, "1.5")[1]
    share = registry.BY_KEY["safety_stock_release_share"]
    assert registry.check_value(share, "0.3")[1] is None
    assert "between 0 % and 100 %" in registry.check_value(share, "1.5")[1]


def test_rules_that_must_fit_together_are_cross_checked():
    values = {"overtime_max_hours_per_day": 4, "overtime_max_hours_per_week": 3}
    assert registry.cross_checks(values) == ["Overtime per week cannot be less than overtime per day"]
    assert registry.cross_checks({**values, "overtime_max_hours_per_week": 8}) == []
