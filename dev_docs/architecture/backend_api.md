# Backend API Design

**Status:** APPROVED by the developer (2026-10-17). Not built yet, except the standalone `/purchasing` routes (§ Purchasing).
Today the shared error handlers (`app/core/errors.py`) return the C5 error body `{"error": {code, message, details}}`.
**Related:** each agent's note 3 (doors), `system_design.md` (runner, security), `pubsub_event_channel.md`,
`negotiation.md` §10 (A2A), `../sales_agent/3_sales_agent_backend.md`.

## 1. Purpose

One place that lists every HTTP door of the backend and the rules all doors follow: paths, data formats, errors,
idempotency, polling, keys, and the read-only observer API for the demo frontend. Agent notes define what their doors
mean; this doc makes them consistent.

## 2. Decisions (2026-10-17)

| ID | Decision |
| --- | --- |
| API-1 | **New error format (future target, not built):** RFC 9457 Problem Details (`application/problem+json`) with our fixed error codes as an extension (§4). Replaces the current `{"error": {...}}` body everywhere, including the Sales Agent, during integration. |
| API-2 | The frontend sees changes by **polling** with a cursor (§6). |
| API-3 | Views spanning several agents come from a **read-only observer API** that decides nothing (§7). |
| API-4 | Old routes (`/orders`, `/plans`, `/negotiations`, `/agents`, `/simulation/reset`, old `/a2a/*` handlers) keep running until the Phase 2 review, then are removed with the old agents (§9). |

## 3. Conventions

| Topic | Rule |
| --- | --- |
| Paths | One prefix per owner: `/sales`, `/planning`, `/inventory`, `/warehouse`, `/hr`, `/purchasing` (later); infrastructure: `/a2a/<agent>`, `/events`, `/negotiations`, `/work`, `/simulation`, `/observer`. Plural nouns, lowercase, hyphens. |
| Body | JSON. Ids are UUID strings or the documented business refs. Quantities are decimal strings (no float rounding). |
| Dates | Business dates are simulated days `YYYY-MM-DD` (fields end in `_day` or `_date`); real times are UTC ISO 8601 (`..._at`). |
| No | Price, cost or priority fields anywhere. |
| Writes from machines | Always carry the caller's own id (`message_id`, `request_ref`, `report_id`, `delivery_id`, `absence_id`). Answer `202 {"status": "received" \| "duplicate", "ref": ...}` at once; the work runs in the background (SD-1). A duplicate is never an error. |
| Reads | `GET` only, never change anything. Lists use cursor paging: `?after=<cursor>&limit=<n>` (default 50, max 200) → `{"items": [...], "next_cursor": "..."}`. |
| Keys | Machine-to-machine doors require the header `X-Door-Key`, compared in constant time with that door's configured key; no key configured → nobody gets in. (Sales door 3 keeps `X-Planning-Key` until integration, then moves to `X-Door-Key`.) |
| Correlation | Every response carries `X-Correlation-Id` (taken from the request if given, otherwise new); it is written to audit rows and errors. |
| Docs | FastAPI's OpenAPI page (`/docs`) is the reference for shapes; contract tests check the shapes in this doc. |
| Versioning | None for the prototype (one frontend, one backend). |

## 4. Error format (API-1)

Standard: RFC 9457 "Problem Details for HTTP APIs" (IETF, 2023). Media type `application/problem+json`.

```json
{
  "type": "urn:mrpii:problem:business-rule-violation",
  "title": "Business rule violation",
  "status": 422,
  "detail": "The planning answer does not match the request.",
  "instance": "/sales/planning/results",
  "code": "BUSINESS_RULE_VIOLATION",
  "errors": [ { "field": "options[0].quantity", "issue": "must be greater than 0" } ],
  "correlation_id": "6f1c..."
}
```

| Field | Meaning |
| --- | --- |
| `type`, `title`, `status`, `detail`, `instance` | Standard RFC 9457 members; `type` = `urn:mrpii:problem:<code>` (API-5) |
| `code` | Our fixed code (extension) — the value code and tests check |
| `errors` | Field-level problems (extension), may be empty |
| `correlation_id` | Same as the `X-Correlation-Id` header (extension) |

| `code` | HTTP status |
| --- | --- |
| VALIDATION_ERROR | 422 |
| NOT_FOUND | 404 |
| CONFLICT | 409 |
| INVALID_STATE_TRANSITION | 409 |
| BUSINESS_RULE_VIOLATION | 422 |
| FORBIDDEN | 403 |
| SERVICE_UNAVAILABLE | 503 |
| INTERNAL_ERROR | 500 (no internals in `detail`) |

The codes are the existing ones (`core/errors.py`); only the body shape changes. What changes during integration:
`core/errors.py` (`error_body` and the handlers — one place for all routes), the Sales Agent tests that check error
bodies, and the frontend client (`frontend/lib/api.ts`) that reads errors. Contract first: this doc, then the code.

## 5. Door catalogue

Meaning of each door: the agent's note 3. Key column: **K** = `X-Door-Key` required.

### Sales (existing, `sales_agent/3_…`, Sales README)

| Door | Path | K |
| --- | --- | --- |
| 1 Customer message | `POST /sales/test-channel/messages` | |
| 2 New messages | `GET /sales/conversations/{id}/messages?after=` | |
| 3 Planning result | `POST /sales/planning/results` | K |
| 4–6 Views | `GET /sales/conversations/{id}`, `/sales/inquiries/{id}`, `/sales/customers[/{id}]` | |
| 8 Test reset | `POST /sales/test-channel/reset` | |
| 9 Simulated customers, structured (DM-7) | `POST /sales/simulated-customers/requests`, `GET .../inquiries/{id}`, `POST .../inquiries/{id}/accept`, `.../decline`, `POST .../orders/{number}/cancel`, `.../change` | K |
| 9 Sweep | `POST /sales/maintenance/sweep` | |

