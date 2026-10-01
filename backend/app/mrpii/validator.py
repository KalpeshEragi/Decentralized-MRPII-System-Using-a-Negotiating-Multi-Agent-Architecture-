"""Deterministic plan validation (C1 section 3.10). A failed validation is a normal result, not an error."""

from collections.abc import Iterable, Mapping
from decimal import Decimal

from app.schemas.domain import (
    CapacityCheck,
    CustomerOrder,
    InventoryPosition,
    MaterialRequirement,
    MPSEntry,
    PlanValidationResult,
    ScheduledReceipt,
    Violation,
    ViolationCode,
)

ZERO = Decimal(0)


def validate_plan(
    order: CustomerOrder,
    mps: Iterable[MPSEntry],
    requirements: Iterable[MaterialRequirement],
    capacity_checks: Iterable[CapacityCheck],
    inventory: Mapping[str, InventoryPosition],
    receipts: Iterable[ScheduledReceipt],
) -> PlanValidationResult:
    mps, requirements, receipts = list(mps), list(requirements), list(receipts)
    violations: list[Violation] = []

    def add(code: ViolationCode, message: str, item_id: str | None = None, **details: object) -> None:
        violations.append(
            Violation(code=code, message=message, item_id=item_id, details={k: str(v) for k, v in details.items()})
        )

    for entry in mps:
        if entry.planned_quantity <= 0:
            add(ViolationCode.INVALID_QUANTITY, f"MPS {entry.id} has non-positive quantity", entry.item_id)
        if entry.planned_end > order.due_date:
            add(
                ViolationCode.DUE_DATE_MISSED,
                f"planned_end {entry.planned_end} is after due date {order.due_date}",
                entry.item_id,
                planned_end=entry.planned_end,
                due_date=order.due_date,
            )

    for check in capacity_checks:
        if not check.feasible:
            add(
                ViolationCode.CAPACITY_EXCEEDED,
                f"{check.required_quantity} units need {check.required_days} days, {check.working_days} available",
                check.item_id,
                required_days=check.required_days,
                working_days=check.working_days,
            )

    consumed: dict[str, Decimal] = {}
    for row in requirements:
        if min(row.gross_requirement, row.net_requirement, row.available_quantity, row.scheduled_receipts) < 0:
            add(ViolationCode.INVALID_QUANTITY, "negative MRP quantity", row.item_id)
        position = inventory.get(row.item_id)
        if row.available_quantity > (position.available_quantity if position else ZERO):
            add(
                ViolationCode.SAFETY_STOCK_VIOLATION,
                "row uses more stock than available_quantity allows",
                row.item_id,
                row_available=row.available_quantity,
            )
        eligible = sum(
            (r.quantity for r in receipts if r.item_id == row.item_id and r.expected_date <= row.required_by), ZERO
        )
        if row.scheduled_receipts > eligible:
            add(
                ViolationCode.RECEIPT_AFTER_REQUIRED_DATE,
                "row relies on receipts arriving after required_by",
                row.item_id,
                required_by=row.required_by,
            )
        consumed[row.item_id] = consumed.get(row.item_id, ZERO) + row.gross_requirement - row.net_requirement
        if row.net_requirement > 0:
            add(
                ViolationCode.SHORTAGE_UNRESOLVED,
                f"short by {row.net_requirement} for {order.order_number}",
                row.item_id,
                shortage_quantity=row.net_requirement,
                required_by=row.required_by,
            )

    for item_id, used in consumed.items():
        position = inventory.get(item_id)
        supply = (position.available_quantity if position else ZERO) + sum(
            (r.quantity for r in receipts if r.item_id == item_id), ZERO
        )
        if used > supply:
            add(
                ViolationCode.OVER_ALLOCATION,
                "plan consumes more than available stock plus receipts",
                item_id,
                consumed=used,
                supply=supply,
            )

    return PlanValidationResult(valid=not violations, violations=violations)
