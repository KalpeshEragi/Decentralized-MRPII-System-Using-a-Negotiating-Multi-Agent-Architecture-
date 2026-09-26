from collections import defaultdict

from app.models.demand import CustomerOrder
from app.models.product import Product
from app.models.planning import MPSEntry


def generate_mps(
    orders: list[CustomerOrder],
    products: list[Product],
) -> list[MPSEntry]:
    """
    Generate a Master Production Schedule.

    Customer orders are aggregated by:
        product + due date
    """

    product_ids = {product.id for product in products}

    production_plan = defaultdict(int)

    for order in orders:

        if order.product_id not in product_ids:
            raise ValueError(
                f"Unknown product '{order.product_id}' "
                f"in order '{order.id}'"
            )

        production_plan[
            (order.product_id, order.due_date)
        ] += order.quantity

    mps = []

    for (product_id, planned_date), quantity in sorted(
        production_plan.items(),
        key=lambda item: (item[0][1], item[0][0]),
    ):
        mps.append(
            MPSEntry(
                product_id=product_id,
                quantity=quantity,
                planned_date=planned_date,
            )
        )

    return mps