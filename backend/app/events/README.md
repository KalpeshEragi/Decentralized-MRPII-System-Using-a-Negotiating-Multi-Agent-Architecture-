# backend/app/events

The publish-subscribe event channel (`dev_docs/architecture/pubsub_event_channel.md`). It stores and delivers
facts; it never decides anything and never changes business data.

| File | Purpose |
| --- | --- |
| `models.py` | `Event` (the envelope, `events.events`), `EventDelivery` (one standard queue row per event and subscriber, `events.event_deliveries`), `EventVersionMixin` (for an agent's own `event_versions` table). |
| `channel.py` | `CATALOGUE` (event type → publisher, subscribers; static, EV-6), `subscribe` (an agent registers its handler), `publish` (event + deliveries in the caller's transaction, EV-2), `deliver` (the dispatcher's short-mode handler, EV-3), `is_newer` (stale check, EV-4), `dispatcher_registration`. |

## Rules

- Publish in the same transaction as the business change; never commit inside `publish`.
- Only subscribers with a registered handler get deliveries (an agent not built yet gets none).
- `scope_key` of a delivery = subscriber + entity, so one subscriber's events about one entity run in order and one
  subscriber's failure never blocks another.
- Handlers are quick and deterministic; slow work (AI, negotiation) is recorded as a work item of the agent.

**Tests:** `backend/tests/platform/test_event_channel.py`.
