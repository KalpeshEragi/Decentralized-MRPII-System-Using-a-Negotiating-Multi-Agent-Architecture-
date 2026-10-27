"""The shared think loop (QD-7, QD-11; `architecture/quotes_and_agent_decisions.md` §5.1–5.2, §6, §11).

At a decision point an agent describes its situation: its goal, the facts code gathered for it, the actions it may take
(with their parameters in words), optional hints, and a few extra facts it may look up. The model thinks and proposes
one action with its own parameters. Code checks the proposal with the agent's own `validate`; a refused proposal gets
one revision with the reason; anything that still fails — or no model at all — uses the agent's deterministic fallback.

Nothing here touches the database or holds a lock: the caller runs `think` outside any transaction and then records
and applies the result in a new one (`record.py`). The model never changes data; it only proposes.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.llm.client import LLMClient, LLMError
from app.llm.reasoning import StructuredOutputError, parse_structured

MAX_CALLS = 3  # first proposal + one lookup round + one revision (QD-11)

# Why the fallback decided instead of the model (decision record, design §6.1).
AI_OFF, TIMEOUT, ERROR, INVALID, NOT_VALID = "AI_OFF", "TIMEOUT", "ERROR", "INVALID", "NOT_VALID"


@dataclass
class Situation:
    """Everything the agent knows at one decision point. Facts come from code (trusted reads), never from free text."""

    agent: str                                   # SALES, PLANNING, INVENTORY, PURCHASING, WAREHOUSE, HR
    point: str                                   # decision point id, e.g. "D7"
    goal: str                                    # the agent's own goal and limits, in words
    facts: dict[str, Any]                        # gathered up front, so one call is usually enough
    actions: dict[str, str]                      # action name -> what it does and which params it takes
    hints: list[dict[str, Any]] = field(default_factory=list)  # code-built options (design §5): hints only
    lookups: dict[str, Callable[[], Any]] = field(default_factory=dict)  # extra facts the agent may ask for once
    case_id: str | None = None
    order_id: str | None = None


class Proposal(BaseModel):
    """What the model answers. Either asks for facts (once) or proposes one action."""

    thinking: str = Field(default="", max_length=4000)
    need_facts: list[str] = Field(default_factory=list)
    action: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=400)


@dataclass
class Call:
    """One model call, for the call log (`observability.llm_calls`)."""

    outcome: str          # OK, INVALID, TIMEOUT, ERROR
    seconds: float
    prompt_chars: int
    output_chars: int | None


@dataclass
class Decision:
    action: str
    params: dict[str, Any]
    chosen_by: str                       # MODEL, MODEL_REVISED or FALLBACK
    reason: str = ""
    thinking: str = ""
    fallback: tuple[str, dict[str, Any]] | None = None
    fallback_reason: str | None = None   # AI_OFF, TIMEOUT, ERROR, INVALID, NOT_VALID
    looked_up: dict[str, Any] = field(default_factory=dict)
    refusals: list[str] = field(default_factory=list)   # what the check said about refused proposals
    calls: list[Call] = field(default_factory=list)


# validate(action, params) -> None when the action is allowed now, else a short reason the model can act on.
Validator = Callable[[str, dict[str, Any]], str | None]


def think(situation: Situation, validate: Validator, fallback: tuple[str, dict[str, Any]],
          client: LLMClient | None) -> Decision:
    """Let the agent think and propose; return a checked decision. `client` None means AI is off."""
    if client is None:
        return _fallback(fallback, AI_OFF)
    messages = _prompt(situation)
    looked_up: dict[str, Any] = {}
    refusals: list[str] = []
    calls: list[Call] = []
    thinking = ""

    while len(calls) < MAX_CALLS:
        proposal, call = _ask(client, messages)
        calls.append(call)
        if proposal is None:
            return _fallback(fallback, call.outcome if call.outcome in (TIMEOUT, ERROR) else INVALID,
                             calls=calls, refusals=refusals, looked_up=looked_up, thinking=thinking)
        thinking = proposal.thinking or thinking
        wanted = [k for k in proposal.need_facts if k in situation.lookups and k not in looked_up]
        if proposal.action is None and wanted and not looked_up:  # one lookup round
            for key in wanted:
                looked_up[key] = _safe(situation.lookups[key])
            messages += [{"role": "assistant", "content": proposal.model_dump_json()},
                         {"role": "user", "content": "Facts you asked for: " + _json(looked_up)
                          + "\nNow propose one action as JSON."}]
            continue
        problem = _check(situation, validate, proposal)
        if problem is None:
            return Decision(proposal.action, proposal.params, "MODEL_REVISED" if refusals else "MODEL",
                            reason=proposal.reason, thinking=thinking, fallback=fallback, looked_up=looked_up,
                            refusals=refusals, calls=calls)
        refusals.append(problem)
        if len(refusals) > 1:  # one revision only
            break
        messages += [{"role": "assistant", "content": proposal.model_dump_json()},
                     {"role": "user", "content": f"The check refused that: {problem}. Propose a corrected action "
                                                 "as JSON, inside the limits."}]
    return _fallback(fallback, NOT_VALID, calls=calls, refusals=refusals, looked_up=looked_up, thinking=thinking)


def _check(situation: Situation, validate: Validator, proposal: Proposal) -> str | None:
    if not proposal.action:
        return "no action was proposed"
    if proposal.action not in situation.actions:
        return f"'{proposal.action}' is not one of your actions ({', '.join(situation.actions)})"
    try:
        return validate(proposal.action, proposal.params)
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:  # malformed params from the model
        return f"the parameters are not usable ({error.__class__.__name__}: {error})"


def _ask(client: LLMClient, messages: list[dict[str, str]]) -> tuple[Proposal | None, Call]:
    started = time.monotonic()
    prompt_chars = sum(len(m["content"]) for m in messages)
    try:
        raw = client.complete(messages)
    except LLMError as error:
        outcome = TIMEOUT if "timed out" in str(error).lower() else ERROR
        return None, Call(outcome, time.monotonic() - started, prompt_chars, None)
    try:
        proposal = parse_structured(raw, Proposal)
    except StructuredOutputError:
        return None, Call(INVALID, time.monotonic() - started, prompt_chars, len(raw))
    return proposal, Call("OK", time.monotonic() - started, prompt_chars, len(raw))


def _fallback(fallback: tuple[str, dict[str, Any]], why: str, *, calls: list[Call] | None = None,
              refusals: list[str] | None = None, looked_up: dict[str, Any] | None = None, thinking: str = "") -> Decision:
    action, params = fallback
    return Decision(action, params, "FALLBACK", reason="deterministic policy", thinking=thinking, fallback=fallback,
                    fallback_reason=why, looked_up=looked_up or {}, refusals=refusals or [], calls=calls or [])


def _safe(lookup: Callable[[], Any]) -> Any:
    try:
        return lookup()
    except Exception as error:  # a lookup is a read; its failure must not stop the decision
        return f"unavailable ({error.__class__.__name__})"


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _prompt(s: Situation) -> list[dict[str, str]]:
    system = (
        f"You are the {s.agent.title()} agent of a simulated factory. You decide for your own area only, using your "
        "goal and the facts given. Think step by step, then propose ONE action with its parameters. Use only numbers "
        "that follow from the facts; a separate check refuses anything outside your limits. If a fact you need is "
        "missing and listed under 'you may look up', ask for it once with need_facts instead of an action.\n"
        "Answer only with JSON: {\"thinking\": \"<your reasoning, short>\", \"need_facts\": [], "
        "\"action\": \"<one action name>\", \"params\": {...}, \"reason\": \"<one sentence for the team>\"}"
    )
    user = {
        "decision": s.point, "goal": s.goal, "facts": s.facts, "your_actions": s.actions,
        "hints_from_your_rules": s.hints, "you_may_look_up": sorted(s.lookups),
        "case": s.case_id, "order": s.order_id,
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": _json(user)}]
