"""Plan one customer order.

Order -> finished-goods netting -> MPS -> capacity check -> BOM explosion -> MRP netting -> shortages -> validation.
"""

from collections.abc import Iterable, Mapping
from datetime import date

from app.mrpii.capacity import check_capacity
from app.mrpii.mps import create_mps, net_finished_goods
from app.mrpii.mrp import find_shortages, run_mrp
from app.mrpii.validator import validate_plan
from app.schemas.domain import (
    BOMLine,
    CustomerOrder,
    InventoryPosition,
    PlanSnapshot,
    PlanStatus,
    ProductionParameters,
    ScheduledReceipt,
    ViolationCode,
)


def plan_order(
    order: CustomerOrder,
    bom: Iterable[BOMLine],
    production: Mapping[str, ProductionParameters],
    inventory: Mapping[str, InventoryPosition],
    receipts: Iterable[ScheduledReceipt] = (),
    planning_date: date | None = None,
    finished_goods: Mapping[str, InventoryPosition] | None = None,
) -> PlanSnapshot:
    """`planning_date` is passed in (no clock access); it defaults to the order date.

    `inventory` holds components (used by MRP); `finished_goods` holds finished-product positions (used only to net
    the order before the MPS). No finished-goods stock means the full order quantity is produced.
    """
    receipts = list(receipts)
    netting = net_finished_goods(order, finished_goods or {})
    mps = create_mps(order, production, netting)
    requirements = run_mrp(mps, bom, inventory, receipts, {order.id: order.order_number})
    shortages = find_shortages(requirements, mps)
    checks = [check_capacity(entry, production[entry.item_id]) for entry in mps]
    validation = validate_plan(order, mps, requirements, checks, inventory, receipts)

    if validation.valid:
        status = PlanStatus.VALIDATED
    elif all(v.code == ViolationCode.SHORTAGE_UNRESOLVED for v in validation.violations):
        status = PlanStatus.SHORTAGE
    else:
        status = PlanStatus.INVALID

    return PlanSnapshot(
        order_id=order.id,
        planning_date=planning_date or order.order_date,
        status=status,
        finished_goods=netting,
        mps=mps,
        requirements=requirements,
        shortages=shortages,
        capacity_checks=checks,
        validation=validation,
    )
