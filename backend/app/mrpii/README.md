# backend/app/mrpii

Pure deterministic MRPII core (Phase 1). No database, LLM, clock or network access; "today" is passed in.

| File | Purpose |
| --- | --- |
| `scheduling.py` | `backward_schedule`: `planned_end = due_date`, `planned_start = due_date - production_lead_time_days`. |
| `mps.py` | `net_finished_goods`: `net_production_requirement = max(0, order_quantity - available_finished_goods)`. `create_mps`: one `MPSEntry` per order line with a net requirement > 0 (`planned_quantity` = that net quantity), with `order_id` and the order's priority. |
| `mrp.py` | `explode_bom` (single level), `run_mrp` (time-phased netting with scheduled receipts), `find_shortages`. |
| `capacity.py` | `check_capacity`: feasible iff `ceil(planned_quantity / capacity_per_day) <= production_lead_time_days`. |
| `validator.py` | `validate_plan`: returns a `PlanValidationResult` (violations are results, not errors). |
| `suppliers.py` | Supplier feasibility from the X1 fixture rule (`is_usable`, `covers_alone`, `is_split_feasible`). Data only; choosing a supplier is Purchasing's decision. |
| `plan.py` | `plan_order`: order → finished-goods netting → MPS → capacity → BOM → MRP → shortages → validation, returned as a `PlanSnapshot`. `finished_goods` (finished-product positions) is separate from `inventory` (components). Omitted finished goods means the full order is produced. |

Netting order across several MPS entries (ascending `required_by`, priority, order number) is the proposal in C1 §3.7.
`CapacityCheck` has two additions to the C1 example (`mps_entry_id`, `required_days`) and `PlanSnapshot` has `capacity_checks`.
`test_mps.py` is an empty placeholder from Phase 0.
