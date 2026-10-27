"""The event manager assistant (EM-4): a conversation about events — what an event does, who depends on it, how to
add, change or remove one safely, and what to do instead when a change would break something.

It is advisory only: it reads the catalogue, the handlers' own descriptions, the wiring report and the deterministic
checks (`manager.impact_of_removing`, `manager.check_new_event`) and explains them; it never changes code or the
catalogue (EM-2). The checks, not the model, decide what is allowed. When the model is down, the answer is built from
the same checks without it.
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.events import catalogue, manager
from app.llm.client import LLMClient, LLMError, OllamaClient
from app.observability.models import LlmCall

TIMEOUT_SECONDS = 120.0
MAX_HISTORY = 6
REMOVE = re.compile(r"\b(remove|delete|drop|retire|deprecate|stop|without|get rid)\b", re.I)
ADD = re.compile(r"\b(add|new|create|introduce|need an event|want an event)\b", re.I)

SYSTEM = (
    "You are the Event Manager of Decentra, a factory run by six agents (Sales, Planning, Inventory, Purchasing, "
    "Warehouse, HR) that talk through publish-subscribe events. You talk with the developer like a careful colleague: "
    "first make sure you understand what they want (ask one short question if it is unclear), then explain in plain "
    "words. Ground every statement in the catalogue, the handler descriptions and the check results given to you; "
    "never invent an event, field or agent. When a change would break something, say what breaks and propose a safer "
    "alternative. Give concrete steps (which file, what to change). You cannot change code yourself; the developer does "
    "it. Rules you must respect: one publisher per event (the agent that owns the fact); events announce facts that "
    "already happened (past-tense names); private negotiation messages are never events; removing an event goes "
    "DEPRECATED -> stop publishing -> RETIRED; every required subscriber needs a handler. Answer in short paragraphs or "
    "a short list, at most about 200 words."
)


def ask(db: Session, message: str, history: list[dict[str, str]] | None = None, focus: str | None = None,
        client: LLMClient | None = None) -> dict[str, Any]:
    """One turn of the conversation. Returns the answer, the facts it was grounded on, and who answered."""
    facts = _facts(message, focus)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "system", "content": "Facts for this question (JSON):\n" + json.dumps(facts, default=str)}]
    for turn in (history or [])[-MAX_HISTORY:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": str(turn["content"])[:2000]})
    messages.append({"role": "user", "content": message})
    started, outcome, answer = datetime.now(timezone.utc), "OK", None
    began = time.monotonic()
    try:
        answer = (client or OllamaClient.from_settings(reasoning_effort="none", timeout=TIMEOUT_SECONDS)).complete(
            messages).strip()
        if not answer:
            outcome = "INVALID"
    except LLMError as error:
        outcome = "TIMEOUT" if "timed out" in str(error).lower() else "ERROR"
    db.add(LlmCall(agent="EVENT_MANAGER", purpose="EVENT_ASSISTANT", case_id=None, queued_at=started,
                   started_at=started, finished_at=datetime.now(timezone.utc), outcome=outcome,
                   prompt_chars=sum(len(m["content"]) for m in messages),
                   output_chars=len(answer) if answer else None, model=get_settings().ollama_model))
    db.commit()
    if not answer:
        return {"answer": _without_model(facts), "by": "CHECKS", "facts": facts,
                "seconds": round(time.monotonic() - began, 1)}
    return {"answer": answer, "by": "MODEL", "facts": facts, "seconds": round(time.monotonic() - began, 1)}


def _facts(message: str, focus: str | None) -> dict[str, Any]:
    """The catalogue in brief, full details of the events in question, and the checks that apply."""
    named = [d.name for d in catalogue.DEFINITIONS if d.name.lower() in message.lower()]
    if focus and focus in catalogue.BY_NAME and focus not in named:
        named.insert(0, focus)
    details = {d["name"]: d for d in manager.definitions() if d["name"] in named}
    facts: dict[str, Any] = {
        "catalogue": [{"event": d.name, "publisher": d.publisher, "subscribers": list(d.subscribers),
                       "status": d.status if d.payload else "NOT_BUILT", "means": d.description}
                      for d in catalogue.DEFINITIONS],
        "wiring_report": manager.report(),
        "events_in_question": details,
    }
    if REMOVE.search(message):
        facts["if_removed"] = {n: manager.impact_of_removing(n) for n in named}
    proposed = [w for w in re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", message) if w not in catalogue.BY_NAME]
    if ADD.search(message) or proposed:
        agents = [a for a in manager.AGENTS if a.lower() in message.lower()]
        facts["new_event_checks"] = [manager.check_new_event(name, agents[0] if agents else "?", agents[1:])
                                     for name in proposed[:2]]
        facts["how_to_add"] = ("One EventDefinition with a Payload model and a STORY entry in "
                               "backend/app/events/catalogue.py; publish it from the owning agent in the same "
                               "transaction as the business change; a handler per subscriber registered with "
                               "channel.subscribe; run the tests.")
    return facts


def _without_model(facts: dict[str, Any]) -> str:
    """The same advice from the checks alone, when the model is not available."""
    parts = ["(The language model did not answer; this comes from the event checks.)"]
    for name, d in facts["events_in_question"].items():
        receivers = ", ".join(f"{s['agent']}" + ("" if s["handler"] else " (planned)") for s in d["subscribers"])
        parts.append(f"{name}: {d['explanation']} Published by {d['publisher']}; received by {receivers}.")
    for name, impact in facts.get("if_removed", {}).items():
        if impact.get("known"):
            losing = ", ".join(x["agent"] for x in impact["losing_input"]) or "nobody"
            parts.append(f"Removing {name} is {impact['risk']} risk: {losing} would lose input. Steps: "
                         + " ".join(f"{i}. {s}" for i, s in enumerate(impact["steps"], 1)))
    for check in facts.get("new_event_checks", []):
        verdict = "can be added" if check["ok"] else "cannot be added as proposed"
        parts.append(f"{check['name']} {verdict}. " + " ".join(check["problems"] + check["warnings"]))
    if len(parts) == 1:
        parts.append("Name an event (for example SupplierDeliveryDelayed) or describe the event you want to add.")
    return "\n\n".join(parts)
