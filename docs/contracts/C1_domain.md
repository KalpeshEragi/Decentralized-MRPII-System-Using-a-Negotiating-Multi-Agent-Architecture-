# C1 — Domain Data Shapes and Enums

**Status:** CONFIRMED (2026-09-30) · open items stay **PENDING**
**Implemented in (Phase 1):** `backend/app/schemas/domain.py` (Pydantic), used by `backend/app/mrpii/`.

This contract defines the in-memory shapes that the deterministic MRPII core consumes and
produces: order, BOM line, inventory position, scheduled receipt, MPS entry, material
requirement, shortage, capacity check and plan validation result.
It does **not** define database tables (C2), negotiation messages or offer terms (C4),
API request/response models (C5), agent state (C6) or approval state (C8).

Items marked **PENDING** must not be guessed during implementation. See
`docs/DECISIONS.md` for each referenced item (`P0-xx`, `P1-xx`).

---

## 1. Conventions

| Topic | Rule |
| --- | --- |
| IDs | UUID strings. |
| Quantities | Decimal, never float. Serialized in JSON as numbers. Always `>= 0`. The unit is the item's `unit`. |
| Dates | ISO-8601 `YYYY-MM-DD`. The MRP core plans in **day buckets** (P0-16). The database column mapping (`DATE` or midnight UTC `TIMESTAMP`) is chosen in C2. |
| Priority | Integer 1–5, `1` = highest (P0-15). |
| Cost / price | Not present in any shape. Out of scope for 25%. |
| Determinism | Same inputs → same outputs. No LLM, clock or database access inside the MRPII core; "today" is passed in as `planning_date`. |

## 2. Enums

| Enum | Values | Notes |
| --- | --- | --- |
| `ItemType` | `FINISHED_PRODUCT`, `COMPONENT`, `RAW_MATERIAL` | From `core.items.item_type`. |
| `OrderStatus` | `NEW`, `PLANNING`, `PLANNED` | Approval-related statuses (approved, rejected, human intervention) are **PENDING C8** (Phase 4). |
| `PlanStatus` | `DRAFT`, `SHORTAGE`, `VALIDATED`, `INVALID` | `DRAFT` = computed, not yet validated. `SHORTAGE` = at least one unresolved shortage. Approval states (`AWAITING_APPROVAL`, `APPROVED`, `REJECTED`, `SUPERSEDED`) are **PENDING C8 / D8**. |
| `RequirementStatus` | `COVERED`, `SHORTAGE`, `PROCUREMENT_AGREED`, `PROCUREMENT_FAILED` | The last two record the negotiation result (agreement or `FAILED`, C4). After `FAILED` the requirement stays unresolved. |
| `ViolationCode` | see §3.9 | |

## 3. Shapes

### 3.1 Item

```json
{
  "id": "6f1c0e2a-0000-4000-8000-000000000001",
  "sku": "COMP-A",
  "name": "Component A",
  "item_type": "COMPONENT",
  "unit": "pcs"
}
```

### 3.2 BOMLine

Single-level BOM (P1-02, confirmed). One line per component of a finished product; components have no BOM of their own.

```json
{
  "parent_item_id": "6f1c0e2a-0000-4000-8000-000000000010",
  "component_item_id": "6f1c0e2a-0000-4000-8000-000000000001",
  "quantity_per": 2
}
```

Invariant: `quantity_per > 0`. Only the active BOM version is passed to the core.

### 3.3 CustomerOrder

```json
{
  "id": "6f1c0e2a-0000-4000-8000-000000000100",
  "order_number": "SO-0001",
  "customer_id": "6f1c0e2a-0000-4000-8000-000000000200",
  "order_date": "2026-10-01",
  "due_date": "2026-10-31",
  "priority": 1,
  "status": "NEW",
  "lines": [
    { "item_id": "6f1c0e2a-0000-4000-8000-000000000010", "quantity": 100 }
  ]
}
```

Invariants: `due_date >= order_date`; every line `quantity > 0`; line items are `FINISHED_PRODUCT`.

### 3.4 InventoryPosition

Provided by the inventory service (never computed by an LLM). Input to MRP.

```json
{
  "item_id": "6f1c0e2a-0000-4000-8000-000000000001",
  "on_hand": 180,
  "reserved": 40,
  "safety_stock": 40,
  "available_quantity": 100
}
```

