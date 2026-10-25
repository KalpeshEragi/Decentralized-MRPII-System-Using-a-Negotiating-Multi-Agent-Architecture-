"""Multi-level MRP (RD-1, quantity_accounting.md §6). Pure functions, no database.

Items are planned level by level from the top (low-level code 0 = finished product). An item used at several levels is
planned at its deepest level, so all its demand is known first. Per item:

    gross(t)  = demand (top level) or Σ parent planned quantity × quantity_per at the parent's start day,
                plus existing promises (reservations, holds) at their due days
    PAB(t)    = PAB(t−1) + scheduled receipts(t) + planned receipts(t) − gross(t),  PAB(0) = on_hand
    net(t)    = safety_stock − PAB before a planned receipt, when that is below safety stock
    planned   = lot rule applied to net: lot-for-lot / multiple m (round up) / minimum q
    release   = need day − supplier lead time (bought) or the start day from capacity scheduling (made)

The planned quantity after lot sizing creates the children's gross requirements. Planned orders are proposals.
"""

import math
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.mrpii.atp import Dated

ZERO = Decimal(0)

MAKE, BUY = "MAKE", "BUY"
LOT_FOR_LOT, MULTIPLE, MINIMUM = "LOT_FOR_LOT", "MULTIPLE", "MINIMUM"


@dataclass(frozen=True)
class ItemData:
    """What Planning knows about one item for this run (from Inventory's and Purchasing's read functions)."""

    item_id: str
    sourcing: str  # MAKE or BUY
    on_hand: Decimal = ZERO
    safety_stock: Decimal = ZERO
    incoming: tuple[Dated, ...] = ()  # scheduled receipts
    promises: tuple[Dated, ...] = ()  # existing reservations and holds of other orders
    lot_rule: str = LOT_FOR_LOT
    lot_size: Decimal = ZERO  # the multiple or the minimum
    lead_time_days: int = 0  # bought items: supplier lead time


@dataclass(frozen=True)
class BomLine:
    parent_id: str
    child_id: str
    quantity_per: Decimal


@dataclass(frozen=True)
class Demand:
    item_id: str
    quantity: Decimal
    need_day: date
    source: str  # e.g. the customer demand or the parent planned order it comes from


@dataclass(frozen=True)
class PlannedOrder:
    item_id: str
    sourcing: str
    quantity: Decimal
    need_day: date
    release_day: date
    level: int
    source: str  # the demand that triggered it (first gross requirement found short)
    net_requirement: Decimal


@dataclass
class ItemRecord:
    """The time-phased record of one item, kept to explain the result (and for tests)."""

    item_id: str
    level: int
    rows: list[dict] = field(default_factory=list)  # one row per day with any movement
    final_pab: Decimal = ZERO


@dataclass
class MrpResult:
    planned_orders: list[PlannedOrder]
    records: dict[str, ItemRecord]
    unschedulable: list[Demand]  # made items whose production does not fit before their need day


# For a made item: (item_id, quantity, need_day) -> start day of production, or None if it does not fit.
ProductionStart = Callable[[str, Decimal, date], date | None]


def low_level_codes(items: Iterable[str], bom: Iterable[BomLine]) -> dict[str, int]:
    """Deepest BOM level of every item. Raises ValueError if the BOM contains a loop."""
    children = defaultdict(list)
    for line in bom:
        children[line.parent_id].append(line.child_id)
    level: dict[str, int] = {item: 0 for item in items}

    def visit(item: str, depth: int, path: tuple[str, ...]) -> None:
        if item in path:
            raise ValueError(f"BOM loop: {' -> '.join((*path, item))}")
        level[item] = max(level.get(item, 0), depth)
        for child in children.get(item, ()):
            visit(child, depth + 1, (*path, item))

    parents = {line.parent_id for line in bom}
    roots = [item for item in level if item not in {line.child_id for line in bom}] or list(parents)
    for root in roots:
        visit(root, 0, ())
    return level


def apply_lot_rule(net: Decimal, item: ItemData) -> Decimal:
    if net <= 0:
        return ZERO
    if item.lot_rule == MULTIPLE and item.lot_size > 0:
        return Decimal(math.ceil(net / item.lot_size)) * item.lot_size
    if item.lot_rule == MINIMUM:
        return max(net, item.lot_size)
    return net


def run_mrp(demands: Iterable[Demand], items: dict[str, ItemData], bom: Iterable[BomLine],
            production_start: ProductionStart) -> MrpResult:
    bom = list(bom)
    levels = low_level_codes(items, bom)
    children = defaultdict(list)
    for line in bom:
        children[line.parent_id].append(line)

    gross: dict[str, list[Demand]] = defaultdict(list)
    for demand in demands:
        gross[demand.item_id].append(demand)

    planned: list[PlannedOrder] = []
    records: dict[str, ItemRecord] = {}
    unschedulable: list[Demand] = []

    for item_id in sorted(items, key=lambda i: (levels[i], i)):
        item = items[item_id]
        record = ItemRecord(item_id, levels[item_id])
        records[item_id] = record
        days = sorted({d.need_day for d in gross[item_id]} | {r.day for r in item.incoming}
                      | {p.day for p in item.promises})
        pab = item.on_hand
        for day in days:
            receipts = sum((r.quantity for r in item.incoming if r.day == day), ZERO)
            promised = sum((p.quantity for p in item.promises if p.day == day), ZERO)
            demands_today = [d for d in gross[item_id] if d.need_day == day]
            requirement = sum((d.quantity for d in demands_today), ZERO)
            pab = pab + receipts - promised - requirement
            net = item.safety_stock - pab if pab < item.safety_stock else ZERO
            quantity = apply_lot_rule(net, item)
            row = {"day": day, "receipts": receipts, "promised": promised, "gross": requirement,
                   "net": net, "planned": quantity}
            if quantity > 0:
                source = demands_today[0].source if demands_today else "promises"
                if item.sourcing == BUY:
                    release = day - timedelta(days=item.lead_time_days)
                else:
                    release = production_start(item_id, quantity, day)
                    if release is None:
                        unschedulable.append(Demand(item_id, quantity, day, source))
                        release = day  # recorded as not schedulable; children still need the material
                order = PlannedOrder(item_id, item.sourcing, quantity, day, release, levels[item_id], source, net)
                planned.append(order)
                pab += quantity
                if item.sourcing == MAKE:
                    for line in children[item_id]:
                        gross[line.child_id].append(Demand(line.child_id, quantity * line.quantity_per, release,
                                                           f"planned:{item_id}:{day.isoformat()}"))
            row["pab"] = pab
            record.rows.append(row)
        record.final_pab = pab
    return MrpResult(planned, records, unschedulable)
