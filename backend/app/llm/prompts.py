"""Prompt building for structured proposals, and the agent-specific task texts (Phase 3)."""

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


PURCHASING_TASK = (
    "You propose the Purchasing Agent's next step in a procurement negotiation with the supplier interface "
    "(at most 3 rounds). Before round 1, propose the first offer with action COUNTER_OFFER and terms "
    "(quantity, delivery_date), or REJECT if no supplier can cover the shortage. After a supplier response, "
    "ACCEPT the terms on the table, COUNTER_OFFER with new terms, or REJECT. Terms must stay within the limits: "
    "quantity between min_quantity and max_quantity, delivery_date between earliest_delivery and latest_delivery. "
    "required_date and priority are fixed by the shortage. Weigh quantity, delivery date, lead time, supplier "
    "availability and priority. Give a rationale of one or two short sentences."
)
