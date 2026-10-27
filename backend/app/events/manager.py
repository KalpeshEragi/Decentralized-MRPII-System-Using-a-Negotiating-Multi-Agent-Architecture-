"""The event manager's views (EM-1, EM-2): the catalogue as data, the wiring report and live numbers. Read-only.

- `definitions()`  every event with publisher, subscribers (required/optional, handler registered or not), payload
                   fields from its model, description, version, status
- `report()`       what does not fit: required subscribers without a handler, handlers for events not in the catalogue
                   or retired, events not built yet, deprecated events
- `stats(db)`      per event: published count, last published, deliveries per subscriber and status
"""

import inspect
import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.events import catalogue, channel
from app.events.models import Event, EventDelivery

logger = logging.getLogger(__name__)


def _handlers() -> set[tuple[str, str]]:
    """(subscriber, event) pairs with a registered handler; registers the agents first when nothing is registered yet
    (an API process without background workers)."""
    if not channel._handlers:
        from app.core import workers

        if not workers.runner.registrations:
            workers.register_all()
    return set(channel._handlers)


def _fields(model: type[catalogue.Payload] | None) -> list[dict[str, Any]]:
    if model is None:
        return []
    schema = model.model_json_schema()
    required = set(schema.get("required", []))
    return [{"name": name, "required": name in required, "type": _type(spec)}
            for name, spec in schema.get("properties", {}).items()]


def _type(spec: dict) -> str:
    if "type" in spec:
        return spec["type"]
    return " | ".join(sorted({o.get("type", "any") for o in spec.get("anyOf", [])})) or "any"


def reaction(agent: str, event: str) -> str | None:
    """What the subscriber does with the event: the first paragraph of its handler's description (from the code)."""
    handler = channel._handlers.get((agent, event))
    if handler is None:
        return None
    doc = (inspect.getdoc(handler) or "").split(2 * chr(10))[0]  # first paragraph
    return " ".join(doc.split()) or f"handled by {handler.__module__}.{handler.__name__}"


def definitions() -> list[dict[str, Any]]:
    handlers = _handlers()
    return [{
        "name": d.name, "publisher": d.publisher, "description": d.description, "version": d.version,
        "status": d.status, "decided_in": d.decided_in, "notes": list(d.notes), "built": d.payload is not None,
        "explanation": d.explanation, "caused_by": list(d.caused_by), "leads_to": list(d.leads_to),
        "subscribers": [{"agent": agent, "required": required, "handler": (agent, d.name) in handlers,
                         "reaction": reaction(agent, d.name)} for agent, required in d.subscribers.items()],
        "payload": _fields(d.payload),
    } for d in catalogue.DEFINITIONS]


AGENTS = ("SALES", "PLANNING", "INVENTORY", "PURCHASING", "WAREHOUSE", "HR", catalogue.SIMULATOR_CLOCK)


def agents() -> list[dict[str, Any]]:
    """Per agent: the events it publishes, the events it handles, and the ones it is listed for but does not handle."""
    handlers = _handlers()
    return [{"agent": a,
             "publishes": [d.name for d in catalogue.DEFINITIONS if d.publisher == a],
             "handles": [d.name for d in catalogue.DEFINITIONS if (a, d.name) in handlers],
             "planned": [d.name for d in catalogue.DEFINITIONS if a in d.subscribers and (a, d.name) not in handlers]}
            for a in AGENTS]


# -- impact analysis: what removing an event breaks, what a new event must respect ---------------------------------------


def impact_of_removing(name: str) -> dict[str, Any]:
    """Who loses what if `name` is removed, which chains stop, and the safe way to do it. Deterministic."""
    d = catalogue.BY_NAME.get(name)
    if d is None:
        return {"event": name, "known": False, "problems": [f"{name} is not in the catalogue"]}
    handlers = _handlers()
    losing = [{"agent": a, "reaction": reaction(a, name)} for a in d.subscribers if (a, name) in handlers]
    only_cause = [e for e in d.leads_to
                  if [c for c in catalogue.BY_NAME[e].caused_by if c in catalogue.BY_NAME] == [name]]
    feeds = [e for e in d.caused_by if e in catalogue.BY_NAME]
    risk = "high" if losing and any(d.subscribers[x["agent"]] for x in losing) else "medium" if losing else "low"
    steps = [f"Set status DEPRECATED in catalogue.py (it keeps being delivered; publishing logs a warning).",
             f"Change {d.publisher}'s code to stop publishing it."]
    steps += [f"Give {x['agent']} another source for what it does today: {x['reaction']}" for x in losing]
    steps += ["Run the tests (the catalogue test checks the wiring), then set status RETIRED and remove the "
              "handlers. Stored events stay readable."]
    alternatives = ["Keep the event; if only one subscriber no longer needs it, remove that subscriber's handler and "
                    "mark only that subscriber optional (the others keep working).",
                    "Change its payload instead (bump the version) if the content is what is wrong.",
                    "Leave it DEPRECATED for a while so the publisher's warnings show who still sends it."]
    return {"event": name, "known": True, "publisher": d.publisher, "risk": risk, "losing_input": losing,
            "chains_stopped": only_cause, "caused_by_events": feeds, "steps": steps, "alternatives": alternatives}


