"""The publish-subscribe event channel (dev_docs/architecture/pubsub_event_channel.md).

- `publish` writes the event and one delivery per *registered* subscriber in the caller's transaction (outbox, EV-2).
- Subscriptions are the static catalogue below (EV-6). An agent that is not built yet has no handler registered, so
  it gets no deliveries until it exists.
- `deliver` is the short-mode work-runner handler: it calls the subscriber's handler inside the same transaction that
  marks the delivery done (EV-3).
- `is_newer` is the stale check an agent runs against its own `event_versions` table (EV-4).

The channel stores and delivers; it never decides anything and never changes business data.
"""

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.work_runner import DONE, Registration, enqueue
from app.events.models import Event, EventDelivery

SALES, PLANNING, INVENTORY, PURCHASING, WAREHOUSE, HR = "SALES", "PLANNING", "INVENTORY", "PURCHASING", "WAREHOUSE", "HR"
SIMULATOR_CLOCK = "SIMULATOR_CLOCK"

# Event type -> (publisher, subscribers). pubsub_event_channel.md §8 (with RD-7, IN-2, WH-3, PB-3).
CATALOGUE: dict[str, tuple[str, tuple[str, ...]]] = {
    "OrderConfirmed": (SALES, (PLANNING,)),
    "OrderChangeRequested": (SALES, (PLANNING,)),
    "OrderCancelled": (SALES, (PLANNING,)),
    "PlanCommitted": (PLANNING, (SALES, INVENTORY, PURCHASING, WAREHOUSE, HR)),
    "PlanCommitFailed": (PLANNING, (SALES, INVENTORY, PURCHASING, WAREHOUSE, HR)),
    "PlanRevised": (PLANNING, (SALES, INVENTORY, PURCHASING, WAREHOUSE, HR)),
    "PlanAtRisk": (PLANNING, (SALES,)),
    "ProductionOrderReleased": (PLANNING, (WAREHOUSE, HR, INVENTORY)),
    "ProductionStarted": (PLANNING, (SALES, INVENTORY, WAREHOUSE)),
    "ProductionCompleted": (PLANNING, (SALES, WAREHOUSE)),
    "ReservationCommitted": (INVENTORY, (PLANNING,)),
    "ReservationReleased": (INVENTORY, (PLANNING,)),
    "StockAvailabilityChanged": (INVENTORY, (PLANNING,)),
    "SafetyStockBreached": (INVENTORY, (PLANNING,)),
    "ProcurementCommitted": (PURCHASING, (PLANNING, INVENTORY, WAREHOUSE)),
    "SupplierDeliveryDelayed": (PURCHASING, (PLANNING, INVENTORY, WAREHOUSE)),
    "SupplierQuantityReduced": (PURCHASING, (PLANNING, INVENTORY, WAREHOUSE)),
    "ReceivingSlotCommitted": (WAREHOUSE, (PURCHASING, PLANNING)),
    "MaterialReceived": (WAREHOUSE, (INVENTORY, PURCHASING, PLANNING)),
    "MaterialIssuedToProduction": (WAREHOUSE, (INVENTORY, PLANNING)),
    "FinishedGoodsStored": (WAREHOUSE, (INVENTORY, PLANNING, SALES)),
    "StorageCapacityChanged": (WAREHOUSE, (PLANNING, PURCHASING)),
    "ShipmentDispatched": (WAREHOUSE, (SALES, INVENTORY, PLANNING)),
    "WorkforceCommitted": (HR, (PLANNING,)),
    "WorkforceCapacityChanged": (HR, (PLANNING,)),
    "SimulatedDayStarted": (SIMULATOR_CLOCK, (PLANNING, INVENTORY, SALES, WAREHOUSE, HR)),
}

Handler = Callable[[Session, Event], str | None]  # returns DONE (or None) or IGNORED_STALE
_handlers: dict[tuple[str, str], Handler] = {}


def subscribe(subscriber: str, event_type: str, handler: Handler) -> None:
    """Register a subscriber's handler. Only pairs listed in the catalogue are allowed."""
    if event_type not in CATALOGUE or subscriber not in CATALOGUE[event_type][1]:
        raise ValueError(f"{subscriber} is not a subscriber of {event_type} in the catalogue")
    _handlers[(subscriber, event_type)] = handler


def unsubscribe_all() -> None:
    """Tests only."""
    _handlers.clear()


def publish(db: Session, *, event_type: str, publisher: str, entity_type: str, entity_id: str, entity_version: int,
            correlation_id: str, payload: dict | None = None, causation_id: uuid.UUID | None = None,
            occurred_at: datetime | None = None, event_id: uuid.UUID | None = None) -> Event:
    """Save one event and its deliveries in the caller's transaction (nothing is committed here)."""
    if event_type not in CATALOGUE:
        raise ValueError(f"unknown event type {event_type}")
    expected_publisher, subscribers = CATALOGUE[event_type]
    if publisher != expected_publisher:
        raise ValueError(f"{event_type} is published by {expected_publisher}, not {publisher}")
    event = Event(event_id=event_id or uuid.uuid4(), event_type=event_type, publisher=publisher,
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
