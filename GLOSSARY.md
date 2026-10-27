# Decentralized MRPII

Manufacturing planning where autonomous domain agents negotiate a mutually feasible plan instead of one central planner deciding it.

## Language

### Procurement

**Procurement Request**:
What Purchasing is asked to cover: one item, a shortage quantity, a required date and a priority.
_Avoid_: Shortage message, purchase request

**Purchasing Contract**:
A standing agreement between Purchasing and one supplier for one item, holding the unit price for a validity period. At most one is active and valid for a supplier-item pair on any date. It exists before any shortage and is not negotiated in rounds.
_Avoid_: Price list, supplier contract, agreement

**Procurement Agreement**:
The combined result of one Procurement Request across all its Legs: who supplies what quantity by when. It is proposed only when every Leg has agreed, and committed only after approval.
_Avoid_: Contract, deal, purchase order

**Leg**:
One supplier's part of a procurement, negotiated on its own with its own quantity and delivery date. A single-supplier procurement has exactly one Leg.
_Avoid_: Sub-order, portion

**Leg Agreement**:
The quantity and delivery date one supplier agreed to for its Leg. It counts for nothing on its own until the whole Procurement Agreement is committed.
_Avoid_: Partial agreement

**Total Purchasing Cost**:
A supplier's contract unit price times the quantity actually ordered from it, so any surplus forced by the minimum order quantity counts as cost.
_Avoid_: Price, unit cost

**Effective Availability**:
What a supplier can still offer a Procurement Request for an item: its available quantity minus the Holds of other requests' Legs with it, never below zero. A request's own Legs never count against it.

**Hold** (Purchasing):
The supplier quantity a Leg reserves while it counts: its allocated quantity while pending, its agreed quantity once agreed or committed. Failed and aborted Legs hold nothing.
_Avoid_: Reservation (Inventory's term)

**Quantity Cap**:
The most a supplier will supply for one procurement, set when it counter-offers a different quantity. Reallocation and Re-sourcing never ask it for more; it is remembered if the supplier returns.

**Reallocation**:
Redistributing a procurement's quantities among the suppliers already selected for it, after a counteroffer.

**Re-sourcing**:
Extending a procurement in negotiation to every eligible supplier of the item, because the suppliers already selected can no longer cover the shortage.
_Avoid_: Reselection (selection is not restarted: open Legs keep their terms and price snapshots), replacement supplier

**Scheduled Receipt**:
A committed Leg of a committed Procurement Agreement: supplier, item, agreed quantity and agreed delivery date. An agreed but uncommitted Leg is never one.
_Avoid_: Free stock, remaining quantity

**Not Registered**:
The price state of a supplier-item pair with no active, currently valid Purchasing Contract. The price is unknown, never zero, and such a supplier cannot be ranked on cost.
_Avoid_: Free, zero price, no price

**Invalidated Agreement**:
A committed Procurement Agreement that a supplier disruption has made unreliable, so it no longer counts as a scheduled receipt. Future scope; not implemented.
_Avoid_: Cancelled agreement, rewritten agreement

### Split procurement

**Split Procurement**:
Covering one Procurement Request with more than one supplier at once, all-or-nothing: nothing is committed until every Leg of the final allocation agrees; if no feasible allocation remains, the whole procurement fails.
_Avoid_: Multi-sourcing, partial procurement

**Necessary Split**:
A Split Procurement used because no single supplier can meet the quantity and required date. It may include a Not Registered supplier (then cost ranking is unavailable).

**Cost-Saving Split**:
A Split Procurement of only priced suppliers, chosen because it costs at least 10% (a configurable threshold) less than the cheapest feasible priced single supplier.

**Constrained Quantity**:
The part of a shortage that the suppliers of the final allocation attempt could have covered by the required date when procurement fails, reported so the shortfall is explicit.
_Avoid_: Partial agreement

### Control panel

**City**:
The whole 3D world of the control panel, where every part of the system has its place.
_Avoid_: Map, scene, world

**District**:
One area of the City belonging to one part of the system, such as an agent's office, the factory or the customer neighbourhood.
_Avoid_: Site, zone, area

**Town Square**:
The City's central plaza, in the spirit of Times Square, where published events appear and the agents subscribed to them come to read them.
_Avoid_: Event board, hub
