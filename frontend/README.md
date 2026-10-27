# frontend

**Decentra** (working name, FE-5): the live control panel of the six-agent factory simulation. Next.js 15 + React 19,
with a 3D view in Three.js through React Three Fiber and drei (FE-1). The backend is the source of truth: the panel
only reads the observer doors and calls the simulation doors (FE-6); it decides nothing.

| Path | Purpose |
| --- | --- |
| `app/page.tsx` | The page: top bar, the 3D factory with floating cards, the agent conversation sidebar. |
| `components/TopBar.tsx` | Simulated day, Quiet / Working, why Play paused, the AI on/off switch (`ai_enabled`), Next day, Play / Pause, scenario picker and start, Customers, Disruption, finish run (opens its report) or Reports. |
| `components/NegotiationThread.tsx` | One negotiation as one card: the two agents, what and for which order (`order_label`), its status chip, and each step written by code from the message type and terms; the AI's sentence only under "AI wording". |
| `components/NewOrderPanel.tsx` | **＋ New order** (manual demo): product, quantity and deadline, sent as one `NEW_ORDER` trigger; the agents plan it at once, even while the clock is paused. |
| `components/CustomersPanel.tsx` | The simulated customers (`POST /simulation/settings`): new requests per day, structured or chat mode, quantity and lead-day ranges. |
| `components/Disruptions.tsx` | Fire a simulator trigger now (`POST /simulation/triggers`): worker absent, supplier delay, customer cancels or changes quantity, new customer request. The agents decide how to react. |
| `components/RunReport.tsx` | A finished run's report: orders, completed, on time, plans at risk, orders by status, triggers, AI calls, events published. |
| `components/scene/FactoryScene.tsx` | The living factory: materials warehouse, production hall (SMT and assembly lines with HR's workers; an absent worker is a faded red figure with a pin), finished-goods building, stock yards, docks (a red pin while a supplier delivery is late). Stock stacks follow stock on hand; lines glow while an order there has started; trucks and forklifts move only when the matching event arrives (FE-3). Click anything for its detail. |
| `components/scene/parts.tsx` | Low-poly models built from simple shapes (FE-2): building, truck, forklift, pallet, machine, worker, tree, map pin. |
| `components/AgentChat.tsx` | The agent conversation (FE-4), one window per order: an **All** tab (the whole factory feed) and a tab per order with its own **Customer ↔ Sales** chat and its own **Agent negotiation** channel (that order's negotiation messages and events, matched by the `refs` of `GET /observer/orders/{ref}`); filter (all / negotiations / events); minimise or widen. |
| `components/Overlays.tsx` | The detail card of what was clicked, disruptions and reactions (the last triggers and risk / repair events), order tracking (request → shipped), docks / lines / open negotiations. |
| `components/cockpit/Cockpit.tsx` | Status strip over the town: Running / Paused / Agents working / Handling disruption, day, active and at-risk orders, completed, stock; opens the two story views. |
| `components/cockpit/AgentBoard.tsx` | The six agents at a glance: status (Idle, Working, Waiting, Negotiating, Alert — defined in `lib/insight.ts`), what each waits for, latest action; agents of the newest disruption are outlined. |
| `components/cockpit/AgentDetail.tsx` | One agent's drawer: open negotiations, what it owns now (orders, lines, stock, deliveries, zones, workers; Sales figures from `/sales/dashboard/overview`), recent events and negotiation threads. |
| `components/cockpit/IncidentView.tsx` | Each disruption as BEFORE (the owner's event) → DURING (agents that reacted, real negotiation threads) → AFTER (Planning's plan events; "linked" only when ids match, otherwise "followed"; open negotiations shown as unresolved). |
| `components/cockpit/PlanCompare.tsx` | Committed plan (the `PlanCommitted` event) vs now (live orders), with every later plan event in words and a link to the order's full story. |
| `components/scene/buildings/` | The agent town: one building per agent around Planning, roads; clicking a building opens its agent; the newest disruption's agents get a pulsing ring. |
| `lib/insight.ts` | Read-only derivations for the cockpit from the live snapshot and the timeline: agent status, disruptions and what followed, plan comparison. Decides nothing and invents nothing. |
| `lib/api.ts` | Client for the backend (through `/backend`, forwarded by `next.config.mjs`) and the shapes it reads. |
| `lib/useLive.ts` | Polls `GET /observer/live` and the timeline cursor, one poll at a time. |
| `lib/agents.ts` | The six agents' names and colours; plain-words lines for messages and events. |

## Run

From the repository root in Git Bash: `bash scripts/demo_backend.sh` (local demo database, port 8000), then
`bash scripts/demo_frontend.sh` → http://localhost:3005 (see `scripts/README.md`). By hand: backend with
`DATABASE_URL` and `SIMULATION_DOOR_KEY` set (`uvicorn app.main:app`), frontend with
`NEXT_PUBLIC_SIMULATION_DOOR_KEY=<the same key> npm run dev`; another backend address: `BACKEND_URL=http://host:port`.
In the panel: pick a scenario, **Start scenario**, then **Next day** or **Play**. For a hand-made demo pick **MANUAL** (empty factory on day 1, no simulated customers), **Start scenario**, add each order with **＋ New order**, open its **📖 Story**, then **Play**.

With the database far away (Neon, another continent) a refresh takes a few seconds; the panel waits for one answer
before asking again.
