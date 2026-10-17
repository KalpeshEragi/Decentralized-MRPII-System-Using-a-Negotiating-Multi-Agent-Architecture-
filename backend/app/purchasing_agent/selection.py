"""Supplier selection. Plain functions: no database and no clock (the caller passes the selection date).

Rules: docs/agent_architectures/purchasing_agent_architecture.md §6. This tracer chooses only the best priced single
supplier; splits, the unpriced fallback, effective availability and the Constrained Quantity come in later tickets.
All money and quantities are `Decimal`, never floats.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

PriceKind = Literal["PRICED", "NOT_REGISTERED", "CONTRACT_OVERLAP"]


@dataclass(frozen=True)
class Contract:
    id: uuid.UUID
    unit_price: Decimal
    valid_from: date
    valid_until: date | None  # None = open-ended
    is_active: bool


@dataclass(frozen=True)
class PriceState:
    kind: PriceKind
    unit_price: Decimal | None = None
    contract_id: uuid.UUID | None = None


def price_state(contracts: Iterable[Contract], on: date) -> PriceState:
    """A price only when exactly one active contract covers `on`. None: Not Registered (never zero). More than one is
    bad data: the supplier-item is excluded (`contract_overlap`)."""
    valid = [c for c in contracts if c.is_active and c.valid_from <= on and (c.valid_until is None or on <= c.valid_until)]
    if not valid:
        return PriceState("NOT_REGISTERED")
    if len(valid) > 1:
        return PriceState("CONTRACT_OVERLAP")
    return PriceState("PRICED", valid[0].unit_price, valid[0].id)


@dataclass(frozen=True)
class SupplierOption:
    """One supplier of the item, as the Supplier Service reports it, plus its price state on the selection date."""

    supplier_id: uuid.UUID
    supplier_name: str
    is_active: bool
    lead_time_days: int
    min_order_qty: Decimal
    available_qty: Decimal
    price: PriceState


@dataclass(frozen=True)
class ConsideredOption:
    """How one supplier was judged. `reason` says why it won or why it did not."""

    supplier_id: uuid.UUID
    supplier_name: str
    price_kind: PriceKind
    unit_price: Decimal | None
    contract_id: uuid.UUID | None
    arrival: date
    min_order_qty: Decimal
    available_qty: Decimal
    order_quantity: Decimal  # max(shortage, MOQ): MOQ surplus is ordered and paid for
    total_cost: Decimal | None  # None when Not Registered
    reason: str


@dataclass(frozen=True)
class Selection:
    outcome: Literal["SINGLE", "FAILED"]
    winner: ConsideredOption | None
    options: list[ConsideredOption]
    reasoning_summary: str


def _unusable_reason(option: SupplierOption, shortage: Decimal, required_date: date, arrival: date) -> str | None:
    if not option.is_active:
        return "inactive_supplier"
    if option.price.kind == "CONTRACT_OVERLAP":
        return "contract_overlap"
    if arrival > required_date:
        return "arrives_too_late"
    if option.available_qty < option.min_order_qty:
        return "availability_below_moq"
    if option.available_qty < shortage:
        return "cannot_cover_alone"
    if option.price.kind == "NOT_REGISTERED":
        return "not_registered"
    return None


def _rank(option: ConsideredOption) -> tuple:
    """Lowest Total Purchasing Cost, then earliest arrival, then larger availability, then name."""
    return option.total_cost, option.arrival, -option.available_qty, option.supplier_name


def select_single_supplier(
    shortage: Decimal, required_date: date, options: Sequence[SupplierOption], selection_date: date
) -> Selection:
    considered: list[ConsideredOption] = []
    candidates: list[ConsideredOption] = []
    for option in options:
        arrival = selection_date + timedelta(days=option.lead_time_days)
        order_quantity = max(shortage, option.min_order_qty)
        unit_price = option.price.unit_price
        judged = ConsideredOption(
            supplier_id=option.supplier_id, supplier_name=option.supplier_name, price_kind=option.price.kind,
            unit_price=unit_price, contract_id=option.price.contract_id, arrival=arrival,
            min_order_qty=option.min_order_qty, available_qty=option.available_qty, order_quantity=order_quantity,
            total_cost=unit_price * order_quantity if unit_price is not None else None,
            reason=_unusable_reason(option, shortage, required_date, arrival) or "",
        )
        considered.append(judged)
        if not judged.reason:
            candidates.append(judged)

    if not candidates:
        return Selection("FAILED", None, considered,
                         "No active, priced supplier can deliver the full quantity by the required date.")
    winner = replace(min(candidates, key=_rank), reason="selected")
    # Usable candidates that lost were outranked; everyone else keeps the reason they were unusable.
    considered = [winner if o.supplier_id == winner.supplier_id else replace(o, reason=o.reason or "higher_cost")
                  for o in considered]
    return Selection("SINGLE", winner, considered, (
        f"{winner.supplier_name} is the lowest-cost priced supplier that can deliver {winner.order_quantity} by "
        f"{required_date.isoformat()}: {winner.order_quantity} x {winner.unit_price} = {winner.total_cost} INR, "
        f"arriving {winner.arrival.isoformat()}."
    ))

