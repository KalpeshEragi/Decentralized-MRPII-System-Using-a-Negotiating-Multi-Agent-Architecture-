# backend/app/observer

The observer (`dev_docs/architecture/backend_api.md` §7, API-3): read-only views for the demo frontend. It decides
nothing and writes nothing. It reads agents' data only through their read modules (IB-2) and otherwise only the
infrastructure tables (events, negotiation, simulation, observability).

| File | Purpose |
| --- | --- |
| `views.py` | `orders` (every order: Sales stage, plan status, production orders), `order_story` (one order: Sales, plan, what each owner holds or committed, its negotiation sessions, its events), `timeline` (events, negotiation messages, triggers, AI calls, failed work, in time order, with a `next` cursor for polling, API-2), `factory_state` (stock and ATP per item, free space per zone, free receiving, free worker-hours per skill, free machine-hours per work center, for one simulated day). |
| `api.py` | `GET /observer/orders`, `/orders/{ref}` (demand id, request ref or Sales order number), `/timeline?after=&case=`, `/factory-state?day=` (default: today). |

Not yet: `GET /observer/metrics` (step 8 measurements).

**Tests:** `backend/tests/platform/test_s1_order_flow.py` reads the order story and the factory state at the end of S1.
