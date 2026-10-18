"""Supplier selection. Plain functions: no database and no clock (the caller passes the selection date).

Rules: dev_docs/purchasing_agent/purchasing_agent_architecture.md §6.3–§6.5. A single supplier, a Cost-Saving Split
or a Necessary Split, with the unpriced fallbacks (`cost ranking unavailable`), else FAILED with the Constrained
Quantity. Every single option and every combination considered is returned with the reason it won or lost.
`reallocate` (§7.4) re-runs the same rules over only the already-selected suppliers, each limited by its cap, without
re-checking the saving threshold.
`available_qty` is the supplier's effective availability: the caller subtracts Purchasing's holds (`availability.py`).
All money and quantities are `Decimal`, never floats.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations as subsets
from typing import Literal

PriceKind = Literal["PRICED", "NOT_REGISTERED", "CONTRACT_OVERLAP"]
Outcome = Literal["SINGLE", "COST_SAVING_SPLIT", "NECESSARY_SPLIT", "FAILED"]

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


def validity_overlaps(a_from: date, a_until: date | None, b_from: date, b_until: date | None) -> bool:
    """Whether two validity periods share at least one day. Both ends are inclusive; None is open-ended."""
    return (a_until is None or b_from <= a_until) and (b_until is None or a_from <= b_until)


def price_state(contracts: Iterable[Contract], on: date) -> PriceState:
    """A price only when exactly one active contract covers `on`. None: Not Registered (never zero). More than one is
    bad data: the supplier-item is excluded (`contract_overlap`)."""
    valid = [c for c in contracts if c.is_active and validity_overlaps(c.valid_from, c.valid_until, on, on)]
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
    available_qty: Decimal  # effective availability
    price: PriceState


@dataclass(frozen=True)
class ConsideredOption:
    """How one supplier was judged as a single supplier. `reason` says why it won or why it did not."""

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
class Leg:
    """One selected supplier's part of the procurement."""

    supplier_id: uuid.UUID
    supplier_name: str
    quantity: Decimal
    unit_price: Decimal | None  # None: Not Registered
    contract_id: uuid.UUID | None
    arrival: date

    @property
    def cost(self) -> Decimal | None:
        return self.unit_price * self.quantity if self.unit_price is not None else None


@dataclass(frozen=True)
class CombinationMember:
    """What one supplier brings to a combination, so every combination, feasible or not, can be checked alone."""

    supplier_id: uuid.UUID
    supplier_name: str
    price_kind: PriceKind
    unit_price: Decimal | None  # None: Not Registered
    available_qty: Decimal
    min_order_qty: Decimal
    arrival: date


@dataclass(frozen=True)
class ConsideredCombination:
    """How one subset of ≥ 2 usable suppliers was judged. `legs` is empty when the subset can't reach the shortage."""

    supplier_names: tuple[str, ...]  # sorted
    members: tuple[CombinationMember, ...]  # sorted by name
    fully_priced: bool
    legs: tuple[Leg, ...]
    total_quantity: Decimal | None
    total_cost: Decimal | None  # None when infeasible or any supplier is Not Registered
    latest_arrival: date
    total_available: Decimal
    reason: str
    reason_detail: str | None = None  # why an infeasible combination can't fulfil the request


@dataclass(frozen=True)
class Selection:
    outcome: Outcome
    legs: list[Leg]  # empty when FAILED
    options: list[ConsideredOption]
    combinations: list[ConsideredCombination]
    reasoning_summary: str
    cost_ranking_available: bool | None = None  # False: a selected supplier is Not Registered; None when FAILED
    constrained_quantity: Decimal | None = None  # only when FAILED: total effective availability of usable suppliers
    best_priced_single: ConsideredOption | None = None  # what a split's saving is measured against; None if none covers

    @property
    def total_cost(self) -> Decimal | None:
        costs = [leg.cost for leg in self.legs]
        return sum(costs, Decimal(0)) if costs and None not in costs else None


def _unusable_reason(option: SupplierOption, required_date: date, arrival: date) -> str | None:
    if not option.is_active:
        return "inactive_supplier"
    if option.price.kind == "CONTRACT_OVERLAP":
        return "contract_overlap"
    if arrival > required_date:
        return "arrives_too_late"
    if option.available_qty < option.min_order_qty:
        return "availability_below_moq"
    return None


