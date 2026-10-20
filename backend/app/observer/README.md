# backend/app/observer

The observer (`dev_docs/architecture/backend_api.md` §7, API-3): read-only views for the demo frontend. It decides
nothing and writes nothing. It reads agents' data only through their read modules (IB-2) and otherwise only the
infrastructure tables (events, negotiation, simulation, observability).

| File | Purpose |
| --- | --- |
| `views.py` | `orders` (every order: Sales stage, plan status, production orders), `order_story` (one order: Sales, plan, what each owner holds or committed, its negotiation sessions, its events), `timeline` (events, negotiation messages, triggers, AI calls, failed work, in time order, with a `next` cursor for polling, API-2; a full page ends with a whole time group, because rows of one transaction share one time, so paging never skips rows), `factory_state` (stock and ATP per item, free space per zone, free receiving, free worker-hours per skill, free machine-hours per work center, for one simulated day). |
| `live.py` | `live`: one snapshot for the control panel (clock with what is waiting and why Play paused, the AI setting, the open run, KPIs, stock, zones, workers with who is absent today, lines, docks, the latest orders, open negotiations). |
| `metrics.py` | `measurements` of the current run (system_design §10): orders (by status, on time, real seconds request → committed and confirmed → committed), real seconds per simulated day, event delivery lag / attempts / failures, per work queue (items, failures, queued → done, attempts), negotiations (by status, open → closed, messages), AI calls (by outcome, wait in the shared model's queue, response time). p50 / p95 / max. Saved in every run report. |
| `api.py` | `GET /observer/orders`, `/orders/{ref}` (demand id, request ref or Sales order number), `/timeline?after=&case=`, `/factory-state?day=` (default: today), `/live`, `/metrics`. |

**Tests:** `backend/tests/platform/test_s1_order_flow.py` reads the order story and the factory state at the end of S1; `test_scenarios.py` checks the measurements of an S1 run; `test_observer_timeline.py` the timeline paging.
