# Project Decisions — Detailed Record

Authoritative, detailed record of coordination decisions: Phase 0 items (P0-xx) and open Phase 1 prerequisites (P1-xx).
`dev_docs/DECISIONS.md` is the project-level summary; where they differ, this file is corrected first and the summary follows.
`scenarios.md` is not modified by any item.

## Decision Status

Use these statuses:

- UNRESOLVED (open; needs a decision)
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

**Status:** APPLIED

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
APPLIED — `system_spec.md` §2 note, C4 §1 and §6, and the three `*_agent_architecture.md` docs (2026-09-30).

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
- C2 — Database schema
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
- C2 — Database schema
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
- C2 — Database schema
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
APPLIED. **Updated 2026-09-30:** with the switch to a single developer, branches are named `phase-N-topic`
(single-developer roadmap §2); `master` stays the integration branch.

---

# Phase 1 Prerequisites

Recorded 2026-09-30 from the Phase 0 integration review. Unless marked otherwise, none is decided here. Options come
from the roadmap or existing documents and are listed without choosing. Each needs the developer's confirmation before
the phase that depends on it starts (single-developer roadmap §5). References to D1–D13 use the numbering of the former
two-developer roadmap §14.

## P1-01 — D1 SmartPhone X1 fixture spec

**Status:** PROPOSED (2026-09-30) — values proposed to the developer; not yet written to `docs/` or implemented

**Problem:**
Roadmap Phase 1 requires exact-number MRPII tests on the X1 fixture, and P0-10 requires one fixture spec in `docs/`.
Missing values are listed in P0-10.

**Needed by:** Phase 1 (`mrpii/` tests, `data/` fixtures); Phase 2 seed.

## P1-02 — D2 BOM depth

**Status:** CONFIRMED (2026-09-30)

**Final Decision:**
Single-level BOM for the 25% milestone: a finished product has one list of components with `quantity_per`; components
have no BOM of their own. Multi-level BOM is out of scope.

**Applied in:** C1 §3.2.

## P1-03 — D3 minimal capacity check

**Status:** CONFIRMED (2026-09-30)

**Final Decision:**
A minimal deterministic capacity check is in scope, using one `capacity_per_day` value per product (P0-14, fixture/config).
Rule: an MPS entry is feasible only if `planned_quantity <= capacity_per_day × production_lead_time_days` (calendar days of
the production window, `planned_start` to `planned_end`). Otherwise the plan validator reports `CAPACITY_EXCEEDED`.
No machines, no scheduling, no optimization.

**Applied in:** C1 §3.9, §3.10.

## P1-04 — D9 AGREEMENT_PROPOSED / COMMIT and timeouts

**Status:** CONFIRMED (2026-09-30), except the item marked PENDING

**Final Decision:**
- The **Purchasing Agent** sends `AGREEMENT_PROPOSED` (to the Inventory Agent, the session initiator) when an agreement with
  the supplier is ready. The agreed terms are then validated deterministically (`negotiation_agreements.validated`).
- `COMMIT` happens **only after the required human approval** of the plan that uses the agreement. Until then the session stays
  `AGREEMENT_PROPOSED` and nothing is reserved or committed. `COMMIT` is an approval/lifecycle action, not an autonomous
  negotiation decision: the application/approval workflow (sender type `APPROVAL_WORKFLOW`, not an agent) performs it after
  human approval. Inventory and Purchasing must not commit an agreement themselves. Phase 1 represents the transition
  (`COMMIT` valid only after `AGREEMENT_PROPOSED`, only from the approval workflow). The approval workflow itself, and what
  happens to an uncommitted agreement when the plan is rejected, are defined in C8 (Phase 4) — **PENDING C8**.
- **Timeouts (simple):** there are no timers, background jobs or automatic expiry in the 25% milestone. Negotiation is bounded
  only by the 3-round limit, and planning by the 2-attempt limit. `negotiation_sessions.deadline` holds the shortage's
  required-by date (the latest acceptable delivery), used for validation, not for expiry. `negotiation_offers.valid_until`
  stays `NULL`. The `EXPIRED` status is not produced automatically in the 25% milestone.

**Applied in:** C4 §3, §6, §7; C2 (column use).

## P1-05 — C4 OfferTerms fields and envelope serialization

**Status:** CONFIRMED (2026-09-30)

**Final Decision:**
`OfferTerms` has exactly `quantity`, `required_date`, `delivery_date` and `priority`. Not offer terms: `lead_time` (comes
from supplier data; `delivery_date` is the negotiated commitment), `inventory_impact` (calculated by deterministic
application logic) and price/cost (out of scope). The Phase 1 envelope is the model in
`backend/app/schemas/negotiation.py`; carrying it inside an A2A message waits for the Phase 2 spike (D13).

**Applied in:** C4 §4, §5; `schemas/negotiation.py`.

## P1-06 — Planning ↔ Inventory allocation semantics

**Status:** UNRESOLVED

**Problem:**
P0-02 decided Inventory → Purchasing initiation for shortages. `system_spec.md` §2 and the agent architecture docs also show
Planning sending a REQUEST to Inventory for allocation. It is not decided whether that allocation exchange is a
negotiation session (C4 messages, persisted in `negotiation.*`) or a direct availability/allocation request answered
through the inventory service, nor how the two paths share one deterministic shortage figure.

