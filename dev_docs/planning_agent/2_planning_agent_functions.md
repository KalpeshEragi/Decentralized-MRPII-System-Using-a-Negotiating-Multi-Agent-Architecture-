# Planning Agent: Agent Design (Role, Rules, Methods, Functions)

**Status:** APPROVED by the developer (2026-10-17). Nothing new here is implemented.
**Related:** `1_planning_agent_high_level_architecture.md` (boundary, PL-1 to PL-4), `../architecture/negotiation.md`,
`../architecture/quantity_accounting.md`, `../DECISIONS.md`.

## 1. Role

The factory's planner. It turns a customer request into a feasible plan, asks the owners of stock, supply, space and
workers for what the plan needs, tells Sales what can honestly be offered, commits the plan when the customer confirms,
runs production orders, and repairs the plan when facts change.

## 2. Instructions (rules it must follow)

- Every quantity, date and capacity figure comes from deterministic code. Never estimate one.
- Ask the owner for anything that belongs to another agent; never change another agent's data.
- Send Sales only options that code has validated; mark options that are not held as "subject to re-check" (PL-1).
- Never change a RELEASED or STARTED production order automatically, or anything inside the time fence (RD-4).
- Change a FIRM order only through negotiation.
- Never reduce a customer's committed quantity or move a committed date on its own; that is the customer's decision
  through Sales.
- Ignore harmless changes (dampener, RD-8); never ignore a shortage or a broken due date.
- No price or cost.

## 3. Methods (what Planning does)

| # | Method | Deterministic or AI |
| --- | --- | --- |
| 1 | Plan a new request against the committed and held state (MPS → MRP level by level → capacity per day) | Code |
| 2 | Compute the options for Sales (REQUESTED, LATER_DATE, LESS_QUANTITY) | Code |
| 3 | Generate alternative ways to realize a target (for example: wait for supply, split supply, overtime, extra worker, use stock held for a later order through negotiation) | Code |
| 4 | Rank the alternatives and write the rationale | AI, validated by code; fixed ranking if the AI fails (§6) |
| 5 | Negotiate with owners (as starter) | Terms by code; wording by AI |
| 6 | Commit a confirmed order (execution policy, NG-4) | Code |
| 7 | Release, start and complete production orders | Code (shop-floor adapter input) |
| 8 | React to fact changes: find affected orders (pegs), apply dampener and time fence, replan | Code, with method 3–4 for the repair |

## 4. Functions

Planning's AI requests **no tools** (PL-5). Code prepares everything the AI needs. The functions below are run by the
Planning manager, never by the AI.

### 4.1 Calculation (pure, no database; extends `backend/app/mrpii/`)

| Function | Input | Output |
| --- | --- | --- |
| `net_finished_goods` | Order, finished-goods ATP | Quantity to produce |
| `explode_and_net` | Planned parent orders, BOM, item records (stock, receipts, safety stock, lot rule, lead time) | Planned orders per item and level, with pegs |
| `load_per_day` | Planned production orders, routings, work-center calendars | Machine-hours and worker-hours needed per day |
| `schedule` | Loads, free machine-hours, free worker-hours | Days per production step, or "does not fit" |
| `compute_options` | Request, plan results, owners' read data | REQUESTED / LATER_DATE / LESS_QUANTITY candidates |
| `generate_alternatives` | A target (quantity, date) and the current facts | Alternatives with their facts (§6.1) |
| `rank_alternatives` | Alternatives | Ordered list with the value of every criterion (§6) |
| `find_affected` | A changed fact (item, date, quantity) | Orders reached through the pegs |

### 4.2 Read functions Planning uses (other agents)

`atp_by_date` (Inventory), `supplier_options` (Purchasing: lead time, multiple, minimum, capacity), `free_space` /
`free_receiving` (Warehouse), `free_worker_hours` (HR, per skill and day).

### 4.3 Actions (write; always through rules and the outbox)

| Action | Effect |
| --- | --- |
| `open_negotiation` | One session per owner and resource for a case (starter role) |
| `answer_negotiation` | Accept / counter / reject / commit / abort, with code-computed terms |
| `send_result_to_sales` | Planning result through Sales door 3 |
| `commit_order` | Execution-policy check, then `COMMIT` to all linked sessions |
| `save_plan` | Planned / firm production orders, procurement requests, pegs (own schema) |
| `release_production_order` | FIRM → RELEASED (setting: 1 day before start) |
| `record_shop_floor_report` | RELEASED → STARTED, quantity completed, COMPLETED |
| `publish` | Plan and production events (`1_planning_agent_high_level_architecture.md` §7) |

### 4.4 Read functions Planning offers

`get_order_plan` (status, dates, quantities per order), `get_production_orders`, `get_pegging_for_order`.

## 5. The two control steps (AI)

