# SmartPhone X1 Fixture (X1-v2) — D1 / P0-10

**Status:** DRAFT · values and feasibility rule approved by the developer; written spec awaiting final developer review (ChatGPT advisory review optional)
**Resolves:** P0-10 (D1 fixture data). **Used by:** Phase 1 tests, Phase 2 seed loader, Phase 4+ scenario runs.

## 1. Purpose and scope

One deterministic, hand-calculable dataset for the SmartPhone X1 vertical slice. Values are chosen so
scenarios 1, 2, 3, 4, 6 and 7 of `dev_docs/implementation_25%/scenarios.md` yield their expected outcomes.
Scenario 5 (price increase) is future scope.

Constraints on this fixture:

- Single-level BOM (D2 recommendation). No price/cost fields anywhere.
- No Supplier Agent: supplier data is read through the supplier service/form only.
- Capacity is the existing minimal `capacity_per_day` check. No scheduling or optimization.
- Inventory is one aggregated position per item (one warehouse).
- Dates are day buckets (P0-16). Quantities are integers.

This document defines **data only**. It does not define schema, MRP code or negotiation behavior.
Agents decide which supplier to pick; the fixture only guarantees which options are feasible.

## 2. Order and planning parameters

| Field | Value |
| --- | --- |
| Order number | SO-0001 |
| Finished product | SmartPhone X1 |
| Quantity | 1,000 |
| Priority | 1 |
| `order_date` = `planning_date` | 2026-10-01 |
| `due_date` | 2026-10-31 (30 days) |
| `production_lead_time_days` | 5 (storage: fixture/config value or `core.items` column, decided in C2, P0-11) |
| `capacity_per_day` | 300 (P0-14) |

Derived: `planned_end = 2026-10-31`, `planned_start = 2026-10-26`, so every component has
`required_by = 2026-10-26` and `required_by - planning_date = 25 days`.

Capacity check (minimal): feasible if `ceil(quantity / capacity_per_day) <= production_lead_time_days`.
1,000 units → 4 days ≤ 5, feasible. 1,300 units → 5 days ≤ 5, feasible.

## 3. BOM (single level)

| Component | `quantity_per` |
| --- | --- |
| Display | 1 |
| Main Board | 1 |
| Battery | 1 |
| Camera Module | 2 |
| Speaker | 1 |
| Charging Port | 1 |

## 4. Inventory

`available_quantity = max(0, on_hand - reserved - safety_stock)` (C1 §3.4). No scheduled receipts at baseline.

| Component | on_hand | reserved | safety_stock | available |
| --- | --- | --- | --- | --- |
| Display | 650 | 50 | 100 | 500 |
| Main Board | 1200 | 100 | 100 | 1000 |
| Battery | 500 | 50 | 50 | 400 |
| Camera Module | 2800 | 200 | 100 | 2500 |
| Speaker | 1500 | 100 | 100 | 1300 |
| Charging Port | 1500 | 100 | 50 | 1350 |

## 5. Suppliers

Supplier data only: `lead_time_days`, `min_order_qty` (MOQ), `available_qty`. No price/cost.
"Arrival" = `planning_date + lead_time_days` at baseline.

| Component | Supplier | Lead (days) | MOQ | Available qty | Arrival |
| --- | --- | --- | --- | --- | --- |
| Display | Alpha Displays | 14 | 200 | 600 | 10-15 |
| Display | Beta Optics | 20 | 300 | 500 | 10-21 |
| Display | Gamma Screens | 28 | 100 | 1000 | 10-29 |
| Main Board | Nova Silicon | 18 | 100 | 400 | 10-19 |
| Main Board | Orbit Circuits | 10 | 200 | 300 | 10-11 |
| Main Board | Pixel Boards | 24 | 50 | 150 | 10-25 |
| Battery | Volt Power | 12 | 250 | 700 | 10-13 |
| Battery | Cell Works | 22 | 500 | 1000 | 10-23 |
| Camera Module | Lumen Optics | 15 | 200 | 500 | 10-16 |
| Camera Module | Focal Point | 8 | 100 | 150 | 10-09 |
| Speaker | Sonic Audio | 9 | 200 | 500 | 10-10 |
| Speaker | EchoTech | 16 | 50 | 150 | 10-17 |
| Charging Port | PlugCo | 7 | 100 | 1000 | 10-08 |
| Charging Port | ConnectRite | 21 | 300 | 500 | 10-22 |