def _single_rank(option: ConsideredOption) -> tuple:
    """Lowest Total Purchasing Cost, then earliest arrival, then larger availability, then name."""
    return option.total_cost, option.arrival, -option.available_qty, option.supplier_name


def _fallback_rank(option: ConsideredOption) -> tuple:
    """No cost is known: earliest arrival, then larger availability, then name."""
    return option.arrival, -option.available_qty, option.supplier_name


def _single_as_combination_rank(option: ConsideredOption) -> tuple:
    """A priced single ranked as a one-supplier combination, so reallocation can rank it against the splits."""
    return option.total_cost, option.arrival, 1, -option.available_qty, (option.supplier_name,)


def _combination_rank(c: ConsideredCombination) -> tuple:
    """Priced: total cost → latest Leg arrival → fewer suppliers → larger total availability → names. With an unpriced
    supplier: latest Leg arrival → fewer suppliers → smaller total quantity → larger total availability → names."""
    if c.fully_priced:
        return c.total_cost, c.latest_arrival, len(c.supplier_names), -c.total_available, c.supplier_names
    return c.latest_arrival, len(c.supplier_names), c.total_quantity, -c.total_available, c.supplier_names


def _combination(members: Sequence[ConsideredOption], shortage: Decimal) -> ConsideredCombination:
    """Every Leg starts at its MOQ; the rest is filled up to each supplier's availability, in this order: fully
    priced: lower price → earlier arrival → larger availability → name; with an unpriced supplier: earlier arrival →
    larger availability → name. MOQs never make a subset infeasible (they only add surplus); too little total
    availability does."""
    members = sorted(members, key=lambda m: m.supplier_name)
    fully_priced = all(m.price_kind == "PRICED" for m in members)
    quantities = {m.supplier_id: m.min_order_qty for m in members}
    remaining = shortage - sum(quantities.values())
    fill_order = sorted(members, key=lambda m: (
        (m.unit_price, m.arrival) if fully_priced else (m.arrival,)) + (-m.available_qty, m.supplier_name))
    for m in fill_order:
        if remaining <= 0:
            break
        extra = min(remaining, m.available_qty - m.min_order_qty)
        quantities[m.supplier_id] += extra
        remaining -= extra
    feasible = remaining <= 0
    legs = tuple(
        Leg(m.supplier_id, m.supplier_name, quantities[m.supplier_id], m.unit_price, m.contract_id, m.arrival)
        for m in members
    ) if feasible else ()
    total_available = sum((m.available_qty for m in members), Decimal(0))
    return ConsideredCombination(
        supplier_names=tuple(m.supplier_name for m in members),
        members=tuple(CombinationMember(m.supplier_id, m.supplier_name, m.price_kind, m.unit_price, m.available_qty,
                                        m.min_order_qty, m.arrival) for m in members),
        fully_priced=fully_priced,
        legs=legs,
        total_quantity=sum((leg.quantity for leg in legs), Decimal(0)) if feasible else None,
        total_cost=sum((leg.cost for leg in legs), Decimal(0)) if feasible and fully_priced else None,
        latest_arrival=max(m.arrival for m in members),
        total_available=total_available,
        reason="" if feasible else "insufficient_quantity",
        reason_detail=None if feasible else (
            f"Together they can supply at most {total_available} of {shortage} (short by {shortage - total_available})."),
    )


def _single_leg(option: ConsideredOption) -> Leg:
    return Leg(option.supplier_id, option.supplier_name, option.order_quantity, option.unit_price,
               option.contract_id, option.arrival)


def _legs_text(legs: Iterable[Leg]) -> str:
    return " + ".join(f"{leg.supplier_name} {leg.quantity}" for leg in legs)


def select_suppliers(
    shortage: Decimal, required_date: date, options: Sequence[SupplierOption], selection_date: date,
    *, saving_threshold: Decimal,
) -> Selection:
    """`saving_threshold`: a Cost-Saving Split must cost at most (1 - this) of the best priced single supplier; exactly
    the threshold qualifies. Its one source is `Settings.purchasing_cost_saving_split_threshold`."""
    return _choose(shortage, required_date, options, selection_date, saving_threshold)


