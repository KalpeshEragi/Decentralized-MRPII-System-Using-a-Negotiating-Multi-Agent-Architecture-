# Project Decisions

## Decision Status

Use these statuses:

- PROPOSED
- CONFIRMED
- APPLIED

## P0-01 — Parked agent stubs

**Status:** APPLIED

**Problem:**  
`dev_docs/DECISIONS.md` said the Sales/Production/Warehouse stubs "stay in the repo, unused and untouched". The roadmap (§4) said they were removed and are not rebuilt. In the repo they still existed as 0-byte files, plus `agents/sales/test_sales_agent.py`.

**Proposed Resolution:**  
Delete the empty `agents/{sales,production,warehouse}/` files in the Phase 0 baseline PR and update the "Parked code" line in `DECISIONS.md` to match the roadmap.

**Final Decision:**  
The empty Sales/Production/Warehouse agent files are deleted and are not rebuilt in the 25%.

**Rationale:**  
The two documents contradicted each other, and the repository matched neither exactly.

**Affected Areas:**  
- `dev_docs/DECISIONS.md`
- `backend/app/agents/`

**Implementation Status:**  
APPLIED

---

## P0-02 — Who initiates procurement negotiation

**Status:** CONFIRMED

**Problem:**  
`system_spec.md` §2 shows Planning sending REQUEST to Purchasing. `dev_docs/DECISIONS.md` (finalized, newer) says the Inventory Agent detects the shortage and initiates negotiation with Purchasing over A2A, and Planning receives the result.

**Proposed Resolution:**  
Follow `DECISIONS.md`. C4 states the Inventory → Purchasing initiation explicitly. Add a one-line "superseded by DECISIONS.md" note to `system_spec.md` §2. Also agree how Planning's MRP net requirement and Inventory's shortage detection stay consistent (both from the same deterministic services).

**Final Decision:**  
The Inventory Agent detects the shortage and initiates Inventory → Purchasing negotiation over A2A. Planning receives the negotiated result (agreement or `FAILED`). Planning's MRP net requirement and Inventory's shortage detection both come from the same deterministic services. This supersedes the Planning → Purchasing REQUEST in `system_spec.md` §2.

**Rationale:**  
`dev_docs/DECISIONS.md` is the finalized and newer source.

**Affected Areas:**  
- C4 — Negotiation protocol
- `dev_docs/implementation_25%/system_spec.md`

**Implementation Status:**  
IN_PROGRESS — `system_spec.md` note applied; C4 not yet drafted.

---

## P0-03 — Postgres hosting

**Status:** APPLIED

**Problem:**  
`database_schema.md` says Neon Serverless and `tech_stack.md` says Neon, but roadmap D4 recommends Docker Compose.

**Proposed Resolution:**  
Originally proposed as local Docker Compose PostgreSQL. Mark `tech_stack.md` as superseded by `DECISIONS.md` for the other stack items. Test-database isolation is decided in Phase 2 (C2).

**Final Decision:**  
PostgreSQL is hosted on **Neon** (serverless), as in `database_schema.md`. There is no local Postgres container. The backend connects through the configurable `DATABASE_URL`. How tests get an isolated database is decided in Phase 2 (C2). First confirmed as local Docker Compose, then changed by the team on 2026-09-30 to Neon (final).

**Rationale:**  
The documents disagreed on hosting. Neon matches `database_schema.md` and `tech_stack.md`.

**Affected Areas:**  
- Roadmap D4
- `.env.example`
- `dev_docs/tech_stack.md`
- C2 — Database schema (test-database isolation)

**Implementation Status:**  
APPLIED

---

## P0-04 — `negotiation_sessions.completed_at` nullability

**Status:** APPLIED

**Problem:**  
`negotiation_sessions.completed_at` is NOT NULL, which is impossible for an open session.

**Proposed Resolution:**  
Make it nullable; set it only when the session reaches an end status.

**Final Decision:**  
`negotiation_sessions.completed_at` is nullable; it is set only when the session reaches an end status.

**Rationale:**  
An open session has no completion time.

**Affected Areas:**  
- C2 — Database schema (Dev 2)
- `dev_docs/implementation_25%/database_schema.md`

**Implementation Status:**  
APPLIED

---

## P0-05 — Message types mixed with session statuses

**Status:** APPLIED

**Problem:**  
`database_schema.md` listed `INITIATED`, `NEGOTIATING`, `EXPIRED` and `ABORTED` as message types.

**Proposed Resolution:**  
Message types: `REQUEST`, `OFFER`, `COUNTER_OFFER`, `ACCEPT`, `REJECT`, `AGREEMENT_PROPOSED`, `COMMIT`. Session statuses: `INITIATED`, `NEGOTIATING`, `AGREEMENT_PROPOSED`, `COMMITTED`, `REJECTED`, `ABORTED`, `EXPIRED`, `FAILED`.

