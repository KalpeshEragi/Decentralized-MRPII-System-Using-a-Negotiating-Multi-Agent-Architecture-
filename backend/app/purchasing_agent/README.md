# purchasing_agent

The new Purchasing Agent (schema `purchasing_agent`). Rules: `docs/agent_architectures/purchasing_agent_architecture.md`.
Tables: `docs/database_schema.md` §5.2. Test data: `docs/purchasing_agent_fixture.md`. Work plan: `.scratch/purchasing-agent/`.
The legacy `app/agents/purchasing` code and the legacy `purchasing` / `negotiation` schemas are not used.

Works with two sibling modules, each with its own schema and declarative base:
- `app/supplier_service/`: read-only supplier master data (items, suppliers, supplier items).
- `app/negotiation_engine/`: sessions, participants, messages, rounds, deadlines. No business decisions.

## Built so far (ticket 01, tracer)

A Procurement Request picks the best priced **single** supplier, creates one Leg (PENDING, with the price snapshot) and
one Engine session (OPEN), and sends a template OFFER (quantity and required date, never a price). Not yet: splits,
unpriced fallback, holds (effective availability), contract API, supplier chat, approval, LLM.

| File | What it does |
| --- | --- |
| `selection.py` | Pure decisions, no database or clock: contract price state on a date, best priced single supplier, why every option won or lost. |
| `service.py` | Orchestration in one transaction: idempotent intake, Supplier Service and contract reads, selection, Leg + Engine session + offer, audit. |
| `messages.py` | Template text and offer terms. |
| `views.py` | Read-only request view (Legs, negotiation, selection audit). |
| `api.py` | Routes only. Clock is a dependency (`get_clock`) so tests fix the date. |
| `models.py` | Tables. Logical references to the other two schemas (no database foreign keys). |
| `seed.py` | Resets the three new schemas and loads the fixture: `python -m app.purchasing_agent.seed` (uses `DATABASE_URL`). |

## API

| Route | What it does |
| --- | --- |
| `POST /purchasing/procurement-requests` | `request_ref`, `item_id`, `shortage_quantity`, `required_date`, `priority`, `requested_by`. `201` new; `200` + the existing request for a known `request_ref`. Unknown item / bad input: `422 VALIDATION_ERROR`. |
| `GET /purchasing/procurement-requests/{id}` | Status, split type, Legs with their negotiation (participants, messages), selection audit. |

## Settings

`PURCHASING_TIMEZONE` (default `Asia/Kolkata`; the selection date is today there), `PURCHASING_RESPONSE_DEADLINE_HOURS`
(24), `PURCHASING_MAX_ROUNDS` (3).
