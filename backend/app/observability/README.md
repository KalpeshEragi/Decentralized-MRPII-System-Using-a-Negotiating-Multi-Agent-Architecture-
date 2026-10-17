# backend/app/observability

Measurements shared by all agents (`dev_docs/architecture/system_design.md` §7, §10).

| File | Purpose |
| --- | --- |
| `models.py` | `LlmCall` (`observability.llm_calls`, SD-3): one row per AI model call — agent, purpose, case, queued/started/finished times, outcome, sizes, model. No prompt text. Written by the agents once their AI steps are switched on (IMP-2). |
