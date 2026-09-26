from app.data.scenarios import get_default_scenario
from app.mrpii.mps import generate_mps


def test_mps_generation():

    scenario = get_default_scenario()

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    assert len(mps) > 0


def test_mps_contains_valid_products():

    scenario = get_default_scenario()

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    valid_products = {
        product.id
        for product in scenario["products"]
    }

    for entry in mps:
        assert entry.product_id in valid_products


def test_mps_quantities_are_positive():

    scenario = get_default_scenario()

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    for entry in mps:
        assert entry.quantity > 0