"""Plan customer orders.

Order -> finished-goods netting -> MPS -> capacity check -> BOM explosion -> MRP netting -> shortages -> validation.

`plan_order` plans one order. `plan_orders` plans several orders together with the same functions (Phase 5):
    finished goods   shared across orders in priority order (1 first), then due date, then order number; each order
                     nets against what the previous ones left (the existing rule already shares them across the lines
                     of one order, in line order)
    MPS              one entry per order line with a net production requirement (entries are never merged)
    MRP              all entries netted together by the existing rule (required_by, priority, order number): an earlier
                     or higher-priority entry consumes stock and receipts first
    capacity         checked per MPS entry against its own production window, as for one order; overlapping windows
                     of different orders are not pooled (no finite-capacity scheduling in the 25%)
    validation       per order, over its own entries and requirements
With one order, `plan_orders` returns exactly what `plan_order` returns.
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


def _status(validation) -> PlanStatus:
    if validation.valid:
        return PlanStatus.VALIDATED
    if all(v.code == ViolationCode.SHORTAGE_UNRESOLVED for v in validation.violations):
        return PlanStatus.SHORTAGE
    return PlanStatus.INVALID


def plan_orders(
    orders: Iterable[CustomerOrder],
    bom: Iterable[BOMLine],
    production: Mapping[str, ProductionParameters],
    inventory: Mapping[str, InventoryPosition],
    receipts: Iterable[ScheduledReceipt] = (),
    finished_goods: Mapping[str, InventoryPosition] | None = None,
) -> list[PlanSnapshot]:
    """One PlanSnapshot per order (in the order given), computed from the combined demand of all of them."""
    orders, bom, receipts = list(orders), list(bom), list(receipts)
    remaining_fg = dict(finished_goods or {})
    netting, mps = {}, {}
    for order in sorted(orders, key=lambda o: (o.priority, o.due_date, o.order_number)):
        netting[order.id] = net_finished_goods(order, remaining_fg)
        for row in netting[order.id]:  # what this order used is no longer available to the next one
            position = remaining_fg.get(row.item_id)
            if position is not None:
                used = row.order_quantity - row.net_production_requirement
                remaining_fg[row.item_id] = position.model_copy(update={"reserved": position.reserved + used})
        mps[order.id] = create_mps(order, production, netting[order.id])

    all_mps = [entry for entries in mps.values() for entry in entries]
    requirements = run_mrp(all_mps, bom, inventory, receipts, {o.id: o.order_number for o in orders})

    snapshots = []
    for order in orders:
        own_ids = {entry.id for entry in mps[order.id]}
        own_rows = [row for row in requirements if row.mps_entry_id in own_ids]
        checks = [check_capacity(entry, production[entry.item_id]) for entry in mps[order.id]]
        validation = validate_plan(order, mps[order.id], own_rows, checks, inventory, receipts)
        snapshots.append(
            PlanSnapshot(
                order_id=order.id,
                planning_date=order.order_date,
                status=_status(validation),
                finished_goods=netting[order.id],
                mps=mps[order.id],
                requirements=own_rows,
                shortages=find_shortages(own_rows, mps[order.id]),
                capacity_checks=checks,
                validation=validation,
            )
        )
    return snapshots


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
