"""Checkpoint 1 chat: one conversation per phone number, kept in memory, answered by the language model.

This is a first, temporary version. Nothing is saved to a database yet, so every conversation is lost when the
backend restarts. The database, tools and manager come in later checkpoints.
"""

from app.core.errors import AppError, ErrorCode
from app.llm.client import LLMClient, LLMError
from app.sales_agent.prompts import SALES_AGENT_SYSTEM_PROMPT

# The small model works better with a short history, so only the latest messages are sent to it.
MAX_HISTORY_MESSAGES = 20

# phone number -> the conversation so far, as a list of {"role": "user" | "assistant", "content": text}
_conversations: dict[str, list[dict[str, str]]] = {}


def get_history(phone: str) -> list[dict[str, str]]:
    """The messages of this customer's conversation (empty if there is none yet)."""
    return list(_conversations.get(phone, []))


def reset_conversation(phone: str) -> None:
    _conversations.pop(phone, None)


def reset_all_conversations() -> None:
    _conversations.clear()


def _build_model_messages(history: list[dict[str, str]], new_text: str) -> list[dict[str, str]]:
    """What the model receives: the rules first, then the recent history, then the new customer message."""
    recent_history = history[-MAX_HISTORY_MESSAGES:]
    return [
        {"role": "system", "content": SALES_AGENT_SYSTEM_PROMPT},
        *recent_history,
        {"role": "user", "content": new_text},
    ]


def chat(phone: str, text: str, llm_client: LLMClient) -> str:
    """Answer one customer message. The conversation is only updated if the model answered successfully."""
    history = get_history(phone)
    try:
        reply = llm_client.complete(_build_model_messages(history, text)).strip()
    except LLMError as error:
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "the language model is not available, please try again") from error
    if not reply:
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "the language model returned an empty answer, please try again")

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    _conversations[phone] = history
    return reply
