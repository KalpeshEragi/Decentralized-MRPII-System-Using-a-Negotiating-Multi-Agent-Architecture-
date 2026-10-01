# frontend

Next.js 15 + React 19 demo console for the SmartPhone X1 simulation (Phase 5). One page; the FastAPI backend is the
source of truth, and the UI only displays and forwards the tester's actions.

| Path | Purpose |
| --- | --- |
| `app/page.tsx` | The simulation page: controls, workflow stages, live activity, order/plan/MRP, supplier options, negotiations with the supplier response form, human approval, attempts, decision log, technical details. |
| `components/panels.tsx` | The page sections. |
| `lib/api.ts` | Typed client for the backend routes (C5 errors → friendly messages, timeouts). |
| `lib/useSimulation.ts` | State: loads everything from the backend; `run` executes one action at a time and polls the real decision log and negotiation status while it runs. |
| `lib/workflow.ts` | Labels for decision records and the workflow stage derived from backend state. |

## Run

Backend (from `backend/`, `DATABASE_URL` set): `uvicorn app.main:app` (port 8000; CORS allows `localhost:3000`).
Frontend: `npm install` once, then `npm run dev` → http://localhost:3000. Another backend URL: set `NEXT_PUBLIC_API_URL`.

No price/cost anywhere; the supplier is the Supplier Interface (the tester), not an agent.
