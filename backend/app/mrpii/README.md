# backend/app/mrpii

Pure deterministic MRPII core. No database, LLM, clock or network access; "today" is passed in.

## Six-agent design (step 2)

| File | Purpose |
| --- | --- |
| `multilevel.py` | Multi-level MRP (RD-1, quantity_accounting.md §6): `low_level_codes` (rejects BOM loops), `apply_lot_rule` (lot-for-lot, multiple, minimum), `run_mrp` (level by level, PAB with safety stock, lead-time offset for bought items, capacity-based start for made items through a `production_start` callback) → planned orders + per-item records. |
| `hours.py` | Hours per day (RD-2, QA-5): rounding (0.25 h up, space up), `machine_hours` / `worker_hours` of a routing step, `fits_every_day` (the owners' capacity rule), `schedule_backward` (steps placed backward using the smaller of free machine-hours and free worker-hours / crew). |
| `atp.py` | Available-to-promise (QA-4): `available_now`, `atp` (min over later days), `earliest_full_date` (IF-1), `uncovered_promises` (due-day walk, §5.3). |
| `ranking.py` | Planning's fixed ranking (PL-6): `Alternative`, `rank` (filters + ordered keys + tie by key), `check_ai_choice`. |

**Tests:** `backend/tests/mrpii/test_planning_calculations.py` (research phone example exact, ATP with a supplier delay, ranking).

## Old 25% modules (retired with the old agents in step 5)

The files below are the old single-level core, still used by the old agents and services.

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
