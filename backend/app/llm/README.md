# backend/app/llm

LLM proposer/helper layer (Phase 1). The LLM only proposes structured data; it never changes business state.

| File | Purpose |
| --- | --- |
| `client.py` | `LLMClient` protocol, `OllamaClient` (OpenAI-compatible endpoint, base URL and model from settings, `reasoning_effort="none"`), `FakeLLMClient`. |
| `reasoning.py` | `parse_structured` (strips `<think>` blocks and code fences, validates JSON), `propose` (one retry), `NegotiationProposal`. |
| `agents_spike.py` | OpenAI Agents SDK + Ollama compatibility spike (Phase 2): `build_proposer_agent` (configurable base URL / model, `ModelSettings(reasoning=Reasoning(effort="none"))`), `propose_with_agent` (reply is parsed and validated before use). Not one of the real agents. |
| `prompts.py` | `build_messages` and the system prompt (no price/cost). |

`OllamaClient` has not been run against a real Ollama; how no-reasoning mode is honoured is checked in the Phase 2 spike (D13).
Callers must run deterministic validation on a proposal before using it.
