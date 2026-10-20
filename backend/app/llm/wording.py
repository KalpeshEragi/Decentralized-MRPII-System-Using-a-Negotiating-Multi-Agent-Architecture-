"""AI wording of negotiation messages (IN-4, HR-4, WH-5, PL-4: the model writes words, never decisions).

The decision and its terms are made and committed by code first, with a template sentence. Just before the message is
sent (outbox, outside any lock) the model may reword it: it sees only the message type, the code-computed terms and the
reason code. Code checks the answer: every number and date in it must be one of the terms' numbers and dates. A wrong
answer is retried once; then the template stays. If the model is down nothing waits: the template is sent.

Every call is logged in `observability.llm_calls` without the prompt text (SD-3).
"""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm.client import LLMClient, LLMError, OllamaClient
from app.observability.models import LlmCall

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
MAX_CHARS = 300


def llm_client() -> LLMClient:
    """The shared model (one Ollama model for all agents). Tests replace this."""
    return OllamaClient.from_settings(timeout=30.0)


def allowed(terms: dict | None) -> tuple[set[str], set[Decimal]]:
    """The dates and numbers a sentence about these terms may contain."""
    dates, numbers = set(), set()

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                walk(key)
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)
        elif value is not None:
            text = str(value)
            dates.update(DATE.findall(text))
            for number in NUMBER.findall(DATE.sub(" ", text)):
                numbers.add(Decimal(number).normalize())

    walk(terms or {})
    return dates, numbers


def check(sentence: str, terms: dict | None) -> bool:
    """True when the sentence is short and every date and number in it comes from the terms."""
    if not sentence or len(sentence) > MAX_CHARS:
        return False
    dates, numbers = allowed(terms)
    if any(d not in dates for d in DATE.findall(sentence)):
        return False
    for number in NUMBER.findall(DATE.sub(" ", sentence)):
        try:
            if Decimal(number).normalize() not in numbers:
                return False
        except InvalidOperation:
            return False
    return True


def _prompt(agent: str, envelope: dict) -> list[dict[str, str]]:
    facts = {"message_type": envelope.get("message_type"), "terms": envelope.get("terms"),
             "reason_code": envelope.get("reason_code")}
    return [
        {"role": "system", "content": (
            f"You write the text of one negotiation message sent by the {agent.title()} agent of a factory. "
            "Write one or two short, polite sentences in plain English. Use only the facts given. Do not add, round "
            "or change any number or date; write dates exactly as YYYY-MM-DD. Do not mention prices. Reply with the "
            "sentences only.")},
        {"role": "user", "content": json.dumps(facts)},
    ]


def word(db: Session, envelope: dict, client: LLMClient | None = None) -> str:
    """The text to send: the model's sentence if it passes the check (one retry), else the template. Logs the call
    (outcome OK; FALLBACK_USED after two wrong answers; ERROR or TIMEOUT when the model could not answer)."""
    template = envelope.get("text") or ""
    agent, terms = envelope["sender"], envelope.get("terms")
    messages = _prompt(agent, envelope)
    started = datetime.now(timezone.utc)
    outcome, sentence = "FALLBACK_USED", template
    try:
        client = client or llm_client()
        for _ in range(2):
            answer = client.complete(messages).strip().strip('"')
            if check(answer, terms):
                outcome, sentence = "OK", answer
                break
    except (LLMError, TimeoutError) as error:
        outcome = "TIMEOUT" if "timed out" in str(error).lower() else "ERROR"
    db.add(LlmCall(agent=agent, purpose="WORDING", case_id=envelope.get("case_id"), queued_at=started,
                   started_at=started, finished_at=datetime.now(timezone.utc), outcome=outcome,
                   prompt_chars=sum(len(m["content"]) for m in messages),
                   output_chars=len(sentence) if outcome == "OK" else None, model=get_settings().ollama_model))
    return sentence