**Needed by:** C4 confirmation; Phase 3 agents. Not needed by the Phase 1 MRPII code.

## P1-07 — Supplier interaction inside negotiation

**Status:** CONFIRMED (2026-09-30), except supplier-message storage

**Final Decision:**
- One **round** = one Purchasing `OFFER` / `COUNTER_OFFER` to the supplier interface + the supplier's response.
  Maximum 3 rounds ("Round N of 3").
- The supplier responds through the structured form with `ACCEPT`, `COUNTER_OFFER` (quantity, delivery date, optional
  message; no price) or `REJECT`.
- **Supplier sender:** `SUPPLIER_INTERFACE` — the supplier form/service only. Supplier = data/service/interface; a Supplier
  Agent is not part of the 25% implementation.
- **Purchasing may `REJECT` early**, before the round limit, when it has no acceptable proposal. The supplier interface may
  also send `REJECT`. Either produces session status `REJECTED`, which is terminal.
- `REJECTED` = explicit participant rejection. `FAILED` = the 3-round limit was reached without agreement.
- Planning receives the normalized outcome `FAILED` for both: the shortage stays unresolved and the plan is not updated.

**Still UNRESOLVED:** how supplier-side messages are stored while `negotiation_messages` sender/receiver reference
`agent.agents` (needed by Phase 2, migration 002).

## P1-08 — Scope of "Phase 1"

**Status:** CONFIRMED (2026-09-30)

**Problem:**
The former two-developer roadmap and C2 defined Phase 1 as the deterministic core with no database, while the Phase 0
review request described Phase 1 as the database foundation.

**Final Decision:**
The project continues with one developer under `dev_docs/implementation_25%/single_developer_roadmap.md`. Phase 1 is the
deterministic core (MRPII, pure negotiation protocol, LLM client) without a database; database, services and the A2A spike
are Phase 2.

## P1-09 — Finished-goods netting before the MPS

**Status:** CONFIRMED (2026-09-30)

**Final Decision:**
- Planning flow: customer order → finished-goods netting → MPS → capacity → BOM → MRP. Available finished goods use
  `max(0, on_hand - reserved - safety_stock)`; `net_production_requirement = max(0, order_quantity - available_finished_goods)`;
  the MPS `planned_quantity` is that net quantity and capacity is checked against it.
- **Same item on several lines of one order:** the lines share the available finished goods, in line order.
- **Several orders:** each order is planned on its own against the finished-goods position it is given. Allocating one
  finished-goods stock across several orders is not done in the 25% (the plan handles one order at a time).
- **Order fully covered by finished goods:** no MPS entry, no capacity check, no MRP rows; the plan is `VALIDATED`.
- The X1 baseline has no finished-goods stock, so it is unchanged (1,000 planned).

**Applied in:** C1 §3.5a, §3.6, §3.11; `mrpii/mps.py`, `mrpii/plan.py`.

## P2-01 — Phase 2 persistence decisions

**Status:** CONFIRMED (2026-09-30)

**Final Decision:**
- **Dates (closes P0-16):** `planning.mps_plans.planned_start` / `planned_end`, `planning.mrp_requirements.required_by` and
  `purchasing.purchase_requisitions.required_by` are `DATE` columns. Other TIMESTAMP columns are `timestamptz`.
- **Production parameters (closes P0-11, P0-14):** production lead time and `capacity_per_day` are fixture/config values
  (`app/data/x1_fixture.py`), not columns. No columns are added to `core.items`.
- **Supplier-side messages (closes P1-07 storage):** `negotiation_messages.sender_agent_id` / `receiver_agent_id` are nullable and
  `sender_type` / `receiver_type` (NOT NULL) are added. The supplier interface and the approval workflow have no `agent.agents` row.
- **D7 / test isolation (closes the open part of P0-03):** Alembic covers the 25% tables only (24 tables). DB tests use a separate
  `TEST_DATABASE_URL` (a second Neon database or branch), start each test from `reset_and_seed`, and skip when it is unset.
- **Warehouses (P0-10):** inventory is one aggregated position per item (one warehouse in the fixture); services sum across warehouses.
- **Scheduled receipts read path (closes P0-12):** committed `negotiation_agreements` (`committed = true`) joined to their session
  objective (item id) give `ScheduledReceipt(item, agreed quantity, agreed delivery_date, source_ref = agreement id)`.
  Uncommitted agreements never count.
- **A2A spike (D13, part):** three endpoints of the official A2A SDK (JSON-RPC) in the same FastAPI app carry the C4 envelope as one
  data part; the protocol validates and rejects, the transport decides nothing. `COMMIT` is refused over HTTP until C8.

**Working values, not yet decided (flagged, easy to change):** `negotiation_type = SHORTAGE_PROCUREMENT`; participant roles
`INITIATOR` / `RESPONDER`; offer statuses `PROPOSED`, `SUPERSEDED`, `ACCEPTED`, `REJECTED`; reservation statuses `ACTIVE` /
`RELEASED`; audit `decision_type` values (C7) and which agent each audit row is attributed to; session `objective` = the C1
`Shortage` JSON; placeholder SKUs, warehouse, demo customer and agent names in the seed.

**Still open (Phase 3+):** whether the OpenAI Agents SDK, A2A and Ollama no-reasoning mode work together end to end (D13): the spike
configures them but has not been run against a live Ollama; the C8 approval workflow; the content of the shortage-context message.
