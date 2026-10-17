# Roadmap

Build plan for the six-agent prototype (from the project brief, 2026-10-16). This is a plan, not a record of what
is built. Work only on the current phase. Tick a phase only after its gate is met.

## Phases

- [ ] **Phase 1 — Agree on design** ← current
- [ ] **Phase 2 — Inspect current code** (Sales, Planning, Inventory, Purchasing, one at a time: what works, what can be reused, what conflicts, what must change)
- [ ] **Phase 3 — One vertical slice** (one end-to-end scenario through events, negotiation and planning, tested)
- [ ] **Phase 4 — Rest of the workflow** (cancellations, workforce/station limits, receiving, production, delivery; Warehouse and HR built on the agreed contracts)
- [ ] **Phase 5 — Simulation controls** (control panel, triggers, snapshots, reset/replay, timeline)
- [ ] **Phase 6 — Concurrency and measurements** (conflicting resources, event reliability, 10 → 20 → target 100 orders)

## Phase 1 — design docs (in this order, one at a time, developer approval after each)

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
12. [ ] `purchasing_agent/` (when the developer says)

## Test progression (Phases 3–6)

1. One complete order.
2. One order with a supplier delay or material shortage.
3. One order with a storage or workforce constraint.
4. Cancellation or change, with release and replanning.
5. Several orders sharing stock, capacity, space or workforce.
6. 10, then 20, then target 100 in-progress orders. Measure throughput, end-to-end time, waiting time, failures,
   event lag, negotiation duration and resource use. No speed is promised in advance.

## Phase gate

1. The phase's deliverable exists and works (or, for Phase 1, every listed doc is approved).
2. All tests pass, including the phase's new tests.
3. Folder `README.md` files, docs and `DECISIONS.md` match the code.
4. The developer has reviewed the changes and can explain them.
5. Merged to `master` by PR; this file updated.

## Prototype is complete when

- All six agents have implemented, documented responsibilities.
- One order moves through feasibility, private negotiation, commitment, production progress and delivery.
- Events reach the right subscribers reliably; negotiation details stay private.
- Disruptions and cancellations trigger correct updates and replanning.
- Concurrent orders never break resource limits or each other's state.
- A demo operator can set the starting state, trigger a change, and see what the agents did and why.
- High-value tests pass; a repeatable report records results and performance limits.