| Step | Does | Input | Output |
| --- | --- | --- | --- |
| `ai_rank_alternatives` | Ranks the alternatives and explains the choice | Target, alternatives with all criterion values, the agent's goal | Fixed format: chosen alternative key, ranking, short rationale, negotiation wording |
| `check_ai_ranking` | Code checks the answer | AI answer + alternatives | Right format? Chosen key exists? It passed filters 1–2 (§6)? Any number in the wording not taken from the alternative? OK → use; otherwise ask once more, then use the fixed ranking |

## 6. Alternative evaluation and fixed ranking (PL-6)

Used whenever Planning must choose how to reach a target: for a new request (target = requested date and quantity)
and when repairing an existing order (target = committed date and quantity).

### 6.1 What an alternative contains

Generated by code only: the steps (which owners, which resources, which days), the resulting completion date and
quantity, and these criterion values:

| Value | Meaning |
| --- | --- |
| `hard_ok` | All hard constraints hold against current facts |
| `touches_protected` | Changes a RELEASED/STARTED order, something inside the time fence, or another order's committed date or quantity |
| `firm_changes` | Number of FIRM orders it needs to renegotiate |
| `full_on_target` | Full quantity on the target date (yes/no) |
| `days_late` | Days after the target date for the full quantity (0 if on time) |
| `orders_moved`, `days_moved` | Other orders whose plans move (through pegs), and the total days moved |
| `safety_stock_used` | Units of safety stock it needs (RD-6) |
| `extra_worker_hours` | Overtime or extra-shift hours |
| `negotiations` | Number of negotiations it needs |
| `completion_date` | Completion date of the full quantity |
| `key` | Fixed text built from the alternative's type and resource ids |

### 6.2 Ranking (in this exact order)

1. **Filter:** drop every alternative with `hard_ok = no` (re-checked against current facts just before ranking).
2. **Filter:** drop every alternative with `touches_protected = yes`. **Then rank** by `firm_changes`, fewest first.
3. **Meet the target:** `full_on_target = yes` first; then fewest `days_late`.
4. **Least disruption:** fewest `orders_moved`; then fewest `days_moved`.
5. **Fewest extra resources and negotiations:** fewest `safety_stock_used`; then fewest `extra_worker_hours`; then
   fewest `negotiations`.
6. **Earliest** `completion_date`.
7. **Tie:** alphabetical `key`, so the same state always gives the same choice.

Plain code (a sort by these keys), no AI call. The full table of values is stored in the audit record.

### 6.3 What the ranking can never do

- Choose an alternative that delivers **less** than the committed quantity. Such alternatives become customer options
  through Sales instead (LESS_QUANTITY).
- Change any number: it only orders the code-generated alternatives and copies their figures unchanged.
- Skip the owners: the chosen alternative still goes through negotiation and commit, and owners may refuse. Then the
  next alternative is tried (up to the re-pick limit).
- Empty list after filters 1–2 → no automatic choice: NOTHING_FEASIBLE for a new request, or escalation with a reason
  code for an existing order.

## 7. Inputs and outputs per task

| Task | Receives | Produces |
| --- | --- | --- |
| New request | Sales request (product, quantity, requested date, order date; no priority) | Planning result for Sales; held best option |
| Order confirmed | `OrderConfirmed` | `PlanCommitted` or `PlanCommitFailed`; FIRM production orders |
| Fact change | Subscribed event | `PlanRevised` / `PlanAtRisk`, or nothing (dampener) |
| Shop-floor report | Adapter input | Production order state change + event |
| Release time | Simulated clock reaches start − release lead | `ProductionOrderReleased` |

## 8. Settings (configurable factory settings, defaults)

| Setting | Default | Decision |
| --- | --- | --- |
| Hold validity / offer validity | 24 h | NG-2 |
| Release lead (FIRM → RELEASED before start) | 1 day | PL-7 |
| LATER_DATE search horizon | 60 days | PL-7 |
| Best-option re-picks after failed negotiations | 2 | PL-7 |
| Time fence | 2 days | RD-4 |
| Dampener | 1 day / 5 % | RD-8 |

## 9. Boundaries (must not do)

- Write stock, supplier, space or worker records.
- Talk to suppliers (only Purchasing does).
- Let the AI compute or change quantities, dates or capacity.
- Commit without the customer's confirmation and the execution policy.
- Change released/started orders automatically.
- Reduce committed quantities without the customer.

## 10. Decisions recorded

| ID | Decision |
| --- | --- |
| PL-5 | Planning's AI requests no tools; code prepares all alternatives and facts. |
| PL-6 | Fixed ranking when the AI fails or chooses invalidly (§6.2), in plain code; the AI may only choose among alternatives that pass filters 1–2. |
| PL-7 | Defaults: release lead 1 day, LATER_DATE horizon 60 days, 2 best-option re-picks; all configurable. |

## 11. Safeguards

- The AI never sees a way to write anything; its answer is a choice among keys plus text.
- Every date and number in AI wording must match the chosen alternative exactly (same check as Sales' reply checker).
- Re-check against current facts right before ranking and again by the owner at commit (stale facts are caught twice).
- Same state and same inputs → same ranking (repeatable tests).
- Test: a fake AI that picks a filtered-out alternative must be overruled by the fixed ranking.