### Planning (`planning_agent/3_…`)

`POST /planning/requests` (K) · `POST /planning/shop-floor/reports` (K) · `POST /planning/setup` (K, demo §4) · `GET /planning/orders/{order_ref}` ·
`GET /planning/production-orders?status=` · `GET /planning/orders/{order_ref}/pegging` ·
`POST /planning/maintenance/regenerate-check`

### Inventory (`inventory_agent/3_…`)

`POST /inventory/setup` (K, demo §4) · `GET /inventory/items/{item_id}/atp?from=&to=` · `GET /inventory/items/{item_id}/position` ·
`GET /inventory/orders/{order_ref}/reservations` · `GET /inventory/items/{item_id}/ledger` ·
`POST /inventory/maintenance/reconcile`

### Warehouse (`warehouse_agent/3_…`)

`POST /warehouse/deliveries` (K) · `POST /warehouse/setup` (K, demo §4) · `POST /warehouse/capacity-changes` (K, demo §7) · `GET /warehouse/receiving?from=&to=` · `GET /warehouse/zones/{zone}/space?from=&to=` ·
`GET /warehouse/commitments/{ref}` · `GET /warehouse/ledger` · `POST /warehouse/maintenance/reconcile`

### HR (`hr_agent/3_…`)

`POST /hr/absences` (K) · `POST /hr/setup` (K) · `GET /hr/pools/{skill}?from=&to=` · `GET /hr/workers/{id}` ·
`GET /hr/production-orders/{id}/assignments` · `GET /hr/ledger` · `POST /hr/maintenance/reconcile`

### Purchasing

Later (Purchasing doc). The standalone Purchasing Agent (branch `purchasing-agent`) already serves `/purchasing/...`
routes, listed in `backend/app/purchasing_agent/README.md`; they use the current C5 error body, not RFC 9457 (API-1).

### A2A (negotiation, NG-1)

`/a2a/planning`, `/a2a/inventory`, `/a2a/warehouse`, `/a2a/hr`, `/a2a/purchasing` (later) — JSON-RPC `SendMessage`
of the official A2A SDK, agent card at `<path>/.well-known/agent-card.json`, store and acknowledge. Errors inside an
A2A exchange stay in the A2A acknowledgement (`accepted: false` + code); RFC 9457 applies to the plain HTTP doors.

### Infrastructure

| Door | Purpose |
| --- | --- |
| `GET /events?after=&type=&case=` | Event list (read-only) |
| `GET /events/{event_id}/deliveries` | Delivery status per subscriber |
| `GET /negotiations/{id}` | One negotiation with its messages (for the timeline; read-only) |
| `GET /work/failed?queue=` | FAILED work items of any queue |
| `POST /work/{queue}/{id}/retry` | Re-queue one FAILED item (K) |
| `/simulation/...` | Configuration, settings, starting states, clock, triggers, scenarios, checkpoints, runs — full list in `demo.md` §13 |

## 6. Polling (API-2)

- Lists that change (timeline, events, messages) return items in a fixed order (time, then id) with an opaque
  `next_cursor`. The frontend asks again with `?after=<next_cursor>` every 1–2 s.
- An empty answer is normal ("nothing new"). A cursor never skips or repeats an item.
- Views of one thing (an order overview) are simply re-read; they include a `version` so the frontend redraws only on
  change.

## 7. Observer API (API-3)

Read-only infrastructure for the frontend. It **decides nothing and writes nothing**; it only composes data that
already exists through agents' read modules (IB-2) and the infrastructure tables.

| Door | Returns |
| --- | --- |
| `GET /observer/orders?after=` | Orders with Sales stage, plan status, commitment and production state |
| `GET /observer/orders/{order_ref}` | One order's full story: inquiry, options, plan, pegs, holds/commitments per owner, production orders, shipments |
| `GET /observer/timeline?after=&case=` | One ordered stream: events, deliveries, negotiation messages, decisions (audit rows), AI calls (`llm_calls`), failed work items |
| `GET /observer/factory-state?day=` | Stock per item, space per zone, receiving, worker hours per skill, machine hours per work center — for one simulated day |
| `GET /observer/metrics?run=` | Phase 6 measurements (delivery lag, waiting, negotiation duration, AI call times) |

## 8. Security (prototype)

Local demo, no user login (SD security). Machine doors use `X-Door-Key`; views are for localhost; CORS allows only the
Next.js dev server. No real personal data.

## 9. Old routes (API-4)

| Old route | Replaced by |
| --- | --- |
| `/orders`, `/orders/overview`, `/orders/items/catalog` | Sales inquiries/orders + `/observer/orders` |
| `/plans/...` incl. approve/reject attempts | Planning doors + NG-4 execution policy (no human approval per plan) |
| `/negotiations`, `.../messages` | A2A doors (`.../supplier-responses` removed 2026-10-18) |
| `/agents/...` | Agents' own doors and `/observer` |
| `/supplier-interface/...` | Removed 2026-10-18; the supplier chat is the Purchasing test channel |
| `/simulation/reset` | `demo.md` |

They stay until the Phase 2 review, then are removed with the old agents, services and tables.

## 10. Open

| ID | Question |
| --- | --- |
| API-O1 | Resolved 2026-10-17 (API-5): `type` is a URN per code, `urn:mrpii:problem:<code in lowercase with hyphens>`. |
| API-O2 | Resolved 2026-10-17: `demo.md` §13. |
| API-O3 | Purchasing doors — Purchasing doc. |
