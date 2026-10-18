"""The model Purchasing uses runs without thinking (reasoning) mode: thinking makes qwen3.5:4b several times slower
and routine tasks (reading replies, wording messages, explaining a selection) don't need it. No model is called."""

import io
import json

from app.llm import client as llm_client_module
from app.purchasing_agent import api


def _sent_body(monkeypatch) -> dict:
    sent = {}

    def fake_urlopen(request, timeout):
        sent.update(json.loads(request.data))
        return io.StringIO(json.dumps({"choices": [{"message": {"content": "{}"}}]}))

    monkeypatch.setattr(llm_client_module.urllib.request, "urlopen", fake_urlopen)
    api.get_llm_client().complete([{"role": "user", "content": "ok, 500 by 20 Nov"}])
    return sent


def test_purchasing_model_calls_disable_thinking(monkeypatch):
    # Ollama's OpenAI-compatible endpoint turns thinking off with reasoning_effort "none".
    assert _sent_body(monkeypatch)["reasoning_effort"] == "none"
