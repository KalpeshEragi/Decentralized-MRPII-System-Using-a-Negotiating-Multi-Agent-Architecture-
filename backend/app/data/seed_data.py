from app.models.product import Product
from app.models.material import Material
from app.models.bom import BOM, BOMLine
from app.models.inventory import InventoryItem
from app.models.machine import Machine
from app.models.demand import CustomerOrder


PRODUCTS = [
    Product(
        id="P001",
        name="Smart Espresso Machine",
        description="Standard intelligent espresso machine",
        production_time_hours=4,
    ),
    Product(
        id="P002",
        name="Pro Espresso Machine",
        description="Professional espresso machine",
        production_time_hours=6,
    ),
    Product(
        id="P003",
        name="Compact Espresso Machine",
        description="Compact home espresso machine",
        production_time_hours=3,
    ),
    Product(
        id="P004",
        name="Coffee Grinder",
        description="Automatic coffee grinder",
        production_time_hours=2,
    ),
    Product(
        id="P005",
        name="Milk Frother",
        description="Automatic milk frother",
        production_time_hours=1.5,
    ),
]


MATERIALS = [
    Material(
        id="M001",
        name="Steel Housing",
        lead_time_days=2,
        safety_stock=10,
    ),
    Material(
        id="M002",
        name="Heating Element",
        lead_time_days=3,
        safety_stock=10,
    ),
    Material(
        id="M003",
        name="Control Board",
        lead_time_days=4,
        safety_stock=8,
    ),
    Material(
        id="M004",
        name="Water Pump",
        lead_time_days=2,
        safety_stock=10,
    ),
    Material(
        id="M005",
        name="Coffee Grinder Assembly",
        lead_time_days=3,
        safety_stock=5,
    ),
    Material(
        id="M006",
        name="Motor",
        lead_time_days=2,
        safety_stock=5,
    ),
    Material(
        id="M007",
        name="Plastic Housing",
        lead_time_days=2,
        safety_stock=10,
    ),
    Material(
        id="M008",
        name="Display Module",
        lead_time_days=3,
        safety_stock=5,
    ),
    Material(
        id="M009",
        name="Power Supply",
        lead_time_days=2,
        safety_stock=8,
    ),
    Material(
        id="M010",
        name="Frothing Assembly",
        lead_time_days=3,
        safety_stock=5,
    ),
]


BOMS = [
    BOM(
        product_id="P001",
        components=[
            BOMLine(component_id="M001", quantity=1),
            BOMLine(component_id="M002", quantity=1),
            BOMLine(component_id="M003", quantity=1),
            BOMLine(component_id="M004", quantity=1),
            BOMLine(component_id="M008", quantity=1),
            BOMLine(component_id="M009", quantity=1),
        ],
    ),
    BOM(
        product_id="P002",
        components=[
            BOMLine(component_id="M001", quantity=1.5),
            BOMLine(component_id="M002", quantity=2),
            BOMLine(component_id="M003", quantity=1),
            BOMLine(component_id="M004", quantity=2),
            BOMLine(component_id="M005", quantity=1),
            BOMLine(component_id="M008", quantity=1),
            BOMLine(component_id="M009", quantity=1),
        ],
    ),
    BOM(
        product_id="P003",
        components=[
            BOMLine(component_id="M007", quantity=1),
            BOMLine(component_id="M002", quantity=1),
            BOMLine(component_id="M003", quantity=1),
            BOMLine(component_id="M004", quantity=1),
            BOMLine(component_id="M009", quantity=1),
        ],
    ),
    BOM(
        product_id="P004",
        components=[
            BOMLine(component_id="M006", quantity=1),
            BOMLine(component_id="M005", quantity=1),
            BOMLine(component_id="M007", quantity=1),
            BOMLine(component_id="M009", quantity=1),
        ],
    ),
    BOM(
        product_id="P005",
        components=[
            BOMLine(component_id="M010", quantity=1),
            BOMLine(component_id="M006", quantity=1),
            BOMLine(component_id="M007", quantity=1),
            BOMLine(component_id="M009", quantity=1),
        ],
    ),
]


INVENTORY = [
    InventoryItem(item_id="M001", quantity_on_hand=40),
    InventoryItem(item_id="M002", quantity_on_hand=25),
    InventoryItem(item_id="M003", quantity_on_hand=15),
    InventoryItem(item_id="M004", quantity_on_hand=30),
    InventoryItem(item_id="M005", quantity_on_hand=12),
    InventoryItem(item_id="M006", quantity_on_hand=20),
    InventoryItem(item_id="M007", quantity_on_hand=35),
    InventoryItem(item_id="M008", quantity_on_hand=18),
    InventoryItem(item_id="M009", quantity_on_hand=30),
    InventoryItem(item_id="M010", quantity_on_hand=10),
]


MACHINES = [
    Machine(
        id="MC001",
        name="Assembly Line A",
        work_center="Assembly",
        capacity_hours_per_day=16,
    ),
    Machine(
        id="MC002",
        name="Assembly Line B",
        work_center="Assembly",
        capacity_hours_per_day=12,
    ),
    Machine(
        id="MC003",
        name="Electronics Station",
        work_center="Electronics",
        capacity_hours_per_day=10,
    ),
    Machine(
        id="MC004",
        name="Finishing Station",
        work_center="Finishing",
        capacity_hours_per_day=8,
    ),
]


ORDERS = [
    CustomerOrder(
        id="ORD001",
        product_id="P001",
        quantity=12,
        due_date="2026-09-08",
        priority=2,
    ),
    CustomerOrder(
        id="ORD002",
        product_id="P002",
        quantity=8,
        due_date="2026-09-09",
        priority=1,
    ),
    CustomerOrder(
        id="ORD003",
        product_id="P003",
        quantity=15,
        due_date="2026-09-10",
        priority=2,
    ),
    CustomerOrder(
        id="ORD004",
        product_id="P004",
        quantity=10,
        due_date="2026-09-09",
        priority=3,
    ),
    CustomerOrder(
        id="ORD005",
        product_id="P005",
        quantity=8,
        due_date="2026-09-11",
        priority=3,
    ),
    CustomerOrder(
        id="ORD006",
        product_id="P001",
        quantity=6,
        due_date="2026-09-11",
        priority=4,
    ),
]