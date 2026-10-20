# backend/app/llm

The shared language-model layer: one Ollama model for all agents (configured in `app/core/config.py`). The model only
proposes words or a choice among code-made alternatives; code checks every answer and falls back on any failure. It
never changes business state.

| File | Purpose |
| --- | --- |
| `client.py` | `LLMClient` protocol, `OllamaClient` (OpenAI-compatible endpoint, base URL and model from settings, `reasoning_effort="none"`, timeout), `FakeLLMClient` (scripted replies for tests). |
| `reasoning.py` | `parse_structured` (strips `<think>` blocks and code fences, validates JSON against a model), `propose` (one retry). |
| `wording.py` | Negotiation wording (IN-4, HR-4, WH-5, PL-4): the model rewords a message from its code-computed terms; every number and date must come from the terms (one retry, then the template). Used by the negotiation outbox just before sending, outside any lock, when the factory setting `ai_enabled` is 1. Logged in `observability.llm_calls` (SD-3). |

Other agents' own AI steps: Sales (`sales_agent/agent.py`, chat), Purchasing (`purchasing_agent/interpretation.py`,
`writer.py`), Planning's ranking (`planning_agent/ai.py`, PL-4).

**Tests:** `backend/tests/llm/test_structured_output.py`, `test_ai_steps.py` (wording fallback, AI choice checked).
