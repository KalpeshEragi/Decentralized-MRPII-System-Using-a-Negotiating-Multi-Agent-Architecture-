# Warehouse Agent: Database Design

**Status:** APPROVED by the developer (2026-10-17). Nothing here is created or migrated.
**Database:** PostgreSQL on Neon (`DATABASE_URL`; tests use `TEST_DATABASE_URL`).
**Schema:** `warehouse` (owned by Warehouse; new, no old tables). Items come from the shared `core.items`.
**Related:** `1_warehouse_agent_high_level_architecture.md`, `2_warehouse_agent_functions.md`,
`3_warehouse_agent_backend.md`, `../architecture/quantity_accounting.md` (§7 capacity rule, §8 ledger).

## 1. Ground rules

1. Warehouse writes only the `warehouse` schema; it reads `core.items` (zone by item type, `space_per_unit`).
2. Warehouse stores **space units and receiving/shipping units**, never the stock truth; item quantities on its
   records only describe the movement (IN-1).
3. Every change is a ledger row plus a balance update in one transaction (QA-1).
4. Space uses a **movement profile** (WD-1): space occupied now + dated planned arrivals and departures + holds.
5. No price, cost or priority. Times UTC; days `DATE`; ids UUID; JSON = JSONB. Statuses enforced by the database.

## 2. Tables

### Space (two zones, WH-2)

**zones** — zone (PK: MATERIALS, FINISHED_GOODS) · capacity_units · occupied_now · version · updated_at

**zone_capacity_changes** — id (PK) · zone (FK) · from_day · to_day (empty = open-ended) · capacity_units · reason
(e.g. PARTLY_UNUSABLE) · created_at

**space_commitments** — id (PK) · kind (DELIVERY, FINISHED_GOODS) · zone (FK) · item_id · quantity · space_units ·
arrival_day · until_day (empty = no planned departure) · for_ref (Purchasing commitment ref or Planning demand /
production order) · case_id · negotiation_id · status (§3) · version · created_at · updated_at

**space_movements** — id (PK) · commitment_id (FK) · zone · kind (ARRIVAL, DEPARTURE) · space_units · item_id ·
quantity · planned_day · status (PLANNED, DONE, CANCELLED) · done_at

### Receiving and shipping (per day)

**receiving_days** — day (PK) · capacity_units · committed_units · held_units · used_units

**shipping_days** — day (PK) · capacity_units · used_units

### Holds

**holds** — id (PK) · kind (DELIVERY, FINISHED_GOODS) · zone · item_id · quantity · space_units · receiving_units ·
arrival_day · until_day · case_id · negotiation_id (unique) · expires_at · status (ACTIVE, COMMITTED, EXPIRED, ABORTED)

### Physical input

**deliveries** (simulated supplier deliveries, door 2) — delivery_id (PK) · purchasing_commitment_ref · item_id ·
quantity · arrival_day · status (STORED, POSTED, REFUSED) · received_quantity · refused_quantity · received_at

### Ledger and plumbing

**space_ledger** — id (PK) · resource (ZONE, RECEIVING, SHIPPING) · zone · day · bucket (OCCUPIED, PLANNED_ARRIVAL,
PLANNED_DEPARTURE, HELD, RECEIVING_COMMITTED, RECEIVING_HELD, RECEIVING_USED, SHIPPING_USED, CAPACITY) · delta ·
reason (HOLD, HOLD_EXPIRED, COMMIT, RELEASE, RECEIPT, REFUSED, ISSUE, FG_STORED, SHIPMENT, CAPACITY_CHANGE, ...) ·
commitment_id · hold_id · movement_id · delivery_id · source_id · line_no · sim_time · created_at.
Unique (source_id, line_no).

**Queue tables** (`work_items` and any outbox here) use the standard queue shape of `../architecture/system_design.md` §4.2: `scope_key` (the "one at a time" key; `ref` below), `status` adds RUNNING, plus `locked_by`, `locked_until`, `last_error`, `done_at` (SD-1).

**work_items** — id (PK) · kind · ref · payload (JSON) · status (PENDING, DONE, FAILED) · attempts · next_attempt_at ·
created_at (one writer, WB-2)

**event_versions** — entity_type · entity_id · last_version. PK (entity_type, entity_id).

**audit_log** — id (PK) · time · actor (WAREHOUSE_AI, SYSTEM, HUMAN) · event_type (e.g. REQUEST_ANSWERED, HOLD_PLACED,
COMMITTED, RECEIVED, KITS_ISSUED, SHIPPED, FLAGGED, RECONCILE_DIFFERENCE) · case_id · details (JSON)

## 3. Statuses

| Table | Statuses |
| --- | --- |
| holds | ACTIVE → COMMITTED; side: EXPIRED, ABORTED |
| space_commitments | ACTIVE → IN_USE (arrived / stored) → FREED (issued / shipped); side: RELEASED, FLAGGED |
| space_movements | PLANNED → DONE; side: CANCELLED |
| deliveries | STORED → POSTED; side: REFUSED |

## 4. Free space and receiving (how the numbers are computed)

For a zone and day t (WD-1, same cumulative method as QA-4):

```
capacity(t)  = the zone_capacity_changes row covering t, else zones.capacity_units
occupied(t)  = occupied_now
               + Σ PLANNED ARRIVAL movements with planned_day ≤ t
               − Σ PLANNED DEPARTURE movements with planned_day ≤ t
held(t)      = Σ space_units of ACTIVE holds with arrival_day ≤ t and (until_day empty or until_day ≥ t)
free(t)      = capacity(t) − occupied(t) − held(t)
```

A space request fits only if `free(t) ≥ space_units` for every t from its arrival day to its until day (or to the end
of the horizon if it has none). Goods with no planned departure simply stay counted.

Receiving on day d: `free = capacity_units − committed_units − held_units`; a delivery fits if its units ≤ free.

## 5. How balances relate to records (checked by reconcile)

| Balance | Equals |
| --- | --- |
| `zones.occupied_now` | Σ DONE arrivals − Σ DONE departures for the zone |
| `receiving_days.committed_units` | Σ units of ACTIVE / IN_USE delivery commitments arriving that day |
| `receiving_days.held_units` | Σ receiving units of ACTIVE delivery holds for that day |
| `receiving_days.used_units` | Σ received quantities posted that day |
| `shipping_days.used_units` | Σ shipped quantities that day |
| every balance | Σ of its ledger deltas |

## 6. Rules the database enforces

- All units and quantities ≥ 0; `received_quantity + refused_quantity` = delivered quantity.
- Unique (source_id, line_no) in the ledger; unique `negotiation_id` on holds; unique `delivery_id`.
- `until_day ≥ arrival_day` when set.
- Status values only from §3.

"Fits every day" is checked by code under the single writer (WB-2), not by a constraint, because a capacity cut may
leave an excess that must be flagged, not rejected.

## 7. Decisions recorded

| ID | Decision |
| --- | --- |
| WD-1 | Space uses a movement profile: occupied now per zone + dated planned arrivals and departures + holds; free(t) computed cumulatively like ATP. Receiving and shipping use one balance row per day. |

## 8. Open

| ID | Question |
| --- | --- |
| WD-O1 | Resolved 2026-10-17: Factory A defaults in `demo.md` §4.1. |
| WD-O2 | Resolved 2026-10-17: cleared on reset; kept in the run report (DM-4). |
