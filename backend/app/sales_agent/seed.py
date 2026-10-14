"""A few test products so the Sales Agent has something to sell while it is built and tested alone.

These are placeholders, not the real catalogue. Later the products come from the shared product list.

Run from `backend/` to add them to the database in DATABASE_URL:  python -m app.sales_agent.seed
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.sales_agent.models import Product

TEST_PRODUCTS = [
    ("X1-PHONE", "SmartPhone X1"),
    ("X2-PHONE", "SmartPhone X2"),
    ("T1-TABLET", "Tablet T1"),
]


def seed_products(db: Session) -> int:
    """Add the test products that are not in the database yet. Safe to run twice. Returns how many were added."""
    existing_skus = set(db.scalars(select(Product.sku)))
    new_products = [Product(sku=sku, name=name) for sku, name in TEST_PRODUCTS if sku not in existing_skus]
    db.add_all(new_products)
    db.commit()
    return len(new_products)


if __name__ == "__main__":
    from app.core.database import new_session

    with new_session() as session:
        added = seed_products(session)
    print(f"{added} test products added")
