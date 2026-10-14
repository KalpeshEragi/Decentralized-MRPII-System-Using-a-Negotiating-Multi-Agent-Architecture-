# sales_agent

The Sales Agent. Design notes: `dev_docs/sales_agent/`. Built in checkpoints:

1. A test chat window where the tester talks to the language model, which behaves like a salesperson.
2. The database: the nine Sales Agent tables (migration `003`).
3. The read-only tools and the order-details check.
4. The conversation manager: chats are saved in the database, the model answers in a fixed format, and our code checks
   the answer. The agent collects product, quantity and delivery date. Planning is not connected yet: when all three
   are collected the manager only records a `READY_FOR_PLANNING` audit note.
5. The API doors: a message is accepted at once ("received"), the answer is produced in the background, duplicate
   deliveries are ignored, and messages that arrive while the agent is answering are answered together next.

| File | What it does |
| --- | --- |
| `prompts.py` | The Sales Agent's role and rules, the answer format, and the "situation" section, written as instructions for the language model. |
| `agent.py` | The model's "thinking" step: it answers in a fixed JSON format (`AgentTurn`). It only suggests; it saves and sends nothing. |
| `rules.py` | Plain checks, no database: order details (`check_order_details`), merging what the model found into what is collected (`merge_details`), checking the model's answer (`check_ai_output`), our own safe reply (`fallback_reply`), and phone number cleaning. The model suggests; this code decides. |
| `manager.py` | Two parts. `accept_message` (fast): save the message, skip duplicates. `process_conversation` (slow, in the background): one worker per conversation loads what is known, asks the model, checks the answer (asking once more if needed, or using our own reply) and saves the result. If the model is down the customer gets an apology and staff is flagged after two failures in a row. |
| `views.py` | What the read-only doors show: new messages, a conversation, an inquiry, a customer. Changes nothing. |
| `data_access.py` | The only code that reads and writes the Sales Agent tables. |
| `tools.py` | The five read-only tools: `get_customer_info`, `get_order_history`, `get_product_list`, `check_order_details`, `get_order_status`. They return plain data for the language model. |
| `models.py` | The nine tables as Python classes, in the `sales_agent` schema. They use their own base, so the demo reset (`/simulation/reset`) cannot delete Sales Agent data. |
| `seed.py` | Three placeholder test products. Safe to run twice. |
| `api.py` | The API doors (routes only). See the table below. |
| `test_channel/chat.html` | The test chat page (plain HTML and JavaScript). Open `/sales/test-channel` while the backend runs. |

## The doors

Door numbers follow `dev_docs/sales_agent/3_sales_agent_backend.md`. Door 3 (Planning result arrives) comes with the
fake Planning, and door 7 (health check) is the backend's existing `/health`.

| Door | Route | What it does |
| --- | --- | --- |
| 1 | `POST /sales/test-channel/messages` | A customer message goes in (`phone`, `message_id`, `text`). Answers `202` with `received` or `duplicate`; the reply comes later. |
| 2 | `GET /sales/conversations/{id}/messages?after=<message id>` | New messages of a conversation. The test page polls this for the reply. |
| 4 | `GET /sales/conversations/{id}` | A conversation, its stage and the collected details. |
| 5 | `GET /sales/inquiries/{id}` | An inquiry with its options. |
| 6 | `GET /sales/customers/{id}` or `GET /sales/customers?phone=` | A customer, saved notes and recent orders. |
| 8 | `POST /sales/test-channel/reset` | Closes every open test conversation (nothing is deleted). |
| page | `GET /sales/test-channel`, `GET` / `DELETE /sales/test-channel/history/{phone}` | The test chat page and its helpers. |

## Run it

Needs Ollama running with the model in `OLLAMA_MODEL` (default `qwen3.5:4b`), and the Sales Agent tables in the
database of `DATABASE_URL` (see below). From the repository root:

```
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8010
```

Then open `http://localhost:8010/sales/test-channel`.

## Database

Create the tables in the database of `DATABASE_URL` (from `backend/`): `alembic upgrade head`. Add the test products:
`python -m app.sales_agent.seed`.

## Tests

From `backend/`: `python -m pytest tests/sales_agent` (22 tests). The plain-code tests and the model tests use a fake
model, so they do not need Ollama. The database tests in `tests/sales_agent/db/` need `TEST_DATABASE_URL` (a separate
database) and are skipped without it. Run only one test session at a time against the same test database.

One backend process only: the lock that keeps two copies of a message apart, and the "busy" flag cleared at startup,
assume a single process.
