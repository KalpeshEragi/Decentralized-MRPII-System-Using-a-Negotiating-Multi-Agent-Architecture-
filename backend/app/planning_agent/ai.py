"""Planning's AI step (PL-4, planning_agent/2 §5): the model ranks code-generated alternatives and writes a short
rationale. It never creates an alternative or changes a number. Code checks the answer (`check_ai_choice`): a key that
does not pass the filters, a malformed answer or no answer -> the fixed ranking (PL-6) decides.

Called outside any database lock (long-mode work item). Every call is logged in `observability.llm_calls` (SD-3).
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm.client import LLMClient, LLMError, OllamaClient
from app.llm.reasoning import StructuredOutputError, propose
from app.mrpii.ranking import Alternative
from app.observability.models import LlmCall


class RankingAnswer(BaseModel):
    chosen_key: str
    rationale: str = Field(max_length=300)


def llm_client() -> LLMClient:
    """The shared model. Tests replace this."""
    return OllamaClient.from_settings(timeout=60.0)


def _prompt(goal: str, alternatives: list[Alternative]) -> list[dict[str, str]]:
    table = [{k: str(v) for k, v in asdict(a).items()} for a in alternatives]
    return [
        {"role": "system", "content": (
            "You are the Planning agent of a factory. Choose the best way to reach the goal from the alternatives "
            "given. Prefer: no changes to protected orders, the full quantity on time, the least disruption, the "
            "fewest extra resources, the earliest completion. Answer only with JSON: "
            '{"chosen_key": "<one key from the list>", "rationale": "<one short sentence, no new numbers>"}')},
        {"role": "user", "content": json.dumps({"goal": goal, "alternatives": table})},
    ]


def rank_with_ai(db: Session, case_id: str | None, goal: str, alternatives: list[Alternative],
                 client: LLMClient | None = None) -> tuple[str | None, str | None]:
    """(chosen key, rationale) from the model, or (None, None) when it could not answer. Logs the call."""
    messages = _prompt(goal, alternatives)
    started, outcome, answer = datetime.now(timezone.utc), "OK", None
    try:
        answer = propose(client or llm_client(), messages, RankingAnswer, retries=1)
    except StructuredOutputError:
        outcome = "INVALID"
    except LLMError as error:
        outcome = "TIMEOUT" if "timed out" in str(error).lower() else "ERROR"
    db.add(LlmCall(agent="PLANNING", purpose="PLANNING_RANKING", case_id=case_id, queued_at=started,
                   started_at=started, finished_at=datetime.now(timezone.utc), outcome=outcome,
                   prompt_chars=sum(len(m["content"]) for m in messages),
                   output_chars=len(answer.rationale) if answer else None, model=get_settings().ollama_model))
    return (answer.chosen_key, answer.rationale) if answer else (None, None)