_PAST = re.compile(r"(ed|Started|Released|Dispatched|Stored|Received|Changed|Breached|Reduced|Delayed|Needed)$")


def check_new_event(name: str, publisher: str, subscribers: list[str], fields: list[str] | None = None) -> dict:
    """Checks a proposed new event against the catalogue's rules. Deterministic; nothing is changed."""
    problems, warnings = [], []
    if name in catalogue.BY_NAME:
        problems.append(f"{name} already exists (published by {catalogue.BY_NAME[name].publisher}).")
    if not re.fullmatch(r"[A-Z][A-Za-z]+", name or ""):
        problems.append("Event names are PascalCase words, e.g. ReplenishmentNeeded.")
    elif not _PAST.search(name):
        warnings.append("An event announces a fact that already happened: a past-tense name (…Changed, …Released, "
                        "…Needed) reads better than a command.")
    if publisher not in AGENTS:
        problems.append(f"Publisher {publisher} is not an agent ({', '.join(AGENTS)}).")
    unknown = [s for s in subscribers if s not in AGENTS]
    if unknown:
        problems.append(f"Unknown subscribers: {', '.join(unknown)}.")
    if publisher in subscribers:
        warnings.append("The publisher should not subscribe to its own event: it already knows the fact.")
    if not subscribers:
        warnings.append("Nobody subscribes: an event nobody handles only fills the table.")
    words = set(re.findall(r"[A-Z][a-z]+", name or ""))
    similar = [d.name for d in catalogue.DEFINITIONS
               if d.publisher == publisher and len(words & set(re.findall(r"[A-Z][a-z]+", d.name))) >= 1]
    if similar:
        warnings.append(f"{publisher} already publishes similar events: {', '.join(similar)}. Check whether one of "
                        "them (with an extra payload field) is enough.")
    if fields is not None and not fields:
        warnings.append("List the payload fields; each subscriber should find what it needs without reading another "
                        "agent's data.")
    steps = [f"Add an EventDefinition '{name}' with a Payload model to backend/app/events/catalogue.py "
             "(publisher, subscribers required/optional, description, STORY entry).",
             f"Publish it from {publisher}'s code in the same transaction as the business change.",
             *[f"Write {s}'s handler and register it with channel.subscribe in its register()." for s in subscribers],
             "Run the tests; the catalogue test fails until every required subscriber has a handler."]
    return {"name": name, "ok": not problems, "problems": problems, "warnings": warnings, "steps": steps}


def report() -> dict[str, list[str]]:
    """What does not fit between the catalogue and the registered handlers. Empty lists = all wired."""
    handlers = _handlers()
    missing, unknown, not_built, deprecated, retired_handlers = [], [], [], [], []
    for d in catalogue.DEFINITIONS:
        for agent, required in d.subscribers.items():
            if required and (agent, d.name) not in handlers:
                missing.append(f"{agent} must handle {d.name} but has no handler")
        if d.payload is None:
            not_built.append(f"{d.name}: {', '.join(d.notes) or 'no payload definition'}")
        if d.status == catalogue.DEPRECATED:
            deprecated.append(d.name)
    for agent, event in sorted(handlers):
        definition = catalogue.BY_NAME.get(event)
        if definition is None:
            unknown.append(f"{agent} handles {event}, which is not in the catalogue")
        elif definition.status == catalogue.RETIRED:
            retired_handlers.append(f"{agent} still handles retired {event}")
    return {"missing_handlers": missing, "unknown_events": unknown, "retired_handlers": retired_handlers,
            "not_built": not_built, "deprecated": deprecated}


def log_report() -> None:
    """Start-up check: problems as warnings, the not-yet-built events as one info line."""
    found = report()
    for key in ("missing_handlers", "unknown_events", "retired_handlers"):
        for line in found[key]:
            logger.warning("event catalogue: %s", line)
    if found["deprecated"]:
        logger.warning("event catalogue: deprecated events still defined: %s", ", ".join(found["deprecated"]))
    if found["not_built"]:
        logger.info("event catalogue: not built yet: %s", "; ".join(found["not_built"]))


def stats(db: Session) -> dict[str, dict[str, Any]]:
    """Live numbers from the events and deliveries tables (two queries)."""
    published = {t: {"published": n, "last_published": last.isoformat() if last else None, "deliveries": {}}
                 for t, n, last in db.execute(select(Event.event_type, func.count(), func.max(Event.published_at))
                                              .group_by(Event.event_type))}
    for event_type, subscriber, status, n in db.execute(
            select(EventDelivery.kind, EventDelivery.subscriber, EventDelivery.status, func.count())
            .group_by(EventDelivery.kind, EventDelivery.subscriber, EventDelivery.status)):
        entry = published.setdefault(event_type, {"published": 0, "last_published": None, "deliveries": {}})
        entry["deliveries"].setdefault(subscriber, {})[status] = n
    return published