Rule (finalized, `DECISIONS.md`): `available_quantity = max(0, on_hand - reserved - safety_stock)`.
Incoming stock is **never** part of `available_quantity`.
**PENDING P0-10 (D1)**: one position per item aggregated across warehouses, or per warehouse.

### 3.5 ScheduledReceipt

Incoming material that is committed but not yet on hand. Used only for projected availability.

```json
{
  "item_id": "6f1c0e2a-0000-4000-8000-000000000001",
  "quantity": 50,
  "expected_date": "2026-10-20",
  "source_ref": "6f1c0e2a-0000-4000-8000-000000000300"
}
```

Source (P0-12): committed negotiation agreements (agreed quantity and delivery date);
`source_ref` is the agreement ID. Purchase orders are out of scope. The read path is defined in C2/C4.

### 3.5a FinishedGoodsNetting

Planning order (P1-09): **customer order → finished-goods netting → MPS → capacity → BOM → MRP**. Finished goods are the
`InventoryPosition` of the finished product, with the same rule `available_finished_goods = max(0, on_hand - reserved - safety_stock)`.
Component inventory is not used here; it is used later by MRP.

```json
{
  "order_id": "6f1c0e2a-0000-4000-8000-000000000100",
  "item_id": "6f1c0e2a-0000-4000-8000-000000000010",
  "order_quantity": 100,
  "available_finished_goods": 50,
  "net_production_requirement": 50
}
```

`net_production_requirement = max(0, order_quantity - available_finished_goods)`. One row per order line.
Lines of the same item in one order share the available finished goods in line order. One order is netted at a time;
finished goods are not allocated across orders in the 25% (P1-09).

### 3.6 MPSEntry

```json
{
  "id": "6f1c0e2a-0000-4000-8000-000000000400",
  "order_id": "6f1c0e2a-0000-4000-8000-000000000100",
  "item_id": "6f1c0e2a-0000-4000-8000-000000000010",
  "planned_quantity": 100,
  "planned_start": "2026-10-25",
  "planned_end": "2026-10-31",
  "priority": 1
}
```

Rules:
- One entry per order line **with `net_production_requirement > 0`** (order traceability via `order_id`). Entries are not
  merged across orders. `planned_quantity = net_production_requirement`, so it can be lower than the order line quantity.
- A line fully covered by finished goods gets **no** MPS entry, no capacity check and no MRP rows. If every line is
  covered, the plan has no MPS or requirements and is `VALIDATED` (P1-09).
- Backward scheduling: `planned_end = order.due_date`; `priority` is copied from the order.
- `planned_start = planned_end - production lead time`. The production lead time is a per-product
  value (P0-11); its storage is chosen in C2 and its value comes from the D1 fixture (**PENDING D1**).

### 3.7 MaterialRequirement (one MRP row)

```json
{
  "mps_entry_id": "6f1c0e2a-0000-4000-8000-000000000400",
  "item_id": "6f1c0e2a-0000-4000-8000-000000000001",
  "gross_requirement": 200,
  "available_quantity": 100,
  "scheduled_receipts": 50,
  "projected_available_quantity": 150,
  "net_requirement": 50,
  "required_by": "2026-10-25",
  "status": "SHORTAGE"
}
```

Calculation (deterministic):

```
gross_requirement            = mps.planned_quantity * bom_line.quantity_per
required_by                  = mps.planned_start
scheduled_receipts           = sum(receipt.quantity for receipts of this item
                                   with expected_date <= required_by, not yet consumed)
projected_available_quantity = available_quantity (still unconsumed) + scheduled_receipts
net_requirement              = max(0, gross_requirement - projected_available_quantity)
status                       = SHORTAGE if net_requirement > 0 else COVERED
```

Time-phased netting across several MPS entries needing the same item: entries are processed
in ascending `required_by`, then priority, then `order_number`; each entry consumes available
and projected quantity before the next. **Proposed**, to be confirmed in review.

`available_quantity` here is the per-row value the MRP used (maps to the schema column
`planning.mrp_requirements.available_inventory`). `scheduled_receipts` and
`projected_available_quantity` map to the columns of the same name (P0-13).

### 3.8 Shortage

Derived from every requirement with `net_requirement > 0`. It is the deterministic basis of the
shortage context that later travels in negotiation (the message content itself is C4 / Phase 3).

