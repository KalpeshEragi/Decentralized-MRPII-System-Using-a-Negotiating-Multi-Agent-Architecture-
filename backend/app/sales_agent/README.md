# sales_agent

The Sales Agent. Design notes: `dev_docs/sales_agent/`. Built in checkpoints:

1. A test chat window where the tester talks to the language model, which behaves like a salesperson. The chat
   history is still kept in memory only.
2. The database: the nine Sales Agent tables exist (migration `003`), but nothing in the chat uses them yet.
3. The read-only tools and the order-details check. They are not connected to the chat yet (the manager comes next).

| File | What it does |
| --- | --- |
| `prompts.py` | The Sales Agent's role and rules, written as instructions for the language model. |
| `chat.py` | Keeps one conversation per phone number in memory and asks the model for the reply. |
| `models.py` | The nine tables as Python classes, in the `sales_agent` schema. They use their own base, so the demo reset (`/simulation/reset`) cannot delete Sales Agent data. |
| `seed.py` | Three placeholder test products. Safe to run twice. |
| `rules.py` | Plain checks, no database: is the product, quantity and date valid (`check_order_details`), and phone number cleaning. The language model only suggests details; this code decides. |
| `data_access.py` | The only code that reads the Sales Agent tables for the tools. Read-only for now. |
| `tools.py` | The five read-only tools: `get_customer_info`, `get_order_history`, `get_product_list`, `check_order_details`, `get_order_status`. They return plain data for the language model. |
| `api.py` | Temporary test-channel door: the chat page, `POST /sales-test/chat`, and `GET` / `DELETE /sales-test/history/{phone}`. Replaced by the real API doors in a later checkpoint. |
| `test_channel/chat.html` | The test chat page (plain HTML and JavaScript). Open `/sales-test` while the backend runs. |

## Run it

Needs Ollama running with the model in `OLLAMA_MODEL` (default `qwen3.5:4b`). From the repository root:

```
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8010
```

Then open `http://localhost:8010/sales-test`.

## Database

Create the tables in the database of `DATABASE_URL` (from `backend/`): `alembic upgrade head`. Add the test products:
`python -m app.sales_agent.seed`.

## Tests

From `backend/`: `python -m pytest tests/sales_agent`. The chat tests use a fake model, so they do not need Ollama. The
database tests in `tests/sales_agent/db/` need `TEST_DATABASE_URL` (a separate database) and are skipped without it.
