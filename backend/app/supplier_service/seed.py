"""Supplier Service fixture data: docs/purchasing_agent_fixture.md §2–§3.

IDs are fixed (derived from the SKU or name), so tests and the Purchasing seed can refer to them. `reset` empties only
the `supplier_service` tables. The whole fixture (all three new schemas) is loaded by `app.purchasing_agent.seed`.
"""

import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.supplier_service.models import Item, Supplier, SupplierItem, SupplierServiceBase

_NAMESPACE = uuid.UUID("6f1d3c2e-5a0b-4b8e-9c71-2d4f8a6e1b30")

ITEMS = [  # sku, name
    ("DSP-100", "Display Panel"),
    ("BAT-200", "Battery Pack"),
    ("MBD-300", "Main Board"),
    ("CAM-400", "Camera Module"),
    ("SPK-500", "Speaker"),
    ("CHP-600", "Charging Port"),
]

SUPPLIER_ITEMS = [  # sku, supplier, lead time days, MOQ, available, active
    ("DSP-100", "Alpha Displays", 10, 200, 1000, True),
    ("DSP-100", "Beta Optics", 6, 100, 800, True),
    ("DSP-100", "Gamma Screens", 4, 50, 2000, True),
    ("BAT-200", "Volt Power", 7, 100, 400, True),
    ("BAT-200", "Cell Works", 9, 200, 500, True),
    ("BAT-200", "Ion Supply", 12, 300, 1500, True),
    ("MBD-300", "Nova Silicon", 5, 50, 600, True),
    ("MBD-300", "Orbit Circuits", 6, 50, 600, True),
    ("MBD-300", "Pixel Boards", 8, 100, 600, True),
    ("MBD-300", "Quartz Electronics", 15, 100, 1000, True),
    ("CAM-400", "Lumen Optics", 6, 100, 300, True),
    ("CAM-400", "Focal Point", 5, 100, 300, True),
    ("CAM-400", "Prism Labs", 20, 100, 2000, True),
    ("SPK-500", "Sonic Audio", 4, 100, 500, True),
    ("SPK-500", "EchoTech", 5, 100, 300, True),
    ("SPK-500", "Wave Acoustics", 6, 100, 300, True),
    ("CHP-600", "PlugCo", 5, 100, 1000, True),
    ("CHP-600", "ConnectRite", 5, 100, 400, True),
    ("DSP-100", "Dormant Displays", 1, 10, 5000, False),
]

ITEM_IDS = {sku: uuid.uuid5(_NAMESPACE, f"item:{sku}") for sku, _ in ITEMS}
SUPPLIER_IDS = {name: uuid.uuid5(_NAMESPACE, f"supplier:{name}") for _, name, *_ in SUPPLIER_ITEMS}


def reset(db: Session) -> None:
    """Empty the Supplier Service tables. The caller commits."""
    tables = ", ".join(f'"{t.schema}"."{t.name}"' for t in SupplierServiceBase.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE {tables} CASCADE"))


def seed(db: Session) -> None:
    """Load the fixture into empty tables. The caller commits."""
    db.add_all(Item(id=ITEM_IDS[sku], sku=sku, name=name, unit="pcs") for sku, name in ITEMS)
    active = {name: is_active for _, name, *_, is_active in SUPPLIER_ITEMS}
    db.add_all(Supplier(id=SUPPLIER_IDS[name], name=name, is_active=is_active) for name, is_active in active.items())
    db.flush()  # suppliers and items first: supplier items point at them
    db.add_all(
        SupplierItem(supplier_id=SUPPLIER_IDS[name], item_id=ITEM_IDS[sku], lead_time_days=lead,
                     min_order_qty=Decimal(moq), available_qty=Decimal(available))
        for sku, name, lead, moq, available, _ in SUPPLIER_ITEMS
    )
