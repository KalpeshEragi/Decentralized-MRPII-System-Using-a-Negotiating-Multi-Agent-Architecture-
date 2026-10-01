"""Deterministic X1 seed and reset (fixture: docs/smartphone_x1_fixture.md).

`reset_and_seed(db)` empties every C2 table and loads the X1 baseline: the finished product, single-level BOM, the six
component inventory positions (one aggregated warehouse), the 14 suppliers with their supplier items, the three
25% agents, and the baseline order SO-0001 (1,000 units, status NEW, not yet planned). Ids are deterministic.

Placeholders NOT defined by the fixture (needed only because the schema has NOT NULL columns): SKUs, the warehouse
name/location, the demo customer, agent names. They carry no business meaning.

Run from `backend/`:  python -m app.data.seed_data
"""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.data import x1_fixture as x1
from app.models import Base
from app.models import agent, core, inventory, purchasing, sales
from app.schemas.domain import ItemType
from app.services.audit_service import AGENT_INVENTORY, AGENT_PLANNING, AGENT_PURCHASING

_NS = uuid.UUID("00000000-0000-4000-8000-0000000000e2")

WAREHOUSE_ID = uuid.uuid5(_NS, "warehouse")
CUSTOMER_ID = uuid.UUID(x1.x1_order().customer_id)
BASELINE_ORDER_ID = uuid.UUID(x1.ORDER_ID)

AGENTS = [
    (AGENT_PLANNING, "Production Planning Agent"),
    (AGENT_INVENTORY, "Inventory Agent"),
    (AGENT_PURCHASING, "Purchasing Agent"),
]


def _sku(name: str) -> str:
    return name.upper().replace(" ", "-")


def reset(db: Session) -> None:
    """Delete all rows of every C2 table."""
    tables = ", ".join(f'"{t.schema}"."{t.name}"' for t in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def seed(db: Session) -> None:
    db.add(
        core.Item(
            id=uuid.UUID(x1.PRODUCT_ID), sku=_sku(x1.PRODUCT), name=x1.PRODUCT,
            item_type=ItemType.FINISHED_PRODUCT, unit="pcs",
        )
    )
    for name, item_id in x1.COMPONENT_IDS.items():
        db.add(core.Item(id=uuid.UUID(item_id), sku=_sku(name), name=name, item_type=ItemType.COMPONENT, unit="pcs"))
    db.flush()

    bom_id = uuid.uuid5(_NS, "bom-x1-v1")
    db.add(core.Bom(id=bom_id, parent_item_id=uuid.UUID(x1.PRODUCT_ID), version=1, is_active=True))
    db.flush()
    for line in x1.x1_bom():
        db.add(
            core.BomItem(
                id=uuid.uuid5(bom_id, line.component_item_id),
                bom_id=bom_id,
                component_item_id=uuid.UUID(line.component_item_id),
                quantity_required=line.quantity_per,
            )
        )

    db.add(inventory.Warehouse(id=WAREHOUSE_ID, name="Main Warehouse", location="Main Plant"))
    db.flush()
    for position in x1.x1_inventory().values():  # finished-goods stock: none in the baseline
        db.add(
            inventory.InventoryBalance(
                id=uuid.uuid5(WAREHOUSE_ID, position.item_id),
                item_id=uuid.UUID(position.item_id),
                warehouse_id=WAREHOUSE_ID,
                on_hand=position.on_hand,
                reserved=position.reserved,
                safety_stock=position.safety_stock,
            )
        )

    for option in x1.x1_suppliers():
        supplier_id = uuid.uuid5(_NS, f"supplier-{option.supplier}")
        db.add(purchasing.Supplier(id=supplier_id, name=option.supplier, is_active=True))
        db.flush()
        db.add(
            purchasing.SupplierItem(
                id=uuid.uuid5(supplier_id, option.item_id),
                supplier_id=supplier_id,
                item_id=uuid.UUID(option.item_id),
                lead_time_days=option.lead_time_days,
                min_order_qty=option.min_order_qty,
                available_qty=option.available_qty,
            )
        )

    for code, name in AGENTS:
        db.add(agent.Agent(id=uuid.uuid5(_NS, code), agent_code=code, agent_type=code, name=name, status="ACTIVE"))

    db.add(sales.Customer(id=CUSTOMER_ID, name="Demo Customer", location="Demo City", contact_info={}))
    db.flush()
    order = x1.x1_order()
    db.add(
        sales.CustomerOrder(
            id=BASELINE_ORDER_ID, customer_id=CUSTOMER_ID, order_number=order.order_number,
            order_date=order.order_date, due_date=order.due_date, priority=order.priority, status=order.status.value,
        )
    )
    db.flush()
    for line in order.lines:
        db.add(
            sales.CustomerOrderItem(
                id=uuid.uuid5(BASELINE_ORDER_ID, line.item_id),
                order_id=BASELINE_ORDER_ID, item_id=uuid.UUID(line.item_id), quantity=line.quantity,
            )
        )


def reset_and_seed(db: Session) -> None:
    """Return the database to the deterministic X1 baseline (one transaction)."""
    reset(db)
    seed(db)
    db.commit()


if __name__ == "__main__":
    from app.core.database import new_session

    with new_session() as session:
        reset_and_seed(session)
    print("X1 baseline loaded")