**Final Decision:**  
Message types are `REQUEST`, `OFFER`, `COUNTER_OFFER`, `ACCEPT`, `REJECT`, `AGREEMENT_PROPOSED`, `COMMIT`. Session statuses are `INITIATED`, `NEGOTIATING`, `AGREEMENT_PROPOSED`, `COMMITTED`, `REJECTED`, `ABORTED`, `EXPIRED`, `FAILED`.

**Rationale:**  
Session lifecycle states were listed as message types, mixing two different concepts.

**Affected Areas:**  
- C4 — Negotiation protocol
- C2 — Database schema (Dev 2)
- `dev_docs/implementation_25%/database_schema.md`

**Implementation Status:**  
APPLIED

---

## P0-06 — `negotiation_offers.valid_until` nullability

**Status:** APPLIED

**Problem:**  
`negotiation_offers.valid_until` is NOT NULL with no rule for its value.

**Proposed Resolution:**  
Make it nullable; if timeouts are adopted (D9), set it from the round/session deadline.

**Final Decision:**  
`negotiation_offers.valid_until` is nullable; if timeouts are adopted (D9) it is set from the round/session deadline.

**Rationale:**  
No rule defines the value while timeouts (D9) are undecided.

**Affected Areas:**  
- C2 — Database schema (Dev 2)
- C4 — Negotiation protocol
- Roadmap D9
- `dev_docs/implementation_25%/database_schema.md`

**Implementation Status:**  
APPLIED

---

## P0-07 — Stale `PROJECT_STATUS.md`

**Status:** APPLIED

**Problem:**  
`PROJECT_STATUS.md` described the removed prototype (7 passing tests, UTF-16 `requirements.txt`, working MRP engine).

**Proposed Resolution:**  
Rewrite it in the Phase 0 baseline PR to describe the actual state (scaffold only, Phase 0 in progress).

**Final Decision:**  
`PROJECT_STATUS.md` describes the actual repository state.

**Rationale:**  
The prototype code it described had been removed.

**Affected Areas:**  
- `dev_docs/PROJECT_STATUS.md`

**Implementation Status:**  
APPLIED

---

## P0-08 — Wrong paths in `CLAUDE.md`

**Status:** APPLIED

**Problem:**  
`CLAUDE.md` referred to `docs/DECISIONS.md` and `dev_docs/implementation_25%/tech_stack.md`; the files were `dev_docs/DECISIONS.md` and `dev_docs/tech_stack.md`. It also said `docs/` holds status, plan and decisions, which lived in `dev_docs/`.

**Proposed Resolution:**  
Small coordination PR correcting the paths only.

**Final Decision:**  
`CLAUDE.md` paths point at `dev_docs/`.

**Rationale:**  
The referenced paths did not exist.

**Affected Areas:**  
- `CLAUDE.md`

**Implementation Status:**  
APPLIED

---

## P0-09 — Agent policy storage

**Status:** APPLIED

**Problem:**  
`system_spec.md` §3 leaves open whether per-agent policy items are columns or JSONB.

**Proposed Resolution:**  
Store them in `agent_state.negotiation_rules.policy` (JSONB); no new columns (C6).

**Final Decision:**  
Per-agent policy items are stored in `agent_state.negotiation_rules.policy` (JSONB); no extra columns.

**Rationale:**  
C6 needed a fixed location for the policy items listed in `agent_operations.md`.

**Affected Areas:**  
- C6 — Agent state
- C2 — Database schema

**Implementation Status:**  
APPLIED

---

## P0-10 — D1 fixture data undefined

**Status:** CONFIRMED

**Problem:**  
Scenarios give only: 1,000 SmartPhone X1; 1,000 → 1,300; 500 → 300 Display Assemblies; due date 30 → 20 days. Missing: X1 BOM components and `quantity_per`, `on_hand`/`reserved`/`safety_stock` per component, warehouses (one or several), suppliers per component (`lead_time_days`, `min_order_qty`, `available_qty`), order date and priority, production lead time and capacity. `what_if_variants_example.md` uses an Office Chair example, not X1.

**Proposed Resolution:**  
Write one fixture spec in `docs/` jointly, choosing values so each in-scope scenario (1, 2, 3, 4, 6, 7) yields its expected outcome. No values are invented before that.

**Final Decision:**  
One SmartPhone X1 fixture spec is written jointly in `docs/`, with values chosen so scenarios 1, 2, 3, 4, 6, 7 yield their expected outcomes. No fixture values are invented before it exists.

**Rationale:**  
`scenarios.md` does not contain enough data to compute exact MPS/MRP results.

**Affected Areas:**  
- Roadmap D1
- C1 examples
- Phase 1 tests
- Phase 2 seed

**Implementation Status:**  
NOT_STARTED

---

## P0-11 — Production lead time has no field

**Status:** CONFIRMED

**Problem:**  
C1 needs a production lead time to derive `planned_start` and component `required_by`. `core.items` has no such field and `production.*` is out of scope.

**Proposed Resolution:**  
Either add `production_lead_time_days` to `core.items` (C2) or keep it as a fixture/config value per product.

