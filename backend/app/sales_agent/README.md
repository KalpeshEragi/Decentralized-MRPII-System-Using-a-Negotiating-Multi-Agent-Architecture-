# sales_agent

The Sales Agent. Design notes: `dev_docs/sales_agent/`. Built in checkpoints:

1. A test chat window where the tester talks to the language model, which behaves like a salesperson.
2. The database: the nine Sales Agent tables (migration `003`).
3. The read-only tools and the order-details check.
4. The conversation manager: chats are saved in the database, the model answers in a fixed format, and our code checks
   the answer. The agent collects product, quantity and delivery date. Planning is not connected yet: when all three
   are collected the manager only records a `READY_FOR_PLANNING` audit note.

| File | What it does |
| --- | --- |
| `prompts.py` | The Sales Agent's role and rules, the answer format, and the "situation" section, written as instructions for the language model. |
| `agent.py` | The model's "thinking" step: it answers in a fixed JSON format (`AgentTurn`). It only suggests; it saves and sends nothing. |
| `rules.py` | Plain checks, no database: order details (`check_order_details`), merging what the model found into what is collected (`merge_details`), checking the model's answer (`check_ai_output`), our own safe reply (`fallback_reply`), and phone number cleaning. The model suggests; this code decides. |
| `manager.py` | Runs one customer message: save it, load what is known, ask the model, check the answer (asking once more if needed, or using our own reply), and save the result. |
| `data_access.py` | The only code that reads and writes the Sales Agent tables. |
| `tools.py` | The five read-only tools: `get_customer_info`, `get_order_history`, `get_product_list`, `check_order_details`, `get_order_status`. They return plain data for the language model. |
| `models.py` | The nine tables as Python classes, in the `sales_agent` schema. They use their own base, so the demo reset (`/simulation/reset`) cannot delete Sales Agent data. |
| `seed.py` | Three placeholder test products. Safe to run twice. |
| `api.py` | Temporary test-channel door: the chat page, `POST /sales-test/chat`, and `GET` / `DELETE /sales-test/history/{phone}`. Replaced by the real API doors in a later checkpoint. |
| `test_channel/chat.html` | The test chat page (plain HTML and JavaScript). Open `/sales-test` while the backend runs. |

## Run it

Needs Ollama running with the model in `OLLAMA_MODEL` (default `qwen3.5:4b`), and the Sales Agent tables in the
database of `DATABASE_URL` (see below). From the repository root:

```
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8010
```

Then open `http://localhost:8010/sales-test`.

## Database

Create the tables in the database of `DATABASE_URL` (from `backend/`): `alembic upgrade head`. Add the test products:
`python -m app.sales_agent.seed`.

## Tests

From `backend/`: `python -m pytest tests/sales_agent` (20 tests). The plain-code tests and the model tests use a fake
model, so they do not need Ollama. The database tests in `tests/sales_agent/db/` need `TEST_DATABASE_URL` (a separate
database) and are skipped without it. Run only one test session at a time against the same test database.
