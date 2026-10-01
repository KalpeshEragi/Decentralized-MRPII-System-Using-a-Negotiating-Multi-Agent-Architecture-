"""Structured-output parsing and validation. The LLM only proposes; nothing here mutates business state.

`propose` returns a validated model or raises `StructuredOutputError`. Callers must still run deterministic
validation (constraints, feasibility) on a proposal before acting on it.
"""

import json
import re
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.llm.client import LLMClient
from app.schemas.negotiation import OfferTerms

T = TypeVar("T", bound=BaseModel)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


class StructuredOutputError(Exception):
    """The model output is not valid JSON or does not match the expected schema."""


class NegotiationProposal(BaseModel):
    """What the LLM may propose for one negotiation step. No cost/price field; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["ACCEPT", "COUNTER_OFFER", "REJECT"]
    terms: OfferTerms | None = None
    rationale: str

    @model_validator(mode="after")
    def _counter_needs_terms(self) -> "NegotiationProposal":
        if self.action == "COUNTER_OFFER" and self.terms is None:
            raise ValueError("COUNTER_OFFER requires terms")
        return self


def parse_structured(raw: str, model: type[T]) -> T:
    """Strip reasoning blocks and code fences, parse one JSON object and validate it against `model`."""
    text = _THINK_BLOCK.sub("", raw).strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"output is not valid JSON: {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise StructuredOutputError(f"output does not match {model.__name__}: {exc}") from exc


def propose(client: LLMClient, messages: list[dict[str, str]], model: type[T], retries: int = 1) -> T:
    """Ask the model and return validated structured output; retry up to `retries` times on invalid output."""
    last_error: StructuredOutputError | None = None
    for _ in range(retries + 1):
        try:
            return parse_structured(client.complete(messages), model)
        except StructuredOutputError as exc:
            last_error = exc
    raise last_error  # type: ignore[misc]
