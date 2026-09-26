from app.data.seed_data import (
    PRODUCTS,
    MATERIALS,
    BOMS,
    INVENTORY,
    MACHINES,
    ORDERS,
)


def get_default_scenario():
    return {
        "products": PRODUCTS,
        "materials": MATERIALS,
        "boms": BOMS,
        "inventory": INVENTORY,
        "machines": MACHINES,
        "orders": ORDERS,
    }