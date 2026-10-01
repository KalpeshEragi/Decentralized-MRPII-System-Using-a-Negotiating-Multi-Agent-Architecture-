# backend/app/schemas

Shared Pydantic shapes (frozen, unknown fields rejected, no cost/price fields).

| File | Purpose |
| --- | --- |
| `domain.py` | C1 shapes: items, BOM, orders, inventory (`available_quantity = max(0, on_hand - reserved - safety_stock)`), receipts, MPS, MRP rows, shortages, capacity, plan validation, `PlanSnapshot`; plus `ProductionParameters` and `SupplierOption` fixture data. |
| `negotiation.py` | C4 shapes: `NegotiationMessage` envelope, `OfferTerms`, `MessageType`, `SessionStatus`, `MAX_ROUNDS`. `OfferTerms` is fixed to `quantity`, `required_date`, `delivery_date`, `priority`. |

`inventory.py`, `planning.py`, `production.py`, `simulation.py` are empty Phase 0 placeholders.