**Final Decision:**  
A per-product production lead time is needed to derive MPS start and component required-by dates. Storage (`core.items` column or fixture/config value) is chosen in C2.

**Rationale:**  
No existing table holds the value within the 25% scope.

**Affected Areas:**  
- C1 — Domain data shapes
- C2 — Database schema
- Roadmap D1

**Implementation Status:**  
IN_PROGRESS — applied in C1; storage choice pending in C2.

---

## P0-12 — Source of scheduled receipts

**Status:** CONFIRMED

**Problem:**  
`projected_available_quantity` needs scheduled receipts, but purchase orders are out of scope.

**Proposed Resolution:**  
Committed negotiation agreements (`agreed_terms` quantity + delivery date) are the scheduled receipts; exact read path defined in C2/C4.

**Final Decision:**  
Committed negotiation agreements (agreed quantity and delivery date) are the scheduled receipts used for projected availability. Purchase orders stay out of scope. Read path defined in C2/C4.

**Rationale:**  
The negotiation agreement is the purchasing outcome in the 25% scope.

**Affected Areas:**  
- C1 — Domain data shapes
- C2 — Database schema
- C4 — Negotiation protocol

**Implementation Status:**  
IN_PROGRESS — applied in C1 and `database_schema.md`; read path pending in C2/C4.

---

## P0-13 — MRP columns

**Status:** APPLIED

**Problem:**  
`planning.mrp_requirements` has `available_inventory` but no `scheduled_receipts` or `projected_available_quantity`.

**Proposed Resolution:**  
Add both columns in migration 001 (C2), mapping `available_inventory` to C1 `available_quantity`.

**Final Decision:**  
`planning.mrp_requirements` gains `scheduled_receipts` and `projected_available_quantity`; `available_inventory` holds `available_quantity`.

**Rationale:**  
C1's MRP calculation produces values the table could not store.

**Affected Areas:**  
- C1 — Domain data shapes
- C2 — Database schema
- `dev_docs/implementation_25%/database_schema.md`

**Implementation Status:**  
APPLIED

---

## P0-14 — Capacity data source

**Status:** APPLIED

**Problem:**  
Scenarios 3 and 7 mention capacity (D3), but `production.machines` is out of scope.

**Proposed Resolution:**  
If D3 keeps a minimal check: one `capacity_per_day` value per product in the fixture/config, no production tables.

**Final Decision:**  
If D3 keeps a minimal capacity check, capacity is one `capacity_per_day` value per product in the fixture/config. No `production.*` tables.

**Rationale:**  
A minimal check needs a capacity value without bringing `production.*` tables into scope.

**Affected Areas:**  
- C1 — Domain data shapes
- Roadmap D1
- Roadmap D3

**Implementation Status:**  
APPLIED

---

## P0-15 — Priority scale

**Status:** APPLIED

**Problem:**  
`priority` is an INTEGER everywhere, with no direction or range.

**Proposed Resolution:**  
`1` = highest, range 1–5.

**Final Decision:**  
Integer 1–5, `1` = highest.

**Rationale:**  
Priority ordering must be unambiguous for MPS ordering and negotiation.

**Affected Areas:**  
- C1 — Domain data shapes
- C2 — Database schema
- C4 — Negotiation protocol

**Implementation Status:**  
APPLIED

---

## P0-16 — Date vs timestamp

**Status:** CONFIRMED

**Problem:**  
The schema uses `TIMESTAMP` for `planned_start`, `planned_end`, `required_by` and delivery dates, while C1 plans in day buckets.

**Proposed Resolution:**  
Domain uses `DATE`; either change these columns to `DATE` or store midnight UTC.

**Final Decision:**  
The domain plans in whole days (`DATE`). Column mapping (`DATE` columns or midnight UTC timestamps) is chosen in C2.

**Rationale:**  
The domain model and the schema used different date granularity.

**Affected Areas:**  
- C1 — Domain data shapes
- C2 — Database schema

**Implementation Status:**  
IN_PROGRESS — applied in C1; column mapping pending in C2.

---

## P0-17 — `master` vs `main`

**Status:** APPLIED

**Problem:**  
The roadmap (§7.3, §10) said `main`; the repository uses `master`.

**Proposed Resolution:**  
Keep `master` as the protected shared integration branch; do not rename now. Branches: `dev1/phase-N-topic`, `dev2/phase-N-topic` from the `master` baseline. Update the roadmap wording.

**Final Decision:**  
`master` is the protected shared integration branch (not renamed to `main`). Work happens on short-lived `dev1/phase-N-topic` and `dev2/phase-N-topic` branches from the `master` baseline, merged by reviewed PR. Decided by Dev 1 on 2026-09-29.

**Rationale:**  
The roadmap and the repository disagreed on the branch name.

**Affected Areas:**  
- Roadmap §7.3, §10
- Roadmap D12

**Implementation Status:**  
APPLIED
