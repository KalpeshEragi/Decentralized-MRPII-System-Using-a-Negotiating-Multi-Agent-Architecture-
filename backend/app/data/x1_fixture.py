"""SmartPhone X1 fixture (X1-v2), transcribed from the former docs/smartphone_x1_fixture.md (removed 2026-10-16; still in git history). Do not change these numbers.

Scenario variants (fixture section 7) are built with the keyword overrides below, each from the untouched baseline.
"""

import uuid
from datetime import date
from decimal import Decimal

from app.schemas.domain import (
    BOMLine,
    CustomerOrder,
    InventoryPosition,
    OrderLine,
    ProductionParameters,
    SupplierOption,
)

_NS = uuid.UUID("00000000-0000-4000-8000-0000000000e1")


def _id(name: str) -> str:
    return str(uuid.uuid5(_NS, name))


PLANNING_DATE = date(2026, 10, 1)
DUE_DATE = date(2026, 10, 31)
PRODUCT = "SmartPhone X1"
PRODUCT_ID = _id(PRODUCT)
ORDER_ID = _id("SO-0001")
PRODUCTION = {PRODUCT_ID: ProductionParameters(item_id=PRODUCT_ID, production_lead_time_days=5, capacity_per_day=300)}

# component: (quantity_per, on_hand, reserved, safety_stock)
_COMPONENTS = {
    "Display": (1, 650, 50, 100),
    "Main Board": (1, 1200, 100, 100),
    "Battery": (1, 500, 50, 50),
    "Camera Module": (2, 2800, 200, 100),
    "Speaker": (1, 1500, 100, 100),
    "Charging Port": (1, 1500, 100, 50),
}

# (component, supplier, lead_time_days, min_order_qty, available_qty)
_SUPPLIERS = [
    ("Display", "Alpha Displays", 14, 200, 600),
    ("Display", "Beta Optics", 20, 300, 500),
    ("Display", "Gamma Screens", 28, 100, 1000),
    ("Main Board", "Nova Silicon", 18, 100, 400),
    ("Main Board", "Orbit Circuits", 10, 200, 300),
    ("Main Board", "Pixel Boards", 24, 50, 150),
    ("Battery", "Volt Power", 12, 250, 700),
    ("Battery", "Cell Works", 22, 500, 1000),
    ("Camera Module", "Lumen Optics", 15, 200, 500),
    ("Camera Module", "Focal Point", 8, 100, 150),
    ("Speaker", "Sonic Audio", 9, 200, 500),
    ("Speaker", "EchoTech", 16, 50, 150),
    ("Charging Port", "PlugCo", 7, 100, 1000),
    ("Charging Port", "ConnectRite", 21, 300, 500),
]

COMPONENT_IDS = {name: _id(name) for name in _COMPONENTS}


def x1_order(quantity: int = 1000, due_date: date = DUE_DATE) -> CustomerOrder:
    """Baseline: 1,000 units due 2026-10-31. S3: quantity=1300. S7: due_date=date(2026, 10, 21)."""
    return CustomerOrder(
        id=ORDER_ID,
        order_number="SO-0001",
        customer_id=_id("customer"),
        order_date=PLANNING_DATE,
        due_date=due_date,
        priority=1,
        lines=[OrderLine(item_id=PRODUCT_ID, quantity=quantity)],
    )


def x1_bom() -> list[BOMLine]:
    return [
        BOMLine(parent_item_id=PRODUCT_ID, component_item_id=COMPONENT_IDS[name], quantity_per=per)
        for name, (per, *_) in _COMPONENTS.items()
    ]


def x1_inventory(reserved: dict[str, int] | None = None) -> dict[str, InventoryPosition]:
    """Positions keyed by item id. S6: reserved={"Speaker": 500}."""
    reserved = reserved or {}
    return {
        COMPONENT_IDS[name]: InventoryPosition(
            item_id=COMPONENT_IDS[name],
            on_hand=on_hand,
            reserved=reserved.get(name, res),
            safety_stock=safety,
        )
        for name, (_, on_hand, res, safety) in _COMPONENTS.items()
    }


def x1_suppliers(overrides: dict[str, dict[str, int]] | None = None) -> list[SupplierOption]:
    """Supplier options. S2: {"Volt Power": {"lead_time_days": 27}}. S4: {"Alpha Displays": {"available_qty": 300}}."""
    overrides = overrides or {}
    return [
        SupplierOption(
            item_id=COMPONENT_IDS[component],
            supplier=supplier,
            **{"lead_time_days": lead, "min_order_qty": moq, "available_qty": available, **overrides.get(supplier, {})},
        )
        for component, supplier, lead, moq, available in _SUPPLIERS
    ]


def component_name(item_id: str) -> str:
    return next(name for name, cid in COMPONENT_IDS.items() if cid == item_id)


BASELINE_EXPECTED_NET = {  # fixture section 6.2, for quick manual comparison
    "Display": Decimal(500),
    "Main Board": Decimal(0),
    "Battery": Decimal(600),
    "Camera Module": Decimal(0),
    "Speaker": Decimal(0),
    "Charging Port": Decimal(0),
}
