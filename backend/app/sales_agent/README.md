# sales_agent

The Sales Agent. Design notes: `dev_docs/sales_agent/`. Only checkpoint 1 exists so far: a test chat window where the
tester talks to the language model, which behaves like a salesperson. Nothing is saved to a database yet.

| File | What it does |
| --- | --- |
| `prompts.py` | The Sales Agent's role and rules, written as instructions for the language model. |
| `chat.py` | Keeps one conversation per phone number in memory and asks the model for the reply. |
| `api.py` | Temporary test-channel door: the chat page, `POST /sales-test/chat`, and `GET` / `DELETE /sales-test/history/{phone}`. Replaced by the real API doors in a later checkpoint. |
| `test_channel/chat.html` | The test chat page (plain HTML and JavaScript). Open `/sales-test` while the backend runs. |

## Run it

Needs Ollama running with the model in `OLLAMA_MODEL` (default `qwen3.5:4b`). From the repository root:

```
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8010
```

Then open `http://localhost:8010/sales-test`.

Tests (no Ollama needed, they use a fake model): `python -m pytest tests/sales_agent` from `backend/`.
