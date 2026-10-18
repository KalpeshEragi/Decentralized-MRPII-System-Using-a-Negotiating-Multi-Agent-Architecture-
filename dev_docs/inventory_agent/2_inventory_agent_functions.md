# Inventory Agent: Agent Design (Role, Rules, Methods, Functions)

**Status:** APPROVED by the developer (2026-10-17). Nothing new here is implemented.
**Related:** `1_inventory_agent_high_level_architecture.md` (boundary, IN-1 to IN-4),
`../architecture/quantity_accounting.md` (formulas, ledger, invariants), `../architecture/negotiation.md`.

## 1. Role

The factory's stock keeper. It knows exactly how much of every item exists, is promised, is held and is coming in;
answers stock requests honestly; never promises the same stock twice; guards safety stock; and reports at once when
availability changes.

## 2. Instructions (rules it must follow)

- Every number comes from the ledger, the balance and the formulas in `quantity_accounting.md`.
- Never offer more than `ATP(needed_by)`; never let `on_hand` go below 0.
- Release safety stock only by the fixed rule (§5) and the configured limits.
- Never start a negotiation; report problems as events (IN-3).
- Never cancel or shrink a commitment on its own; mark it AT_RISK and report (IF-2).
- Change quantities only from its own decisions (holds, commits, releases) or from owners' physical facts (Warehouse
  events) and supply facts (Purchasing events).
- No price or cost.

## 3. Methods (all deterministic, IN-4)

| # | Method |
| --- | --- |
| 1 | Answer a stock request: OFFER, COUNTER_OFFER (IF-1) or REJECT, with a reason code |
| 2 | Place, commit, release and expire holds; turn holds into reservations |
| 3 | Apply order changes as deltas (QA-3) |
| 4 | Apply physical facts: receipt, issue to production, finished goods stored, shipment |
| 5 | Apply supply facts: incoming added, delayed, reduced |
| 6 | Find uncovered reservations after a supply change (due-date walk) and mark them AT_RISK; restore when covered again |
| 7 | Decide a safety-stock release (fixed rule) |
| 8 | Reconcile: recompute every balance from the ledger |

The AI only turns code-computed terms and reason codes into short negotiation wording (§6).

## 4. Functions

### 4.1 Calculation (pure, no database)

| Function | Input | Output |
| --- | --- | --- |
| `available_now` | Balance | `max(0, on_hand − reserved − held − safety_stock)` |
| `atp_by_date` | Balance, incoming receipts, reservations and holds with due dates, safety stock, date | ATP (QA-4) |
| `earliest_full_date` | Same + quantity + horizon | First date the full quantity is available, or none |
| `counter_terms` | Request, ATP facts, horizon | IF-1 counter-offer terms |
| `safety_release_allowed` | Request slack, shortfall, released so far, settings, promise profile | Allowed quantity (minimum needed) or 0 |
| `uncovered_reservations` | Promise profile after a supply change | Reservations not covered, in due-date order |

### 4.2 Read functions Inventory offers

| Function | Returns |
| --- | --- |
| `atp_by_date(item, from, to)` | ATP per day for the range |
| `stock_position(item)` | on_hand, reserved, held, incoming list, safety stock |
| `reservations_for_order(order)` | Reservations and holds of an order with status |

### 4.3 Actions (write; one transaction each: ledger + balance + event in the outbox)

| Action | Effect |
| --- | --- |
| `answer_request` | OFFER / COUNTER_OFFER / REJECT |
| `place_hold` | `held` +, hold ACTIVE with expiry; `AGREEMENT_PROPOSED` |
| `commit_hold` | Re-check; `held` −, `reserved` +; reservation ACTIVE; `ReservationCommitted` |
| `release` | `reserved` − (or `held` −); `ReservationReleased` |
| `apply_change` | Delta: extra quantity through a new request, or release of the difference (QA-3) |
| `expire_holds` | On `SimulatedDayStarted`: holds past expiry → EXPIRED, `held` − |
| `apply_receipt` / `apply_issue` / `apply_finished_goods` / `apply_shipment` | `on_hand`, `incoming`, `reserved` per `1_…` §6 |
| `apply_supply_change` | `incoming` date/quantity; then `mark_at_risk` |
| `mark_at_risk` / `restore_covered` | Reservation AT_RISK ↔ ACTIVE; `StockAvailabilityChanged` lists them |
| `use_safety_stock` | `SAFETY_STOCK_USE` ledger row; `SafetyStockBreached` |
| `reconcile` | Compare balances with ledger sums; report any difference (changes nothing) |