def reallocate(
    shortage: Decimal, required_date: date, selected: Sequence[SupplierOption], selection_date: date,
) -> Selection:
    """§7.4: the selection rules over only the already-selected suppliers, each `available_qty` already limited by its
    cap. Any subset, including a single supplier, wins if it ranks better: when a priced single covers, it competes with
    the priced splits on the combination ranking and the saving threshold is not re-checked. FAILED: no allocation fits
    the caps."""
    return _choose(shortage, required_date, selected, selection_date, saving_threshold=None)


def _choose(
    shortage: Decimal, required_date: date, options: Sequence[SupplierOption], selection_date: date,
    saving_threshold: Decimal | None,  # None: reallocation, the threshold is not re-checked
) -> Selection:
    considered: list[ConsideredOption] = []
    for option in options:
        arrival = selection_date + timedelta(days=option.lead_time_days)
        order_quantity = max(shortage, option.min_order_qty)
        unit_price = option.price.unit_price
        reason = _unusable_reason(option, required_date, arrival)
        if reason is None and option.available_qty < shortage:
            reason = "cannot_cover_alone"  # still usable in a combination
        considered.append(ConsideredOption(
            supplier_id=option.supplier_id, supplier_name=option.supplier_name, price_kind=option.price.kind,
            unit_price=unit_price, contract_id=option.price.contract_id, arrival=arrival,
            min_order_qty=option.min_order_qty, available_qty=option.available_qty, order_quantity=order_quantity,
            total_cost=unit_price * order_quantity if unit_price is not None else None, reason=reason or "",
        ))

    usable = sorted((o for o in considered if o.reason in ("", "cannot_cover_alone")), key=lambda o: o.supplier_name)
    covering = [o for o in usable if not o.reason]
    priced_singles = [o for o in covering if o.price_kind == "PRICED"]
    unpriced_singles = [o for o in covering if o.price_kind != "PRICED"]
    combos = [_combination(members, shortage) for size in range(2, len(usable) + 1)
              for members in subsets(usable, size)]
    feasible = [c for c in combos if not c.reason]
    best_priced_combo = min((c for c in feasible if c.fully_priced), key=_combination_rank, default=None)
    best_unpriced_combo = min((c for c in feasible if not c.fully_priced), key=_combination_rank, default=None)

    winner_combo: ConsideredCombination | None = None
    single: ConsideredOption | None = None
    if priced_singles:  # §6.4 rule 1
        single = min(priced_singles, key=_single_rank)
        if best_priced_combo is None:
            split_wins = False
        elif saving_threshold is None:
            split_wins = _combination_rank(best_priced_combo) < _single_as_combination_rank(single)
        else:
            split_wins = best_priced_combo.total_cost <= single.total_cost * (1 - saving_threshold)
        if split_wins:
            winner_combo, outcome = best_priced_combo, "COST_SAVING_SPLIT"
            saving = (single.total_cost - best_priced_combo.total_cost) / single.total_cost * 100
            summary = (
                f"Cost-Saving Split {_legs_text(best_priced_combo.legs)} = {best_priced_combo.total_cost} INR, "
                f"arriving by {best_priced_combo.latest_arrival.isoformat()}. It saves {saving:.2f}% against the best "
                f"priced single supplier, {single.supplier_name} {single.order_quantity} = {single.total_cost} INR "
                + (f"(threshold {saving_threshold * 100:.2f}%)." if saving_threshold is not None
                   else "(the threshold is not re-checked on reallocation).")
            )
        else:
            outcome = "SINGLE"
            summary = (
                f"{single.supplier_name} is the lowest-cost priced supplier that can deliver {single.order_quantity} "
                f"by {required_date.isoformat()}: {single.order_quantity} x {single.unit_price} = "
                f"{single.total_cost} INR, arriving {single.arrival.isoformat()}."
            )
            if best_priced_combo is not None:
                summary += (f" The best priced split, {_legs_text(best_priced_combo.legs)} = "
                            f"{best_priced_combo.total_cost} INR, " + (
                                f"does not save at least {saving_threshold * 100:.2f}%." if saving_threshold is not None
                                else "ranks lower."))
    elif unpriced_singles:  # rule 2
        single, outcome = min(unpriced_singles, key=_fallback_rank), "SINGLE"
        summary = (
            f"No priced supplier can deliver {shortage} alone by {required_date.isoformat()}. {single.supplier_name} "
            f"is Not Registered (no valid Purchasing Contract) but arrives earliest, on {single.arrival.isoformat()}, "
            f"and can deliver {single.order_quantity}: cost ranking unavailable."
        )
    elif best_priced_combo is not None:  # rule 3, fully priced
        winner_combo, outcome = best_priced_combo, "NECESSARY_SPLIT"
        summary = (
            f"No single supplier can deliver {shortage} by {required_date.isoformat()}. Necessary Split "
            f"{_legs_text(winner_combo.legs)} is the lowest-cost priced combination: {winner_combo.total_cost} INR, "
            f"arriving by {winner_combo.latest_arrival.isoformat()}."
        )
    elif best_unpriced_combo is not None:  # rule 3, with an unpriced supplier
        winner_combo, outcome = best_unpriced_combo, "NECESSARY_SPLIT"
        summary = (
            f"No single supplier and no fully priced combination can deliver {shortage} by "
            f"{required_date.isoformat()}. Necessary Split {_legs_text(winner_combo.legs)} arrives earliest, by "
            f"{winner_combo.latest_arrival.isoformat()}, and includes a Not Registered supplier: cost ranking "
            f"unavailable."
        )
    else:  # rule 4
        constrained = sum((o.available_qty for o in usable), Decimal(0))
        return Selection(
            "FAILED", [], considered, combos,
            f"No supplier or combination of suppliers can deliver {shortage} by {required_date.isoformat()}. "
            f"Constrained Quantity: {constrained}.",
            constrained_quantity=constrained,
        )

    legs = list(winner_combo.legs) if winner_combo else [_single_leg(single)]
    selected = {leg.supplier_id for leg in legs}
    best_priced_single = min(priced_singles, key=_single_rank, default=None)
    options_judged = [replace(o, reason=_option_reason(o, outcome, selected, single)) for o in considered]
    combos_judged = [replace(c, reason=_combination_reason(c, winner_combo, best_priced_single, saving_threshold))
                     for c in combos]
    cost_ranking_available = all(leg.unit_price is not None for leg in legs)
    return Selection(outcome, legs, options_judged, combos_judged, summary, cost_ranking_available,
                     best_priced_single=best_priced_single)


