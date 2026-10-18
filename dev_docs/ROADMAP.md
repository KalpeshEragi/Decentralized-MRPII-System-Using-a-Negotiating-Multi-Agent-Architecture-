# Roadmap

Build plan for the six-agent prototype (from the project brief, 2026-10-16; implementation plan approved 2026-10-17).
This is a plan, not a record of what is built. Work only on the current step.

## Phases

- [x] **Phase 1 — Agree on design** (docs 1–11 approved; Purchasing docs by another contributor; diagrams by the developer)
- [x] **Phase 2 — Inspect current code** — folded into the implementation steps (IMP-1): each step reviews, reuses or
  retires the old code it replaces.
- [ ] **Phase 3 — One vertical slice** = steps 1–5 (S1 end to end)
- [ ] **Phase 4 — Rest of the workflow** = step 6
- [ ] **Phase 5 — Simulation controls** = step 7
- [ ] **Phase 6 — Concurrency and measurements** = step 8

## Phase 1 — design docs

1. [x] `architecture/high_level_architecture.md`
2. [x] `architecture/pubsub_event_channel.md`
3. [x] `architecture/negotiation.md`
4. [x] `architecture/quantity_accounting.md`
5. [x] `planning_agent/`
6. [x] `inventory_agent/`
7. [x] `warehouse_agent/`
8. [x] `hr_agent/`
9. [x] `architecture/system_design.md`
10. [x] `architecture/backend_api.md`
11. [x] `architecture/demo.md`
12. [ ] `purchasing_agent/` — by another contributor; must follow `negotiation.md` (§4, §5, §5.1), WH-1 and the event
    catalogue. Until then a FAKE Purchasing stub answers supply requests (IMP-3).
    Status 2026-10-18: design docs written and the agent built standalone (branch `purchasing-agent`); alignment
    with `negotiation.md`, WH-1 and the event catalogue is future integration.

## Implementation steps (current: step 5)

Each step: implement from the referenced docs → run tests → small commits → fast-forward `master` locally (IMP-4).
AI steps are switched on only after S1 works; until then owners use template wording and Planning the fixed ranking
(IMP-2). Tests: about 14 in total, one per important rule.

| # | Step | Docs | Tests |
| --- | --- | --- | --- |
| [x] 1 | Foundation: migration for new schemas and `core` changes; shared work runner; event channel; RFC 9457 errors + correlation id; simulated clock + factory settings | `system_design.md` §4–6, `pubsub_event_channel.md`, `backend_api.md` §3–4, `demo.md` §6, PD-2 | Work runner (claim, lease, retry, idempotency) · Event channel (duplicates, stale, per-entity order) |
| [x] 2 | Pure calculations: multi-level MRP, lot sizing, lead-time offset, hours per day (QA-5), ATP by date, capacity fit, PL-6 ranking | `quantity_accounting.md`, `planning_agent/2`, research §4.2 | Research phone example exact · ATP with supplier delay · Ranking filters and ties |
| [x] 3 | Negotiation v2: starter/owner sessions, A2A store-and-acknowledge, outbox/inbox, holds, commit, expiry, reason codes, `case_id` | `negotiation.md` | Request → offer → hold → commit; duplicate; stale |
| [x] 4 | Owners: Inventory, HR, Warehouse (templates only) | `inventory_agent/`, `hr_agent/`, `warehouse_agent/` | 5000 → 3000 ledger + no double booking · HR absence cover |
| [ ] 5 | Planning + Sales integration → **S1 end to end**; retire old agents, routes, tables and their tests | `planning_agent/`, `sales_agent/`, PB-O1, API-4 | S1 request → shipment (fake AI, simulated days) |
| [ ] 6 | Replanning: pegging, net change, dampener, time fence, AT_RISK repair; S5–S7; Purchasing stub for S2/S3 | RD-4, RD-5, RD-8, `planning_agent/2` §6 | Worker absence repair · Cancellation release |
| [ ] 7 | Simulator + observer API + minimal control panel; then switch on the AI steps | `demo.md`, `backend_api.md` §7 | Snapshot restore + reconcile |
| [ ] 8 | Real Purchasing (contributor); S2–S4, S8; load 10 → 20 → 100 orders with measurements | `demo.md` §8, `system_design.md` §10 | Competing orders across agents |

Database tests need `TEST_DATABASE_URL` (a separate Neon branch) set by the developer.

## Step gate

1. The step's deliverable exists and works.
2. All tests pass, including the step's new tests.
3. Folder `README.md` files, docs and `DECISIONS.md` match the code.
4. Committed and `master` fast-forwarded locally; the developer reviews and pushes.

## Prototype is complete when

- All six agents have implemented, documented responsibilities.
- One order moves through feasibility, private negotiation, commitment, production progress and delivery.
- Events reach the right subscribers reliably; negotiation details stay private.
- Disruptions and cancellations trigger correct updates and replanning.
- Concurrent orders never break resource limits or each other's state.
- A demo operator can set the starting state, trigger a change, and see what the agents did and why.
- High-value tests pass; a repeatable report records results and performance limits.
