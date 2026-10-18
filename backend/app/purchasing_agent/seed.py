"""The Purchasing fixture (dev_docs/purchasing_agent/seed_data.md §2–§4) in the three new schemas only: `supplier_service`,
`purchasing_agent` and `negotiation_engine`. Legacy schemas and the Sales Agent are never touched.

The Pixel Boards contracts overlap on purpose. They are inserted directly, bypassing the contract write check, so the
selection-time `contract_overlap` exclusion can be tested.

Run from `backend/` to reset the database in DATABASE_URL to the fixture:  python -m app.purchasing_agent.seed
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent.models import PurchasingAgentBase, PurchasingContract
from app.supplier_service import seed as supplier_seed
from app.supplier_service.seed import ITEM_IDS, SUPPLIER_IDS

OPEN = None  # open-ended contract

CONTRACTS = [  # supplier, item, unit price, valid_from, valid_until, is_active
    ("Alpha Displays", "DSP-100", "1200.00", date(2026, 1, 1), OPEN, True),
    ("Beta Optics", "DSP-100", "1250.00", date(2026, 1, 1), date(2026, 12, 31), True),
    ("Volt Power", "BAT-200", "800.00", date(2026, 6, 1), OPEN, True),
    ("Cell Works", "BAT-200", "900.00", date(2026, 6, 1), OPEN, True),
    ("Ion Supply", "BAT-200", "1000.00", date(2026, 6, 1), OPEN, True),
    ("Nova Silicon", "MBD-300", "1100.00", date(2026, 1, 1), date(2026, 10, 31), True),  # expired on D
    ("Nova Silicon", "MBD-300", "1150.00", date(2026, 12, 1), OPEN, True),  # future on D
    ("Orbit Circuits", "MBD-300", "1050.00", date(2026, 1, 1), OPEN, False),  # inactive
    ("Pixel Boards", "MBD-300", "1400.00", date(2026, 1, 1), OPEN, True),  # overlaps the next row (bad data)
    ("Pixel Boards", "MBD-300", "1350.00", date(2026, 10, 1), OPEN, True),
    ("Quartz Electronics", "MBD-300", "1500.00", date(2026, 1, 1), OPEN, True),
    ("Lumen Optics", "CAM-400", "2000.00", date(2026, 1, 1), OPEN, True),
    ("Prism Labs", "CAM-400", "1800.00", date(2026, 1, 1), OPEN, True),
    ("Sonic Audio", "SPK-500", "300.00", date(2026, 1, 1), OPEN, True),
    ("EchoTech", "SPK-500", "320.00", date(2026, 1, 1), OPEN, True),
    ("Wave Acoustics", "SPK-500", "340.00", date(2026, 1, 1), OPEN, True),
    ("PlugCo", "CHP-600", "100.00", date(2026, 1, 1), OPEN, True),
    ("ConnectRite", "CHP-600", "87.50", date(2026, 1, 1), OPEN, True),
]


def reset_and_seed(db: Session) -> None:
    """Empty the three new schemas and load the fixture, in one transaction."""
    tables = ", ".join(f'"{t.schema}"."{t.name}"' for t in PurchasingAgentBase.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE {tables} CASCADE"))
    negotiation_engine.reset(db)
    supplier_seed.reset(db)
    supplier_seed.seed(db)
    db.add_all(
        PurchasingContract(supplier_id=SUPPLIER_IDS[supplier], item_id=ITEM_IDS[sku], unit_price=Decimal(price),
                           valid_from=valid_from, valid_until=valid_until, is_active=is_active)
        for supplier, sku, price, valid_from, valid_until, is_active in CONTRACTS
    )
    db.commit()


if __name__ == "__main__":
    from app.core.database import new_session

    with new_session() as session:
        reset_and_seed(session)
    print("Purchasing fixture loaded (supplier_service, purchasing_agent, negotiation_engine)")
