"""Prompt building for structured proposals. Agent-specific prompts are added with the agents (Phase 3)."""

import json

PROPOSAL_SYSTEM_PROMPT = (
    "You assist a manufacturing-planning agent in a negotiation. You only propose; deterministic services decide "
    "what is feasible. Negotiate on quantity, dates and priority only. Never mention or use price or cost. "
    "Reply with a single JSON object and nothing else."
)


def build_messages(task: str, context: dict, schema: dict) -> list[dict[str, str]]:
    """Chat messages asking for one JSON object matching `schema`, given deterministic `context`."""
    user = f"{task}\n\nContext:\n{json.dumps(context, default=str)}\n\nJSON schema of the reply:\n{json.dumps(schema)}"
    return [{"role": "system", "content": PROPOSAL_SYSTEM_PROMPT}, {"role": "user", "content": user}]
