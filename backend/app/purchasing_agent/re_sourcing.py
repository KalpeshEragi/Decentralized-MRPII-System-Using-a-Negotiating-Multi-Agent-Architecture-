"""Re-sourcing (dev_docs/purchasing_agent/purchasing_agent_architecture.md §7.4.1, ADR-003): when the open Legs can no
longer cover the shortage, every eligible supplier of the item is a candidate, not just the selected ones.

This module finds the candidates besides the open Legs and records the RE_SOURCING audit; `negotiation.py` decides when
to re-source and applies the result.
- Excluded: a supplier with a FAILED Leg in this request (`failed_in_request`), or none of its per-request round budget
  left (`no_rounds_left`; the budget is the max rounds, shared across all its sessions for the request, never reset).
- A returning supplier (dropped `no_longer_needed` earlier) is limited by its remembered terms: its latest cap limits
  its availability, and it arrives no earlier than its latest stated delivery date. They are not a commitment: it gets
  a fresh offer.
- Every other check is the selection rules' (`selection.py`): active, no contract overlap, on time, availability ≥ MOQ.
- New and returning suppliers are priced at the current contract; open Legs keep their snapshot. Both are audited.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.negotiation_engine import service as negotiation_engine
from app.purchasing_agent import messages
from app.purchasing_agent.availability import Availability
from app.purchasing_agent.models import (DecisionAudit, LegReason, LegStatus, ProcurementRequest,
                                         PurchaseRequisition)
from app.purchasing_agent.selection import PriceState, Selection, SupplierOption
from app.purchasing_agent.service import audit_record, contract_prices
from app.supplier_service.service import SupplierItemRecord


@dataclass(frozen=True)
class Candidate:
    """A supplier without an open Leg that re-sourcing may add."""

    option: SupplierOption
    rounds_left: int  # of its per-request budget: the new session's max rounds
    returning: bool  # it was dropped `no_longer_needed` earlier in this request
    quantity_cap: Decimal | None  # remembered; kept on its new Leg
    remembered_date: date | None


@dataclass(frozen=True)
class Candidates:
    candidates: list[Candidate]
    excluded: dict[uuid.UUID, str]  # supplier → reason
    prices: dict[uuid.UUID, PriceState]  # every supplier's current contract price

    def by_supplier(self, supplier_id: uuid.UUID) -> Candidate:
        return next(c for c in self.candidates if c.option.supplier_id == supplier_id)


def candidate_option(supplier: SupplierItemRecord, effective: Decimal, price: PriceState, today: date,
                     quantity_cap: Decimal | None, remembered_date: date | None) -> SupplierOption:
    """Pure. A supplier without an open Leg as re-sourcing sees it: its current price, its effective availability
    limited by its remembered cap, and arriving on today + lead time or its remembered date, whichever is later."""
    arrival = today + timedelta(days=supplier.lead_time_days)
    if remembered_date is not None and remembered_date > arrival:
        arrival = remembered_date
    return SupplierOption(
        supplier_id=supplier.supplier_id, supplier_name=supplier.supplier_name, is_active=supplier.supplier_is_active,
        lead_time_days=(arrival - today).days, min_order_qty=supplier.min_order_qty,
        available_qty=effective if quantity_cap is None else min(effective, quantity_cap), price=price,
    )


def candidates(db: Session, request: ProcurementRequest, open_legs: list[PurchaseRequisition],
               availability: dict[uuid.UUID, Availability], today: date, max_rounds: int) -> Candidates:
    """Every supplier of the item without an open Leg, as a candidate or excluded with its reason."""
    open_suppliers = {leg.supplier_id for leg in open_legs}
    past = list(db.scalars(select(PurchaseRequisition)
                           .where(PurchaseRequisition.procurement_request_id == request.id,
                                  PurchaseRequisition.status.not_in(LegStatus.OPEN))
                           .order_by(PurchaseRequisition.created_at, PurchaseRequisition.id)))
    prices = contract_prices(db, request.item_id, today)
    found, excluded = [], {}
    for supplier_id, a in availability.items():
        if supplier_id in open_suppliers:
            continue
        history = [leg for leg in past if leg.supplier_id == supplier_id]
        if any(leg.status == LegStatus.FAILED for leg in history):
            excluded[supplier_id] = "failed_in_request"
            continue
        sessions = [leg.negotiation_session_id for leg in history]
        rounds_left = max_rounds - sum(negotiation_engine.session_state(db, s).round_count for s in sessions)
        if rounds_left <= 0:
            excluded[supplier_id] = "no_rounds_left"
            continue
        cap = history[-1].quantity_cap if history else None
        stated = [date.fromisoformat(o.terms["delivery_date"]) for s in sessions
                  for o in negotiation_engine.respondent_counter_offers(db, s) if o.terms.get("delivery_date")]
        remembered_date = stated[-1] if stated else None
        option = candidate_option(a.supplier, a.effective, prices[supplier_id], today, cap, remembered_date)
        returning = any(leg.status_reason == LegReason.NO_LONGER_NEEDED for leg in history)
        found.append(Candidate(option, rounds_left, returning, cap, remembered_date))
    return Candidates(found, excluded, prices)


def audit(db: Session, request: ProcurementRequest, trigger: PurchaseRequisition, open_legs: list[PurchaseRequisition],
          selected: list[SupplierOption], found: Candidates, result: Selection, names: dict[uuid.UUID, str],
          threshold: Decimal, changes: dict, summary: str) -> None:
    """The RE_SOURCING audit: every candidate (open Legs with their snapshot and current price, new and returning
    suppliers with their current price and remembered terms), the exclusions, every option and combination, and what
    the result changes."""
    def price(state: PriceState) -> str | None:
        return str(state.unit_price) if state.unit_price is not None else None

    rounds = {leg.supplier_id: negotiation_engine.session_state(db, leg.negotiation_session_id).rounds_left
              for leg in open_legs}
    candidate_records = [
        {"supplier_name": names.get(leg.supplier_id), "source": "open_leg", "status": leg.status,
         "allocated_quantity": messages.quantity_text(leg.allocated_quantity),
         "quantity_cap": messages.quantity_text(leg.quantity_cap) if leg.quantity_cap is not None else None,
         "unit_price_at_selection": str(leg.unit_price_at_selection) if leg.unit_price_at_selection is not None
         else None,
         "current_unit_price": price(found.prices[leg.supplier_id]), "rounds_left": rounds[leg.supplier_id]}
        for leg in open_legs
    ] + [
        {"supplier_name": c.option.supplier_name, "source": "returning" if c.returning else "new",
         "current_unit_price": price(c.option.price), "rounds_left": c.rounds_left,
         "remembered_cap": messages.quantity_text(c.quantity_cap) if c.quantity_cap is not None else None,
         "remembered_date": c.remembered_date.isoformat() if c.remembered_date else None}
        for c in found.candidates
    ]
    reference = result.best_priced_single
    saving = None
    if reference is not None and result.total_cost is not None and result.outcome != "SINGLE":
        saving = ((reference.total_cost - result.total_cost) / reference.total_cost * 100).quantize(Decimal("0.01"))
    db.add(DecisionAudit(
        procurement_request_id=request.id, decision_type="RE_SOURCING",
        context=audit_record({
            "trigger_leg_id": trigger.id,
            "supplier_id": trigger.supplier_id,
            "trigger": trigger.status_reason if trigger.status == LegStatus.FAILED else "quantity_counter",
            "allocation_before": {names.get(leg.supplier_id): messages.quantity_text(leg.allocated_quantity)
                                  for leg in open_legs},
            "saving_threshold": threshold,
            "candidates": candidate_records,
            "excluded": {names.get(supplier_id): reason for supplier_id, reason in found.excluded.items()},
            "selected_suppliers": selected,  # available_qty: effective availability limited by the cap
            "options": result.options,
            "combinations": result.combinations,
        }),
        decision=audit_record({
            "outcome": result.outcome,
            "legs": result.legs,
            "total_cost": result.total_cost,
            "cost_ranking_available": result.cost_ranking_available,
            "constrained_quantity": result.constrained_quantity,
            "best_priced_single": ({"supplier_name": reference.supplier_name, "total_cost": reference.total_cost}
                                   if reference else None),
            "saving_percent": saving,
            **changes,
        }),
        reasoning_summary=summary,
    ))
