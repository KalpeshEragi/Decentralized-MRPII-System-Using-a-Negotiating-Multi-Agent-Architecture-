# frontend

**Decentra** (working name, FE-5): the live control panel of the six-agent factory simulation. Next.js 15 + React 19,
with a 3D view in Three.js through React Three Fiber and drei (FE-1). The backend is the source of truth: the panel
only reads the observer doors and calls the simulation doors (FE-6); it decides nothing.

| Path | Purpose |
| --- | --- |
| `app/page.tsx` | The page: top bar, the 3D factory with floating cards, the agent conversation sidebar. |
| `components/TopBar.tsx` | Simulated day, Quiet / Working, why Play paused, the AI on/off switch (`ai_enabled`), Next day, Play / Pause, scenario picker and start, Disruption, finish run (opens its report) or Reports. |
| `components/Disruptions.tsx` | Fire a simulator trigger now (`POST /simulation/triggers`): worker absent, supplier delay, customer cancels or changes quantity, new customer request. The agents decide how to react. |
| `components/RunReport.tsx` | A finished run's report: orders, completed, on time, plans at risk, orders by status, triggers, AI calls, events published. |
| `components/scene/FactoryScene.tsx` | The living factory: materials warehouse, production hall (SMT and assembly lines with HR's workers; an absent worker is a faded red figure with a pin), finished-goods building, stock yards, docks (a red pin while a supplier delivery is late). Stock stacks follow stock on hand; lines glow while an order there has started; trucks and forklifts move only when the matching event arrives (FE-3). Click anything for its detail. |
| `components/scene/parts.tsx` | Low-poly models built from simple shapes (FE-2): building, truck, forklift, pallet, machine, worker, tree, map pin. |
| `components/AgentChat.tsx` | The agent conversation (FE-4): negotiation messages as a chat between agents, events and triggers as notices; filter (all / negotiations / events / one case); minimise or widen. |
| `components/Overlays.tsx` | KPI cards, the detail card of what was clicked, disruptions and reactions (the last triggers and risk / repair events), order tracking (request → shipped), docks / lines / open negotiations. |
| `lib/api.ts` | Client for the backend (through `/backend`, forwarded by `next.config.mjs`) and the shapes it reads. |
| `lib/useLive.ts` | Polls `GET /observer/live` and the timeline cursor, one poll at a time. |
| `lib/agents.ts` | The six agents' names and colours; plain-words lines for messages and events. |

## Run

Backend (from `backend/`, with `DATABASE_URL` and `SIMULATION_DOOR_KEY` set): `uvicorn app.main:app` (port 8000).
Frontend: `npm install` once, then `NEXT_PUBLIC_SIMULATION_DOOR_KEY=<the same key> npm run dev` → http://localhost:3000.
Another backend address: `BACKEND_URL=http://host:port`. In the panel: pick a scenario, **Start scenario**, then
**Next day** or **Play**.

With the database far away (Neon, another continent) a refresh takes a few seconds; the panel waits for one answer
before asking again.
