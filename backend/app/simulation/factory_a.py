"""The default demo factory "Factory A" (demo.md §4.1, starting values to tune after the first runs).

A phone and a tablet share the main board, so orders compete. Configuring is separate from triggering: this builds the
starting state through each owner's own setup (and the shared `core` reference data), never through a trigger.

| Item     | Make/buy | BOM                    | Stock / safety | Routing / supply                        |
| PHONE-P  | Make     | 1 MB, 1 BAT, 1 CASE    | 50 / 0         | ASM: setup 1 h, 0.05 h/pc, ASSEMBLY      |
| TABLET-T | Make     | 1 MB, 2 BAT, 1 CASE-T  | 20 / 0         | ASM: setup 1 h, 0.08 h/pc, ASSEMBLY      |
| MB       | Make     | 1 PCB, 2 CHIP          | 20 / 0         | SMT: setup 0.5 h, 0.02 h/pc, SMT         |
| BAT      | Buy      | -                      | 300 / 50       | lead time 5 days, multiple 100           |
| CASE     | Buy      | -                      | 1000 / 100     | lead time 3 days                         |
| CASE-T   | Buy      | -                      | 300 / 50       | lead time 3 days                         |
| PCB      | Buy      | -                      | 100 / 0        | lead time 4 days                         |
| CHIP     | Buy      | -                      | 300 / 100      | lead time 7 days, multiple 250           |

Work centers SMT 8 h/day, ASM 16 h/day. Workers: 2 SMT, 3 ASSEMBLY (one also SMT), 8 h shifts. Warehouse: MATERIALS
2000 space units, FINISHED_GOODS 1000, receiving 1500 units/day, shipping 1000 units/day. One simulated supplier per
bought item (the multiple is its minimum order quantity). Sales sells the phone and the tablet.
"""

import uuid
from decimal import Decimal as D

from sqlalchemy.orm import Session

from app.hr_agent import manager as hr
from app.inventory_agent import manager as inventory
from app.models.core import Bom, BomItem, Item, ItemType, Routing
from app.planning_agent import manager as planning
from app.sales_agent.models import Product
from app.supplier_service.models import Item as SupplierItem, Supplier, SupplierItem as SupplierTerms
from app.warehouse_agent import manager as warehouse

FINISHED, COMPONENT, RAW = ItemType.FINISHED_PRODUCT, ItemType.COMPONENT, ItemType.RAW_MATERIAL
# sku: (name, type, make/buy, space per unit, on hand, safety stock)
ITEMS = {
    "PHONE-P": ("Phone P", FINISHED, "MAKE", "1", 50, 0),
    "TABLET-T": ("Tablet T", FINISHED, "MAKE", "2", 20, 0),
    "MB": ("Main board", COMPONENT, "MAKE", "0.5", 20, 0),
    "BAT": ("Battery", RAW, "BUY", "0.2", 300, 50),
    "CASE": ("Phone case", RAW, "BUY", "0.5", 1000, 100),
    "CASE-T": ("Tablet case", RAW, "BUY", "0.5", 300, 50),
    "PCB": ("Printed circuit board", RAW, "BUY", "0.1", 100, 0),
    "CHIP": ("Chip", RAW, "BUY", "0.01", 300, 100),
}
BOMS = {"PHONE-P": [("MB", 1), ("BAT", 1), ("CASE", 1)], "TABLET-T": [("MB", 1), ("BAT", 2), ("CASE-T", 1)],
        "MB": [("PCB", 1), ("CHIP", 2)]}
# sku: (work center, skill, setup hours, run hours per unit)
ROUTINGS = {"PHONE-P": ("ASM", "ASSEMBLY", "1", "0.05"), "TABLET-T": ("ASM", "ASSEMBLY", "1", "0.08"),
            "MB": ("SMT", "SMT", "0.5", "0.02")}
