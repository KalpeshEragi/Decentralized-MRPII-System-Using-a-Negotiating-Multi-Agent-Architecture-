from app.data.scenarios import get_default_scenario
from app.mrpii.mps import generate_mps
from app.mrpii.mrp import (
    explode_bom,
    calculate_net_requirements,
)


def test_bom_explosion():

    scenario = get_default_scenario()

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    requirements = explode_bom(
        mps=mps,
        boms=scenario["boms"],
    )

    assert len(requirements) > 0


def test_bom_requirements_are_positive():

    scenario = get_default_scenario()

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    requirements = explode_bom(
        mps=mps,
        boms=scenario["boms"],
    )

    for quantity in requirements.values():
        assert quantity > 0


def test_mrp_netting():

    scenario = get_default_scenario()

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    gross_requirements = explode_bom(
        mps=mps,
        boms=scenario["boms"],
    )

    results = calculate_net_requirements(
        gross_requirements=gross_requirements,
        inventory=scenario["inventory"],
    )

    assert len(results) > 0

    for result in results:
        assert result.gross_requirement >= 0
        assert result.available_inventory >= 0
        assert result.net_requirement >= 0


def test_net_requirement_never_exceeds_gross_requirement():

    scenario = get_default_scenario()

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    gross_requirements = explode_bom(
        mps=mps,
        boms=scenario["boms"],
    )

    results = calculate_net_requirements(
        gross_requirements=gross_requirements,
        inventory=scenario["inventory"],
    )

    for result in results:
        assert result.net_requirement <= result.gross_requirement