### 5.1 Supplier feasibility rule

Let `R` = the shortage `required_by`, `Q` = the `shortage_quantity`, `planning_date` as in §2.

1. A supplier is **usable** only if both hold:
   1. `planning_date + lead_time_days <= required_by`
   2. `available_quantity >= MOQ`
2. A supplier **covers alone** only if it is usable and `available_quantity >= shortage_quantity`.
3. For **split procurement**, every participating supplier must individually be usable and satisfy
   its own bounds (`MOQ <= ordered quantity <= available_quantity`), and the combined ordered
   quantities must cover the shortage (`sum >= Q`).

Note: an ordered quantity is never below the supplier's MOQ, so it may exceed `Q`; the excess is surplus.
This rule is a fixture-level, deterministic feasibility check. Negotiation preferences (speed, surplus,
splitting) remain agent decisions.

## 6. Baseline (Scenario 1)

### 6.1 Expected MPS

| Order | Item | Planned qty | planned_start | planned_end | Priority |
| --- | --- | --- | --- | --- | --- |
| SO-0001 | SmartPhone X1 | 1,000 | 2026-10-26 | 2026-10-31 | 1 |

### 6.2 Expected MRP

| Component | Gross | Available | Scheduled receipts | Net | Status |
| --- | --- | --- | --- | --- | --- |
| Display | 1000 | 500 | 0 | **500** | SHORTAGE |
| Main Board | 1000 | 1000 | 0 | 0 | COVERED (exact; safety stock untouched) |
| Battery | 1000 | 400 | 0 | **600** | SHORTAGE |
| Camera Module | 2000 | 2500 | 0 | 0 | COVERED |
| Speaker | 1000 | 1300 | 0 | 0 | COVERED |
| Charging Port | 1000 | 1350 | 0 | 0 | COVERED |

Baseline shortages: Display 500, Battery 600, both required by 2026-10-26.

### 6.3 Feasible suppliers per shortage (`R` = 10-26)

| Shortage | Usable | Covers alone | Not usable |
| --- | --- | --- | --- |
| Display 500 | Alpha (10-15), Beta (10-21) | Alpha (avail 600), Beta (avail 500) | Gamma: arrives 10-29 > 10-26 |
| Battery 600 | Volt (10-13), Cell (10-23) | Volt (avail 700), Cell (avail 1000) | none |

Both shortages have two feasible suppliers, so supplier selection is meaningful.

## 7. Scenario changes

Each scenario is evaluated independently from the baseline above, against the untouched supplier table
(except for the stated change). Feasibility results therefore do not depend on which supplier an earlier
negotiation picked. If baseline agreements were already committed, they enter as scheduled receipts
(C1 §3.5) and only the residual shortage is procured.

### S2 — Battery supplier delay (Scenario 2)

Change: Volt Power `lead_time_days` 12 → 27 (arrival 10-28).

| Shortage | Usable | Covers alone | Not usable |
| --- | --- | --- | --- |
| Battery 600 | Cell (10-23) | Cell | Volt: 10-28 > 10-26 |

Outcome: the originally feasible Volt becomes unusable because of delivery. Cell is the only feasible
source (order 600, avail 1000). The plan stays feasible with a supplier switch. Display is unchanged from §6.3.

### S3 — Demand 1,000 → 1,300 (Scenario 3)

Change: order quantity 1,300. `planned_start`, `required_by` and due date are unchanged.
Capacity: 5 days ≤ 5, feasible.