# sku: (supplier, lead time days, minimum order quantity)
SUPPLY = {"BAT": ("Volt Batteries", 5, 100), "CASE": ("Shell Cases", 3, 1), "CASE-T": ("Shell Cases", 3, 1),
          "PCB": ("Board Works", 4, 1), "CHIP": ("Silicon Parts", 7, 250)}
WORKERS = [{"code": "S1", "name": "Sana", "primary_skill": "SMT"}, {"code": "S2", "name": "Ravi", "primary_skill": "SMT"},
           {"code": "A1", "name": "Asha", "primary_skill": "ASSEMBLY"},
           {"code": "A2", "name": "Ben", "primary_skill": "ASSEMBLY"},
           {"code": "A3", "name": "Mira", "primary_skill": "ASSEMBLY", "secondary_skills": ["SMT"]}]


def build(db: Session, finished_stock: dict[str, int] | None = None, finished_space: int = 1000) -> dict[str, str]:
    """Create Factory A in an empty run (caller commits). Returns {sku: item id}.

    `finished_stock` replaces the starting stock of finished products (load scenarios start with more, see
    scenarios.LOAD_COVER); `finished_space` is then the FINISHED_GOODS zone capacity in space units."""
    on_hand = {sku: (finished_stock or {}).get(sku, row[4]) for sku, row in ITEMS.items()}
    ids = {}
    for sku, (name, kind, sourcing, space, _, _) in ITEMS.items():
        item = Item(sku=sku, name=name, item_type=kind, unit="pcs", sourcing=sourcing, space_per_unit=D(space))
        db.add(item)
        db.flush()
        ids[sku] = str(item.id)
    for parent, lines in BOMS.items():
        bom = Bom(parent_item_id=uuid.UUID(ids[parent]), version=1)
        db.add(bom)
        db.flush()
        db.add_all([BomItem(bom_id=bom.id, component_item_id=uuid.UUID(ids[child]), quantity_required=D(per))
                    for child, per in lines])
    db.add_all([Routing(item_id=uuid.UUID(ids[sku]), step_no=1, work_center_code=wc, skill=skill, crew_size=1,
                        setup_hours=D(setup), run_hours_per_unit=D(run))
                for sku, (wc, skill, setup, run) in ROUTINGS.items()])
    db.add_all([Product(sku=sku, name=ITEMS[sku][0], active=True) for sku in ("PHONE-P", "TABLET-T")])
    suppliers = {}
    for sku, (supplier_name, lead, minimum) in SUPPLY.items():
        if supplier_name not in suppliers:
            suppliers[supplier_name] = Supplier(name=supplier_name, is_active=True)
            db.add(suppliers[supplier_name])
        supplier_item = SupplierItem(sku=sku, name=ITEMS[sku][0], unit="pcs")
        db.add(supplier_item)
        db.flush()
        db.add(SupplierTerms(supplier_id=suppliers[supplier_name].id, item_id=supplier_item.id, lead_time_days=lead,
                             min_order_qty=D(minimum), available_qty=D(10000)))
    db.flush()
    inventory.setup(db, [{"item_id": ids[sku], "on_hand": on_hand[sku], "safety_stock": safety}
                         for sku, (_, _, _, _, _, safety) in ITEMS.items()])
    planning.setup(db, {"SMT": 8, "ASM": 16})
    hr.setup(db, WORKERS)
    occupied = {"MATERIALS": D(0), "FINISHED_GOODS": D(0)}
    for sku, (_, kind, _, space, _, _) in ITEMS.items():
        occupied["FINISHED_GOODS" if kind == FINISHED else "MATERIALS"] += D(space) * on_hand[sku]
    warehouse.setup(db, {"zones": {"MATERIALS": {"capacity_units": 2000, "occupied_now": occupied["MATERIALS"]},
                                   "FINISHED_GOODS": {"capacity_units": finished_space,
                                                      "occupied_now": occupied["FINISHED_GOODS"]}},
                         "receiving_units_per_day": 1500, "shipping_units_per_day": 1000})
    return ids
