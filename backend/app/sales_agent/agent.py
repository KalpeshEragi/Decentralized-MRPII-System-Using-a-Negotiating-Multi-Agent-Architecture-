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


class AgentTurn(BaseModel):
    """What the model answers each turn."""

    model_config = ConfigDict(extra="ignore")

    reply: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_REPLY_LENGTH)]
    next_step: Literal["ask_more", "send_request", "select_option", "confirm_order", "decline", "pass_to_staff"]
    chosen_option: str | None = None  # the letter of the option the customer picked, with select_option
    details: Details = Details()
    reason: str = ""


def ai_understand_and_reply(llm_client: LLMClient, messages: list[dict[str, str]]) -> AgentTurn:
    """Ask the model and return its answer in the fixed format.

    If the answer is not valid JSON of the right shape, the model is asked once more. If it is still wrong,
    `StructuredOutputError` is raised. If the model cannot be reached, `LLMError` is raised.
    """
    return propose(llm_client, messages, AgentTurn, retries=1)