```json
{
  "item_id": "6f1c0e2a-0000-4000-8000-000000000001",
  "order_id": "6f1c0e2a-0000-4000-8000-000000000100",
  "mps_entry_id": "6f1c0e2a-0000-4000-8000-000000000400",
  "shortage_quantity": 50,
  "required_by": "2026-10-25",
  "priority": 1,
  "available_quantity": 100,
  "projected_available_quantity": 150
}
```

`shortage_quantity == net_requirement`. These fields cover the finalized negotiation factors
that the domain owns: quantity, required date, inventory impact, production priority.
Delivery date / lead time come from supplier data and offers (C3, C4).

### 3.9 CapacityCheck (minimal)

In scope (P1-03, confirmed). `capacity_per_day` is one value per product from the fixture/config, with no
`production.*` tables (P0-14). No scheduling or optimization.

```
working_days     = production lead time in calendar days (planned_start → planned_end)
required_days    = ceil(required_quantity / capacity_per_day)   # required_quantity = MPS planned_quantity (net)
max_quantity     = capacity_per_day * working_days
feasible         = required_days <= working_days   # equivalent to required_quantity <= max_quantity
```

```json
{
  "mps_entry_id": "6f1c0e2a-0000-4000-8000-000000000400",
  "item_id": "6f1c0e2a-0000-4000-8000-000000000010",
  "required_quantity": 100,
  "capacity_per_day": 20,
  "required_days": 5,
  "working_days": 6,
  "max_quantity": 120,
  "feasible": true
}
```

### 3.10 PlanValidationResult

Output of the deterministic plan validator. A failed validation is a **normal result**, not an error (see C5).

```json
{
  "valid": false,
  "violations": [
    {
      "code": "SHORTAGE_UNRESOLVED",
      "message": "Component A short by 50 for SO-0001",
      "item_id": "6f1c0e2a-0000-4000-8000-000000000001",
      "details": { "shortage_quantity": 50, "required_by": "2026-10-25" }
    }
  ]
}
```

| `ViolationCode` | Meaning |
| --- | --- |
| `SHORTAGE_UNRESOLVED` | A requirement still has `net_requirement > 0` (including after `FAILED`). |
| `RECEIPT_AFTER_REQUIRED_DATE` | Material relied on arrives after its `required_by`. |
| `DUE_DATE_MISSED` | `planned_end` is after the order `due_date`. |
| `OVER_ALLOCATION` | Plan consumes more than `available_quantity` + eligible receipts. |
| `SAFETY_STOCK_VIOLATION` | Plan would consume safety stock. |
| `INVALID_QUANTITY` | A quantity is negative or zero where positive is required. |
| `CAPACITY_EXCEEDED` | An MPS entry's `planned_quantity` exceeds its `CapacityCheck.max_quantity` (§3.9). |

### 3.11 PlanSnapshot

The aggregate the MRPII core returns for one order.

```json
{
  "order_id": "6f1c0e2a-0000-4000-8000-000000000100",
  "planning_date": "2026-10-01",
  "status": "SHORTAGE",
  "finished_goods": ["<FinishedGoodsNetting>"],
  "mps": ["<MPSEntry>"],
  "requirements": ["<MaterialRequirement>"],
  "shortages": ["<Shortage>"],
  "capacity_checks": ["<CapacityCheck>"],
  "validation": "<PlanValidationResult>"
}
```

Persistence of a plan record, plan versions and the planning-attempt counter are **PENDING C2 / C8**.

## 4. Illustrative example (NOT the D1 fixture)

Values are illustrative only (the inventory numbers are from `agent_operations.md`).
The real SmartPhone X1 fixture is **PENDING D1 / P0-10**.

- Order: 100 × product P, due 2026-10-31. BOM: P needs 2 × Component A.
- Component A: on_hand 180, reserved 40, safety_stock 40 → `available_quantity = 100`.
- Scheduled receipt: 50 × A on 2026-10-20. MPS `planned_start` 2026-10-25 (lead time illustrative).
- MRP: gross 200, projected available 150, net 50 → one `Shortage` of 50 A by 2026-10-25.

## 5. Open items affecting C1

Still open: D1 fixture values and warehouse aggregation (P0-10 / P1-01),
C2 storage choices for P0-11 and P0-16, C8 approval states.
Confirmed and applied here: P0-11, P0-12, P0-13, P0-14, P0-15, P0-16, P1-02 (single-level BOM), P1-03 (capacity check)
(see `docs/DECISIONS.md`).
