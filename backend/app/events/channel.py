"""The publish-subscribe event channel (dev_docs/architecture/pubsub_event_channel.md).

- `publish` writes the event and one delivery per *registered* subscriber in the caller's transaction (outbox, EV-2).
- Events, publishers, subscribers and payloads are the event catalogue (`catalogue.py`, EM-1); publish and subscribe are
  checked against it (EM-3). An agent that is not built yet has no handler registered, so
  it gets no deliveries until it exists.
- `deliver` is the short-mode work-runner handler: it calls the subscriber's handler inside the same transaction that
  marks the delivery done (EV-3).
- `is_newer` is the stale check an agent runs against its own `event_versions` table (EV-4).

The channel stores and delivers; it never decides anything and never changes business data.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.work_runner import DONE, Registration, enqueue
from app.events import catalogue
from app.events.models import Event, EventDelivery

SALES, PLANNING, INVENTORY, PURCHASING, WAREHOUSE, HR = "SALES", "PLANNING", "INVENTORY", "PURCHASING", "WAREHOUSE", "HR"
SIMULATOR_CLOCK = "SIMULATOR_CLOCK"
logger = logging.getLogger(__name__)

# Event type -> (publisher, subscribers), derived from the event catalogue (EM-1); retired events are left out.
CATALOGUE: dict[str, tuple[str, tuple[str, ...]]] = {
    d.name: (d.publisher, tuple(d.subscribers)) for d in catalogue.DEFINITIONS if d.status != catalogue.RETIRED}


class EventRefused(ValueError):
    """The event manager refused a publish or a subscription (unknown, retired, wrong publisher, bad payload)."""


def check_payload(event_type: str, payload: dict) -> str | None:
    """None when the payload matches the event's model, else what is wrong (EM-3)."""
    model = catalogue.BY_NAME[event_type].payload
    if model is None:
        return f"{event_type} has no payload definition yet (not built): define it in the catalogue first"
    try:
        model.model_validate(payload)
    except ValidationError as error:
        return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'payload'}: {e['msg']}" for e in error.errors())
    return None


Handler = Callable[[Session, Event], str | None]  # returns DONE (or None) or IGNORED_STALE
_handlers: dict[tuple[str, str], Handler] = {}


def subscribe(subscriber: str, event_type: str, handler: Handler) -> None:
    """Register a subscriber's handler. Only pairs listed in the catalogue are allowed; retired events are refused."""
    definition = catalogue.BY_NAME.get(event_type)
    if definition is None or subscriber not in definition.subscribers:
        raise EventRefused(f"{subscriber} is not a subscriber of {event_type} in the catalogue")
    if definition.status == catalogue.RETIRED:
        raise EventRefused(f"{event_type} is retired: nobody may subscribe to it")
    _handlers[(subscriber, event_type)] = handler


def unsubscribe_all() -> None:
    """Tests only."""
    _handlers.clear()


def publish(db: Session, *, event_type: str, publisher: str, entity_type: str, entity_id: str, entity_version: int,
            correlation_id: str, payload: dict | None = None, causation_id: uuid.UUID | None = None,
            occurred_at: datetime | None = None, event_id: uuid.UUID | None = None) -> Event:
    """Save one event and its deliveries in the caller's transaction (nothing is committed here)."""
    definition = catalogue.BY_NAME.get(event_type)
    if definition is None:
        raise EventRefused(f"unknown event type {event_type}")
    if definition.status == catalogue.RETIRED:
        raise EventRefused(f"{event_type} is retired and may not be published")
    if publisher != definition.publisher:
        raise EventRefused(f"{event_type} is published by {definition.publisher}, not {publisher}")
    if definition.status == catalogue.DEPRECATED:
        logger.warning("event %s is deprecated; publishers should stop sending it", event_type)
    if problem := check_payload(event_type, payload or {}):
        if get_settings().event_payload_check == "strict":
            raise EventRefused(f"{event_type} payload does not match the catalogue: {problem}")
        logger.error("EVENT PAYLOAD MISMATCH %s from %s: %s", event_type, publisher, problem)
    subscribers = tuple(definition.subscribers)
    event = Event(event_id=event_id or uuid.uuid4(), event_type=event_type, schema_version=definition.version,
                  publisher=publisher,
                  entity_type=entity_type, entity_id=str(entity_id), entity_version=entity_version,
                  correlation_id=correlation_id, causation_id=causation_id,
                  occurred_at=occurred_at or datetime.now(timezone.utc), payload=payload or {})
    db.add(event)
    db.flush()  # the deliveries reference the event row
    for subscriber in subscribers:
        if (subscriber, event_type) in _handlers:
            enqueue(db, EventDelivery, scope_key=f"{subscriber}:{entity_type}:{entity_id}", kind=event_type,
                    event_id=event.event_id, subscriber=subscriber)
    return event


def deliver(db: Session, delivery: EventDelivery) -> str:
    """Short-mode handler for one delivery: run the subscriber's handler in this transaction."""
    handler = _handlers.get((delivery.subscriber, delivery.kind))
    if handler is None:
        raise LookupError(f"no handler registered for {delivery.subscriber} / {delivery.kind}")
    return handler(db, db.get(Event, delivery.event_id)) or DONE


def is_newer(db: Session, versions_model: type, event: Event) -> bool:
    """Stale check against an agent's own `event_versions` table: True (and remembered) if this event's entity
    version is newer than the last one applied; False for an older or equal version (ignore the event)."""
    row = db.get(versions_model, (event.entity_type, event.entity_id), with_for_update=True)
    if row is not None and event.entity_version <= row.last_version:
        return False
    if row is None:
        db.add(versions_model(entity_type=event.entity_type, entity_id=event.entity_id,
                              last_version=event.entity_version))
    else:
        row.last_version = event.entity_version
    return True


def dispatcher_registration(workers: int = 4) -> Registration:
    return Registration(name="event-dispatcher", model=EventDelivery, handler=deliver, mode="short", workers=workers)
