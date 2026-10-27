# backend/app/events

The publish-subscribe event channel (`dev_docs/architecture/pubsub_event_channel.md`). It stores and delivers
facts; it never decides anything and never changes business data.

| File | Purpose |
| --- | --- |
| `models.py` | `Event` (the envelope, `events.events`), `EventDelivery` (one standard queue row per event and subscriber, `events.event_deliveries`), `EventVersionMixin` (for an agent's own `event_versions` table). |
| `catalogue.py` | The event manager's catalogue (EM-1): every event once — its story (`STORY`: what it means, caused by, leads to), publisher, subscribers (required = must have a handler, optional = planned), Pydantic payload model (unknown fields refused), description, version, status (`ACTIVE` / `DEPRECATED` / `RETIRED`), the decision that introduced it. Two events (`StockAvailabilityChanged`, `SupplierQuantityReduced`) have no publisher yet (payload `None` = not built). |
| `channel.py` | `CATALOGUE` (derived from `catalogue.py`), `subscribe` (only catalogue pairs; retired refused), `publish` (checks event, status, publisher and payload — EM-3: refused when `EVENT_PAYLOAD_CHECK=strict`, the test setting; logged loudly when `warn`, the demo default; stores the catalogue version in `schema_version`; event + deliveries in the caller's transaction, EV-2), `deliver` (the dispatcher's short-mode handler, EV-3), `is_newer` (stale check, EV-4), `dispatcher_registration`. |

## Rules

- Publish in the same transaction as the business change; never commit inside `publish`.
- Only subscribers with a registered handler get deliveries (an agent not built yet gets none).
- `scope_key` of a delivery = subscriber + entity, so one subscriber's events about one entity run in order and one
  subscriber's failure never blocks another.
- Handlers are quick and deterministic; slow work (AI, negotiation) is recorded as a work item of the agent.

| `manager.py` | Read-only views (EM-2): `definitions()` (catalogue as data: story, which handlers are registered and what each does — the first paragraph of the handler's own description — and the payload fields), `agents()` (per agent: publishes, handles, planned), `impact_of_removing(name)` and `check_new_event(...)` (deterministic checks), `report()` (required subscribers without a handler, handlers for unknown or retired events, events not built, deprecated events; logged at start by `core/workers.start_workers`), `stats(db)` (published count, last time, deliveries per subscriber and status). |
| `assistant.py` | The event manager assistant (EM-4): one conversation turn grounded in the catalogue, the handlers' descriptions, the wiring report and the checks below; advisory only; without the model the answer is built from the checks. Logged in `observability.llm_calls` (agent `EVENT_MANAGER`). |
| `api.py` | Doors: `GET /events/catalogue` (definitions with story and each receiver's reaction, per-agent lists, live numbers, report), `GET /events/report`, `GET /events/{name}/impact` (what removing it breaks, safe steps, alternatives), `POST /events/check` (a proposed new event against the rules), `POST /events/assistant` (talk with the assistant). Shown on the frontend page `/events`. |

## Adding, changing or removing an event

- **Add:** one `EventDefinition` (with its payload model) in `catalogue.py`, the publisher's `channel.publish` call, and
  each subscriber's `channel.subscribe` handler. Run the tests: the catalogue test checks the wiring.
- **Change the payload:** update the model and bump `version`; old stored events keep their `schema_version`.
- **Remove:** set `status=DEPRECATED` (still delivered, a warning on publish), stop publishing it, then `RETIRED`
  (publish and subscribe refused). Stored events stay readable.

**Tests:** `backend/tests/platform/test_event_channel.py`, `tests/core/test_event_catalogue.py` (wiring, payload checks,
refusals), `tests/platform/test_event_manager.py` (versions, live numbers, the door).
