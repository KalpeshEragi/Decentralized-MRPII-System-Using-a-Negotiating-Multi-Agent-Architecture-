# Decentralized MRPII

Manufacturing planning where autonomous agents (Production Planning, Inventory, Purchasing) negotiate a mutually feasible plan instead of one central planner deciding it.

## Language

### Procurement

**Purchasing Contract**:
A standing agreement between Purchasing and one supplier for one item, holding the unit price. It exists before any shortage and is not negotiated in rounds.
_Avoid_: Price list, supplier contract, agreement

**Procurement Agreement**:
The negotiated result of one procurement negotiation for one shortage: the agreed quantity and delivery date.
_Avoid_: Contract, deal, purchase order

**Total Purchasing Cost**:
A supplier's contract unit price times the quantity actually ordered from it, so any surplus forced by the minimum order quantity counts as cost.
_Avoid_: Price, unit cost

**Not Registered**:
The price state of a supplier-item pair that has no Purchasing Contract. The price is unknown, never zero, and such a supplier cannot be ranked on cost.
_Avoid_: Free, zero price, no price

**Invalidated Agreement**:
A committed Procurement Agreement that a supplier disruption has made unreliable, so it no longer counts as a scheduled receipt.
_Avoid_: Cancelled agreement, rewritten agreement

### Split procurement

**Split Procurement**:
Covering one shortage with two suppliers at once, all-or-nothing: either every leg agrees or the whole shortage fails.
_Avoid_: Multi-sourcing, partial procurement

**Leg**:
One supplier's part of a Split Procurement, negotiated on its own with its own quantity and delivery date.
_Avoid_: Sub-order, portion

**Necessary Split**:
A Split Procurement used because no single supplier can meet the quantity and required date.

**Cost-Saving Split**:
A Split Procurement of two priced suppliers chosen because it costs at least 10% less than the cheapest feasible single supplier.

**Constrained Quantity**:
The part of a shortage that could have been covered when procurement fails, reported so the shortfall is explicit.
_Avoid_: Partial agreement
