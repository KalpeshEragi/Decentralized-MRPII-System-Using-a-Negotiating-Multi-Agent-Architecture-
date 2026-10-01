# backend/app/api

Thin FastAPI routers. Every non-2xx response uses the C5 error format (`app/core/errors.py`). No business rules here.

| Route | Purpose |
| --- | --- |
| `POST /orders`, `GET /orders`, `GET /orders/{id}` | `orders.py`: create and read customer orders. |
| `POST /plans` `{order_id}`, `GET /plans/{order_id}`, `GET /plans/{order_id}/shortages` | `planning.py`: run the deterministic plan and persist it; read the persisted plan; shortages with supplier feasibility inputs. |
| `POST /negotiations` `{order_id, item_id}` | `negotiations.py`: create the one session for a persisted shortage (status `INITIATED`). |
| `GET /negotiations/{id}` | Session, round, messages, offers, agreement, `outcome` (`AGREEMENT` / `FAILED` / null) and the participant ids to use in envelopes. |
| `POST /negotiations/{id}/messages` | Submit a C4 envelope. `COMMIT` is refused (approval workflow is C8). |
| `POST /negotiations/{id}/supplier-responses` | The supplier form: `round_number`, `response_type` (`ACCEPT` / `COUNTER_OFFER` / `REJECT`), `quantity`, `delivery_date`, `message`. No price field. |
| `POST /a2a/inventory`, `/a2a/purchasing`, `/a2a/supplier-interface` (+ `.well-known/agent-card.json`) | `a2a.py`: the A2A transport spike, three endpoints of the official A2A SDK in this app. Each takes an A2A `SendMessage` with one data part holding the C4 envelope and answers with an acknowledgement (`accepted`, `session_status`, `round_number`, `outcome` or `error`). The transport decides nothing; there are no agents behind it yet. |
| `GET /health` | Liveness. |

`agents.py` and `simulation.py` are empty Phase 0 placeholders (Phases 3–4).

Without `DATABASE_URL` the routes that need the database answer `SERVICE_UNAVAILABLE` (503).
