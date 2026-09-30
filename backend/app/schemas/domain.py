"""C1 domain shapes: the in-memory data the deterministic MRPII core consumes and produces.

Quantities are Decimal (never float) and dates are whole-day `date` values (P0-16).
There is no cost/price field anywhere (out of scope for the 25%).
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, computed_field, model_validator

def _json_number(value: Decimal) -> int | float:
    """C1: quantities are Decimal in memory and numbers in JSON."""
    return int(value) if value == value.to_integral_value() else float(value)


JsonDecimal = PlainSerializer(_json_number, return_type=int | float, when_used="json")
Quantity = Annotated[Decimal, Field(ge=0), JsonDecimal]
PositiveQuantity = Annotated[Decimal, Field(gt=0), JsonDecimal]
Priority = Annotated[int, Field(ge=1, le=5)]  # 1 = highest (P0-15)


class Shape(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ItemType(StrEnum):
    FINISHED_PRODUCT = "FINISHED_PRODUCT"
    COMPONENT = "COMPONENT"
    RAW_MATERIAL = "RAW_MATERIAL"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PLANNING = "PLANNING"
    PLANNED = "PLANNED"


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    SHORTAGE = "SHORTAGE"
    VALIDATED = "VALIDATED"
    INVALID = "INVALID"


class RequirementStatus(StrEnum):
    COVERED = "COVERED"
    SHORTAGE = "SHORTAGE"
    PROCUREMENT_AGREED = "PROCUREMENT_AGREED"
    PROCUREMENT_FAILED = "PROCUREMENT_FAILED"


class ViolationCode(StrEnum):
    SHORTAGE_UNRESOLVED = "SHORTAGE_UNRESOLVED"
    RECEIPT_AFTER_REQUIRED_DATE = "RECEIPT_AFTER_REQUIRED_DATE"
    DUE_DATE_MISSED = "DUE_DATE_MISSED"
    OVER_ALLOCATION = "OVER_ALLOCATION"
    SAFETY_STOCK_VIOLATION = "SAFETY_STOCK_VIOLATION"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"


class Item(Shape):
    id: str
    sku: str
    name: str
    item_type: ItemType
    unit: str = "pcs"


class BOMLine(Shape):
    """Single-level BOM line (P1-02)."""

    parent_item_id: str
    component_item_id: str
    quantity_per: PositiveQuantity


class OrderLine(Shape):
    item_id: str
    quantity: PositiveQuantity


class CustomerOrder(Shape):
    id: str
    order_number: str
    customer_id: str
    order_date: date
    due_date: date
    priority: Priority
    status: OrderStatus = OrderStatus.NEW
    lines: list[OrderLine] = Field(min_length=1)

    @model_validator(mode="after")
    def _due_date_not_before_order_date(self) -> "CustomerOrder":
        if self.due_date < self.order_date:
            raise ValueError("due_date must be >= order_date")
        return self


class InventoryPosition(Shape):
    """One aggregated position per item. Incoming stock is never part of availability."""

    item_id: str
    on_hand: Quantity
    reserved: Quantity
    safety_stock: Quantity

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_quantity(self) -> Annotated[Decimal, JsonDecimal]:
        return max(Decimal(0), self.on_hand - self.reserved - self.safety_stock)


class ScheduledReceipt(Shape):
    """Committed incoming material (a committed negotiation agreement, P0-12)."""

    item_id: str
    quantity: PositiveQuantity
    expected_date: date
    source_ref: str


class ProductionParameters(Shape):
    """Per-product production values from fixture/config (P0-11, P0-14)."""

    item_id: str
    production_lead_time_days: Annotated[int, Field(ge=1)]
    capacity_per_day: PositiveQuantity


class SupplierOption(Shape):
    """Supplier data (not an agent). No price/cost. Service shape is C3 (Phase 2); fields follow the X1 fixture."""

    item_id: str
    supplier: str
    lead_time_days: Annotated[int, Field(ge=0)]
    min_order_qty: PositiveQuantity
    available_qty: Quantity


class FinishedGoodsNetting(Shape):
    """Finished-goods netting of one order line, done before the MPS is created."""

    order_id: str
    item_id: str
    order_quantity: PositiveQuantity
    available_finished_goods: Quantity
    net_production_requirement: Quantity


class MPSEntry(Shape):
    id: str
    order_id: str
    item_id: str
    planned_quantity: PositiveQuantity
    planned_start: date
    planned_end: date
    priority: Priority


class MaterialRequirement(Shape):
    """One MRP row."""

    mps_entry_id: str
    item_id: str
    gross_requirement: Quantity
    available_quantity: Quantity
    scheduled_receipts: Quantity
    projected_available_quantity: Quantity
    net_requirement: Quantity
    required_by: date
    status: RequirementStatus


class Shortage(Shape):
    item_id: str
    order_id: str
    mps_entry_id: str
    shortage_quantity: PositiveQuantity
    required_by: date
    priority: Priority
    available_quantity: Quantity
    projected_available_quantity: Quantity


class CapacityCheck(Shape):
    """Minimal capacity check (P1-03). `mps_entry_id` and `required_days` are additions to the C1 example."""

    mps_entry_id: str
    item_id: str
    required_quantity: Quantity
    capacity_per_day: PositiveQuantity
    required_days: int
    working_days: int
    max_quantity: Quantity
    feasible: bool


class Violation(Shape):
    code: ViolationCode
    message: str
    item_id: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class PlanValidationResult(Shape):
    valid: bool
    violations: list[Violation] = Field(default_factory=list)


class PlanSnapshot(Shape):
    order_id: str
    planning_date: date
    status: PlanStatus
    finished_goods: list[FinishedGoodsNetting]
    mps: list[MPSEntry]
    requirements: list[MaterialRequirement]
    shortages: list[Shortage]
    capacity_checks: list[CapacityCheck]
    validation: PlanValidationResult