| Component | Gross | Available | Net | Status |
| --- | --- | --- | --- | --- |
| Display | 1300 | 500 | **800** | SHORTAGE |
| Main Board | 1300 | 1000 | **300** | SHORTAGE |
| Battery | 1300 | 400 | **900** | SHORTAGE |
| Camera Module | 2600 | 2500 | **100** | SHORTAGE |
| Speaker | 1300 | 1300 | 0 | COVERED (exact) |
| Charging Port | 1300 | 1350 | 0 | COVERED |

| Shortage | Usable | Covers alone | Notes |
| --- | --- | --- | --- |
| Display 800 | Alpha (600), Beta (500) | none | Split required, e.g. Alpha 500 + Beta 300. Gamma unusable (late). |
| Main Board 300 | Nova (400), Orbit (300), Pixel (150) | Nova, Orbit (exact) | Pixel usable only in a split, e.g. Nova 150 + Pixel 150. |
| Battery 900 | Volt (700), Cell (1000) | Cell | Split possible, e.g. Volt 400 + Cell 500. |
| Camera 100 | Lumen (500), Focal (150) | Lumen (order ≥ 200, surplus ≥ 100), Focal | Both cover alone. |

If the baseline agreements (Display 500, Battery 600) are already committed as scheduled receipts, the
residual shortages are Display 300, Battery 300, Main Board 300, Camera 100.

### S4 — Display supplier quantity reduction (Scenario 4)

Change: **Alpha Displays' supplier `available_qty` 600 → 300.** This is a change to *supplier data* only.
**Display inventory is not changed** (on_hand 650, reserved 50, safety 100, available 500 stay as in §4),
so the Display shortage stays 500 and `required_by` stays 10-26.

| Shortage | Usable | Covers alone | Not usable |
| --- | --- | --- | --- |
| Display 500 | Alpha (avail 300 ≥ MOQ 200), Beta | Beta (500) | Gamma: late |

- Alpha is still usable but no longer covers alone (300 < 500): the originally feasible supplier fails on quantity.
- Feasible plans: Beta 500 alone; or split Alpha 200 + Beta 300 (exact); Alpha 300 + Beta 300 (surplus 100).
- Alpha 300 + Beta 200 is infeasible (Beta MOQ 300).

### S6 — Speaker inventory reservation change (Scenario 6)

Change: Speaker `reserved` 100 → 500. Available = 1500 − 500 − 100 = 900. Gross 1000 → net **100**, SHORTAGE.
This is an internal inventory-state change; suppliers are unchanged.

| Shortage | Usable | Covers alone | Notes |
| --- | --- | --- | --- |
| Speaker 100 | Sonic (10-10), EchoTech (10-17) | Sonic (order ≥ 200, surplus ≥ 100), EchoTech (order 100 or more) | Trade-off: speed vs. surplus. |

### S7 — Due date 30 → 20 days (Scenario 7)

Change: `due_date` 2026-10-21, so `planned_start = 2026-10-16` and `required_by = 2026-10-16`
(15 days from `planning_date`). Quantity 1,000, capacity check unchanged (4 days ≤ 5). Baseline shortages
(Display 500, Battery 600) are unchanged.

| Shortage | Usable | Covers alone | Not usable |
| --- | --- | --- | --- |
| Display 500 | Alpha (10-15) | Alpha | Beta (10-21), Gamma (10-29) |
| Battery 600 | Volt (10-13) | Volt | Cell (10-23) |

Outcome: feasible with a single source each. Combined with S2 (Volt delayed) no usable Battery supplier
remains, giving an unresolved shortage — a validated "cannot meet" case rather than an assumed success.

## 8. Not in this fixture

- Price/cost, supplier reliability scores, multiple warehouses, multi-level BOM, capacity beyond `capacity_per_day`.
- Any schema, MRP code, negotiation behavior or Supplier Agent.
