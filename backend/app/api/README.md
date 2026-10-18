# backend/app/api

Thin FastAPI routers. Every non-2xx response uses the C5 error format (`app/core/errors.py`). No business rules here.

| Route | Purpose |
| --- | --- |
| `POST /orders`, `GET /orders`, `GET /orders/{id}` | `orders.py`: create and read customer orders. |
| `POST /plans` `{order_id}`, `GET /plans/{order_id}`, `GET /plans/{order_id}/shortages` | `planning.py`: run the deterministic plan and persist it; read the persisted plan; shortages with supplier feasibility inputs. |
| `POST /negotiations` `{order_id, item_id}` | `negotiations.py`: create the one session for a persisted shortage (status `INITIATED`). |
| `GET /negotiations/{id}` | Session, round, messages, offers, agreement, `outcome` (`AGREEMENT` / `FAILED` / null) and the participant ids to use in envelopes. |
| `POST /negotiations/{id}/messages` | Submit a C4 envelope directly (Phase 2 path, no agent reacts). `COMMIT` is refused (approval workflow is C8). |
| `POST /a2a/inventory`, `/a2a/purchasing` (+ `.well-known/agent-card.json`) | `a2a.py`: two endpoints of the official A2A SDK in this app. Each takes an A2A `SendMessage` with one data part holding the C4 envelope and answers with an acknowledgement (`accepted`, `session_status`, `round_number`, `outcome` or `error`; `reaction_error` if the receiving agent failed). An accepted message is routed to the receiving agent (`agents/workflow.py`) before the answer. The transport decides nothing. |
| `POST /agents/planning/orders/{order_id}` | `agents.py`: hand the order to the Planning Agent (plan, Inventory assessment, Inventory → Purchasing negotiations, round-1 offers). Returns plan status, shortages, the inventory assessment and the procurement state per shortage. |
| `GET /agents/planning/orders/{order_id}/procurement-results` | Per shortage session: status, round, `outcome` (`AGREEMENT`, `FAILED` for REJECTED/FAILED, or null), agreement. |
| `GET /agents/{agent_code}/state` | C6 state of `PRODUCTION_PLANNING_AGENT`, `INVENTORY_AGENT` or `PURCHASING_AGENT` (read-only). |
| `GET /agents/decisions?order_id=&negotiation_id=` | The C7 decision log with the deciding agent's code. |
| `GET /plans/{order_id}/attempts` | C8 planning attempts: `approval_status`, `approvable`, `blockers`, negotiations, `attempts_remaining`. |
| `POST /plans/{order_id}/attempts/{n}/approve` | Human approval: COMMIT, re-plan with committed receipts, stock reservation (D8). 409 if not the current attempt awaiting approval; 422 if not approvable. |
| `POST /plans/{order_id}/attempts/{n}/reject` `{reason?}` | Human rejection: ABORT uncommitted agreements; attempt 1 → replan as attempt 2; attempt 2 → `HUMAN_INTERVENTION_REQUIRED`. |
| `GET /health` | Liveness. |

Use the `/agents` routes for agent-driven sessions; the Phase 2 `/negotiations/{id}/messages` route bypasses the
agents. The legacy supplier routes (`/supplier-interface/...`, `/negotiations/{id}/supplier-responses`,
`/a2a/supplier-interface`) were removed 2026-10-18: a legacy negotiation can no longer get a supplier answer. `simulation.py` is an empty placeholder (Phase 4).

Without `DATABASE_URL` the routes that need the database answer `SERVICE_UNAVAILABLE` (503).
