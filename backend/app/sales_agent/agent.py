"""The Sales Agent's "thinking" step: the language model reads the conversation and answers in a fixed format.

The model only suggests. It saves nothing and sends nothing. Our code checks its answer (rules.py) before anything happens.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.llm.client import LLMClient
from app.llm.reasoning import propose

MAX_REPLY_LENGTH = 1000


class Details(BaseModel):
    """The order details the model believes it knows. Any of them can be unknown (null)."""

    model_config = ConfigDict(extra="ignore")

    product: str | None = None
    quantity: int | float | str | None = None  # the model may write 500 or "500"
    requested_date: str | None = None


class PreferenceSuggestion(BaseModel):
    """A preference the customer clearly asked for. Only types from the allowed list are ever saved (rules.py)."""

    model_config = ConfigDict(extra="ignore")

    type: str
    applies_to: Literal["always", "this_order"] = "always"


class AgentTurn(BaseModel):
    """What the model answers each turn."""

    model_config = ConfigDict(extra="ignore")

    reply: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_REPLY_LENGTH)]
    next_step: Literal["ask_more", "send_request", "pass_to_staff"]
    details: Details = Details()
    preference: PreferenceSuggestion | None = None
    reason: str = ""


class Decision(BaseModel):
    """How the model classified the customer's reply to the options we showed or to our confirmation question."""

    model_config = ConfigDict(extra="ignore")

    decision: Literal["choose", "yes", "no", "change", "question", "unclear"]
    option: str | None = None  # the letter of the chosen option, with "choose"


def ai_read_decision(llm_client: LLMClient, system_prompt: str, customer_text: str) -> Decision:
    """A small, separate question to the model with one job: classify the customer's reply. Our code decides what to do."""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": customer_text}]
    return propose(llm_client, messages, Decision, retries=1)


def ai_understand_and_reply(llm_client: LLMClient, messages: list[dict[str, str]]) -> AgentTurn:
    """Ask the model and return its answer in the fixed format.

    If the answer is not valid JSON of the right shape, the model is asked once more. If it is still wrong,
    `StructuredOutputError` is raised. If the model cannot be reached, `LLMError` is raised.
    """
    return propose(llm_client, messages, AgentTurn, retries=1)
