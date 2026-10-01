"""Finished-goods netting and MPS creation: one entry per order line that still needs production."""

import uuid
from collections.abc import Mapping
from decimal import Decimal

from app.mrpii.scheduling import backward_schedule
from app.schemas.domain import (
    CustomerOrder,
    FinishedGoodsNetting,
    InventoryPosition,
    MPSEntry,
    ProductionParameters,
)


def net_finished_goods(
    order: CustomerOrder, finished_goods: Mapping[str, InventoryPosition]
) -> list[FinishedGoodsNetting]:
    """net_production_requirement = max(0, order_quantity - available_finished_goods).

    available_finished_goods uses the standard rule max(0, on_hand - reserved - safety_stock). Finished goods
    are consumed across lines of the same item within the order. Component inventory is not used here.
    """
    remaining = {item_id: position.available_quantity for item_id, position in finished_goods.items()}
    result = []
    for line in order.lines:
        available = remaining.get(line.item_id, Decimal(0))
        used = min(available, line.quantity)
        remaining[line.item_id] = available - used
        result.append(
            FinishedGoodsNetting(
                order_id=order.id,
                item_id=line.item_id,
                order_quantity=line.quantity,
                available_finished_goods=available,
                net_production_requirement=line.quantity - used,
            )
        )
    return result


def create_mps(
    order: CustomerOrder,
    production: Mapping[str, ProductionParameters],
    netting: list[FinishedGoodsNetting],
) -> list[MPSEntry]:
    """planned_quantity = net production requirement; lines fully covered by finished goods get no entry.

    Entries are not merged across orders; priority is copied from the order; planned_end = due_date.
    """
    entries = []
    for index, (line, net) in enumerate(zip(order.lines, netting, strict=True)):
        if net.net_production_requirement == 0:
            continue
        if line.item_id not in production:
            raise ValueError(f"no production parameters for item {line.item_id}")
        start, end = backward_schedule(order.due_date, production[line.item_id].production_lead_time_days)
        entries.append(
            MPSEntry(
                id=str(uuid.uuid5(uuid.UUID(order.id), f"mps-{index}-{line.item_id}")),
                order_id=order.id,
                item_id=line.item_id,
                planned_quantity=net.net_production_requirement,
                planned_start=start,
                planned_end=end,
                priority=order.priority,
            )
        )
    return entries
