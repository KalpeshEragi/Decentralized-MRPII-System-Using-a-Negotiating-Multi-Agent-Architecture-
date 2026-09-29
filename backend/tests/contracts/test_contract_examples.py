"""Phase 0 check: every JSON example in docs/contracts/ parses and contains no cost/price field."""

import json
import re
from pathlib import Path

import pytest

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "docs" / "contracts"
JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.S)
FORBIDDEN_KEYS = {"price", "unit_price", "cost", "unit_cost", "supplier_price"}

EXAMPLES = [
    pytest.param(block, id=f"{path.name}#{index}")
    for path in sorted(CONTRACTS_DIR.glob("C*.md"))
    for index, block in enumerate(JSON_BLOCK.findall(path.read_text(encoding="utf-8")))
]


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def test_contract_examples_found():
    assert EXAMPLES, f"no JSON examples found in {CONTRACTS_DIR}"


@pytest.mark.parametrize("block", EXAMPLES)
def test_contract_example_is_valid_json_without_price(block):
    data = json.loads(block)
    assert not FORBIDDEN_KEYS & set(_keys(data))
