# dev_docs

Design documents for the six-agent MRPII research prototype. Rules for how Claude works are in `/CLAUDE.md`.

**Status legend:** DONE = written and approved by the developer · PLANNED = not written yet.

| Path | Contents | Status |
| --- | --- | --- |
| `ROADMAP.md` | Build phases, current phase, phase gates | DONE |
| `DECISIONS.md` | Confirmed and open decisions | DONE |
| `architecture/high_level_architecture.md` | Six agents, boundaries, how they connect | DONE |
| `architecture/pubsub_event_channel.md` | Event envelope, catalogue, subscriptions, delivery rules | DONE |
| `architecture/negotiation.md` | Private negotiation protocol, holds, commitments, priority | DONE |
| `architecture/quantity_accounting.md` | How every quantity changes (stock, reservations, space, workforce) | DONE |
| `research/real_manufacturing_mrpii_research.md` | How real MRPII/ERP systems work; sources; gap analysis | DONE (research, 2026-10-17) |
| `planning_agent/` | Planning Agent design (4 notes) | DONE |
| `inventory_agent/` | Inventory Agent design (4 notes) | DONE |
| `warehouse_agent/` | Warehouse Agent design (4 notes) | DONE |
| `hr_agent/` | HR Agent design (4 notes) | DONE |
| `architecture/system_design.md` | Runtime, processes, database layout, failure handling | DONE |
| `architecture/backend_api.md` | Backend API design across agents | DONE |
| `architecture/demo.md` | Simulation controls and how the demo is run | DONE |
| `sales_agent/` | Sales Agent design (4 notes) | DONE (written before this reorganization) |
| `purchasing_agent/` | Purchasing Agent design | Later, on the developer's instruction |
| `*.png` | Diagrams drawn by the developer | Will be redrawn by the developer |

Each agent folder follows the Sales Agent pattern: `1_high_level_architecture`, `2_functions`, `3_backend`, `4_database`.