def _option_reason(option: ConsideredOption, outcome: Outcome, selected: set[uuid.UUID],
                   best_single: ConsideredOption | None) -> str:
    """Why a single option won or lost. Unusable options and those that can't cover alone keep their reason.
    `best_single` is the best covering single (priced, else the fallback); None for a Necessary Split."""
    if option.supplier_id in selected:
        return "selected"
    if option.reason:
        return option.reason
    if option.price_kind != "PRICED":
        # A priced choice always beats a covering unpriced supplier; otherwise it lost the fallback ranking.
        return "not_registered" if best_single.price_kind == "PRICED" else "outranked"
    if outcome == "COST_SAVING_SPLIT":
        return "cost_saving_split_cheaper"
    return "higher_cost" if option.total_cost > best_single.total_cost else "outranked"  # equal cost: a tie-break


def _combination_reason(c: ConsideredCombination, winner: ConsideredCombination | None,
                        best_priced_single: ConsideredOption | None, saving_threshold: Decimal | None) -> str:
    if c.reason:  # infeasible
        return c.reason
    if winner is None:  # a single supplier won
        if best_priced_single is None:
            return "single_covers"  # §6.4 rule 2: an unpriced single that covers beats any split
        if not c.fully_priced:
            return "not_registered"
        if saving_threshold is not None:
            return "saving_below_threshold"
        return "higher_cost" if c.total_cost > best_priced_single.total_cost else "outranked"  # reallocation
    if c is winner:
        return "selected"
    if not c.fully_priced and winner.fully_priced:
        return "not_registered"
    if c.fully_priced and c.total_cost > winner.total_cost:
        return "higher_cost"
    return "outranked"