## 5. Decision rules

### 5.1 Answering a request (IF-1)

1. `q ≤ ATP(needed_by)` → OFFER q by `needed_by`.
2. Else, if `earliest_full_date` exists within the horizon (shared setting, default 60 days, PL-7) → COUNTER_OFFER:
   full q on that date.
3. Else, if `ATP(needed_by) > 0` → COUNTER_OFFER: `ATP(needed_by)` by `needed_by`.
4. Else, if the safety-stock release rule allows the shortfall → OFFER with the release (§5.2).
5. Else → REJECT, reason `INSUFFICIENT`.

The safety-stock check (§5.2) is applied before steps 2–3 when the request is urgent (slack ≤ the slack limit), so
an urgent order can be served on time instead of being pushed later.

### 5.2 Safety-stock release (RD-6, IN-4)

Allowed quantity = the **minimum** shortfall, only if all hold:
- deadline slack ≤ `safety_stock_max_slack_days` (default 2);
- total released for the item ≤ `safety_stock_release_share` × safety stock (default 50 %);
- after the release, `S(t) − C(t) ≥ 0` for every later day (no other promise uncovered).

### 5.3 Supply change (IF-2)

`incoming` changes → walk this item's promises in due-date order (then commit time) → the ones no longer covered
become AT_RISK → one `StockAvailabilityChanged` lists them (item, reservation ids, orders, missing quantity, from
date). Inventory never releases them itself. When later supply covers them again → ACTIVE and a new
`StockAvailabilityChanged`.

## 6. The AI step (wording only)

| Step | Input | Output | Check |
| --- | --- | --- | --- |
| `ai_word_message` | Message type, code-computed terms, reason code | One or two short sentences | Every number and date must equal the terms; else retry once, then a fixed template |

If the model is down, the template is used; the decision itself never waits for the AI.

## 7. Statuses

| Record | Statuses |
| --- | --- |
| Hold | ACTIVE → COMMITTED; side: EXPIRED, ABORTED |
| Reservation | ACTIVE ↔ AT_RISK → ISSUED (fully issued); side: RELEASED |

## 8. Settings (configurable, defaults)

| Setting | Default | Source |
| --- | --- | --- |
| `safety_stock_release_share` | 50 % | RD-6 |
| `safety_stock_max_slack_days` | 2 days | RD-6 |
| Counter-offer horizon | 60 days (shared with Planning) | PL-7 |
| Hold validity | 24 h (one simulated day) | NG-2 |

## 9. Boundaries (must not do)

- Start negotiations, choose suppliers or plan refills (Planning does).
- Change space, receiving or worker records.
- Change quantities without a ledger row.
- Let the AI decide or change any number.
- Cancel a commitment on its own.

## 10. Decisions recorded

| ID | Decision |
| --- | --- |
| IF-1 | Counter-offer rule: full quantity at the earliest date within the shared horizon; otherwise the most available by the needed date; urgent requests check the safety-stock release first. |
| IF-2 | Uncovered reservations become AT_RISK and are reported in `StockAvailabilityChanged`; Inventory never releases them on its own; they return to ACTIVE when covered again. |

## 11. Safeguards and tests

- The developer's 5000 → 3000 example (`quantity_accounting.md` §5.1) as an exact test.
- Three simultaneous requests on one item: total held never exceeds ATP.
- Safety-stock release: refused at slack 3 days, allowed at 2; never above 50 %; never uncovers another promise.
- Supplier delay: the right reservations become AT_RISK and return to ACTIVE after the receipt.
- Repeated event or message → no second ledger row (unique `source_id`).
- Reconcile after every test: balances equal ledger sums.
- Fake AI that writes a wrong number → template used.
