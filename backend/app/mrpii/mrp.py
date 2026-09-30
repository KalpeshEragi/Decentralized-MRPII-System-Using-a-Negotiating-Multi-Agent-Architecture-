"""Single-level BOM explosion and time-phased MRP netting (C1 section 3.7)."""

from collections.abc import Iterable, Mapping
from decimal import Decimal

from app.schemas.domain import (
    BOMLine,
    InventoryPosition,
    MaterialRequirement,
    MPSEntry,
    RequirementStatus,
    ScheduledReceipt,
    Shortage,
)

ZERO = Decimal(0)


def explode_bom(entry: MPSEntry, bom: Iterable[BOMLine]) -> list[tuple[BOMLine, Decimal]]:
    """(bom_line, gross_requirement) for each component of the entry's product."""
    return [(line, entry.planned_quantity * line.quantity_per) for line in bom if line.parent_item_id == entry.item_id]


def run_mrp(
    mps: Iterable[MPSEntry],
    bom: Iterable[BOMLine],
    inventory: Mapping[str, InventoryPosition],
    receipts: Iterable[ScheduledReceipt],
    order_numbers: Mapping[str, str],
) -> list[MaterialRequirement]:
    """Net every component requirement.

    Entries are processed by ascending required_by, then priority (1 first), then order number; each consumes
    available stock first, then eligible scheduled receipts (expected_date <= required_by, earliest first)
    before the next entry is netted. Incoming stock is never part of available_quantity.
    """
    bom = list(bom)
    available = {item_id: position.available_quantity for item_id, position in inventory.items()}
    remaining = [[receipt, receipt.quantity] for receipt in sorted(receipts, key=lambda r: r.expected_date)]
    ordered = sorted(mps, key=lambda e: (e.planned_start, e.priority, order_numbers[e.order_id]))

    rows = []
    for entry in ordered:
        required_by = entry.planned_start
        for line, gross in explode_bom(entry, bom):
            item_id = line.component_item_id
            row_available = available.get(item_id, ZERO)
            eligible = [
                slot
                for slot in remaining
                if slot[0].item_id == item_id and slot[0].expected_date <= required_by and slot[1] > 0
            ]
            row_receipts = sum((slot[1] for slot in eligible), ZERO)
            projected = row_available + row_receipts
            net = max(ZERO, gross - projected)

            # Consume stock first, then receipts in date order, so the next entry sees what is left.
            from_stock = min(gross, row_available)
            available[item_id] = row_available - from_stock
            need = gross - from_stock
            for slot in eligible:
                take = min(need, slot[1])
                slot[1] -= take
                need -= take

            rows.append(
                MaterialRequirement(
                    mps_entry_id=entry.id,
                    item_id=item_id,
                    gross_requirement=gross,
                    available_quantity=row_available,
                    scheduled_receipts=row_receipts,
                    projected_available_quantity=projected,
                    net_requirement=net,
                    required_by=required_by,
                    status=RequirementStatus.SHORTAGE if net > 0 else RequirementStatus.COVERED,
                )
            )
    return rows


def find_shortages(requirements: Iterable[MaterialRequirement], mps: Iterable[MPSEntry]) -> list[Shortage]:
    """One Shortage per requirement with net_requirement > 0 (shortage_quantity == net_requirement)."""
    entries = {entry.id: entry for entry in mps}
    return [
        Shortage(
            item_id=row.item_id,
            order_id=entries[row.mps_entry_id].order_id,
            mps_entry_id=row.mps_entry_id,
            shortage_quantity=row.net_requirement,
            required_by=row.required_by,
            priority=entries[row.mps_entry_id].priority,
            available_quantity=row.available_quantity,
            projected_available_quantity=row.projected_available_quantity,
        )
        for row in requirements
        if row.net_requirement > 0
    ]
