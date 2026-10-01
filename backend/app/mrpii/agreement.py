"""Deterministic agreement validation (C4 section 8: deterministic validation is the authority on feasibility).

Minimal check on the agreed terms against the shortage they resolve: enough quantity, delivered by the required date.
Supplier bounds (MOQ, available quantity) are checked with `mrpii/suppliers.py`; this module does not pick suppliers.
"""

from app.schemas.domain import Shortage
from app.schemas.negotiation import OfferTerms


def check_agreement(terms: OfferTerms, shortage: Shortage) -> list[str]:
    """Return the reasons the terms do not resolve the shortage; an empty list means feasible."""
    problems = []
    if terms.quantity < shortage.shortage_quantity:
        problems.append(f"quantity {terms.quantity} is below the shortage {shortage.shortage_quantity}")
    if terms.delivery_date is None or terms.delivery_date > shortage.required_by:
        problems.append(f"delivery_date {terms.delivery_date} is after required_by {shortage.required_by}")
    return problems
