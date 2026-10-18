"""Sales' read module (IB-2): the only thing other agents may import from the Sales Agent. Read-only; plain data."""

import uuid

from sqlalchemy.orm import Session

from app.sales_agent.models import Product


def product_sku(db: Session, product_id: str) -> str | None:
    """The SKU of a Sales product: the link to the factory item (`core.items.sku`)."""
    try:
        product = db.get(Product, uuid.UUID(str(product_id)))
    except ValueError:
        return None
    return product.sku if product else None
