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
6. Planning and options: when the three details are collected the request goes to Planning (a FAKE Planning for now)
   and the agent waits. Planning's answer arrives at door 3; the agent explains the options, and our code checks that
   every date and number in the reply is one it was given.
7. Choosing and confirming: the customer picks an option, our own question repeats the exact quantity, date and
   "payment assumed", and only a clear "yes" to that question makes the order (guarded by code, see `rules.confirmation_problem`).
   Declining, an expired offer (24 hours) and a "yes" mixed with a change are handled without an order. Planning is
   sent a confirmation notice (the fake one keeps them).
8. Timeouts: a request Planning has not answered within 10 minutes is reported to the customer and staff once, by a
   manual sweep (`POST /sales/maintenance/sweep`, door 9; there are no timers). A late answer is still accepted.
   `tests/sales_agent/db/test_live_model.py` runs one whole order with the real model (`RUN_LIVE_MODEL=1`).

| File | What it does |
| --- | --- |
| `prompts.py` | The Sales Agent's role and rules, the answer format, and the "situation" section, written as instructions for the language model. |
| `agent.py` | The model's "thinking" step: it answers in a fixed JSON format (`AgentTurn`). It only suggests; it saves and sends nothing. |
| `rules.py` | Plain checks, no database: order details (`check_order_details`), merging what the model found into what is collected (`merge_details`), checking the model's answer (`check_ai_output`, including that every date and number in a reply is one it was given), our own safe reply (`fallback_reply`), and phone number cleaning. The model suggests; this code decides. |
| `manager.py` | Two parts (the model's choice, "yes" or "no" is acted on by `_decide`; replies about choosing and confirming are always our own words). `accept_message` (fast): save the message, skip duplicates. `process_conversation` (slow, in the background): one worker per conversation loads what is known, asks the model, checks the answer (asking once more if needed, or using our own reply) and saves the result. If the model is down the customer gets an apology and staff is flagged after two failures in a row. |
| `planning.py` | The contact point to Planning: the request Sales sends (`build_request`, no price and no priority), the answer shape (`PlanningResult`), the checks on an answer, our own wording for options, and `FakePlanning`, a FAKE Planning that answers by the quantity asked. |
| `structured.py` | The structured customer path (DM-7): a simulated customer's request, choice and "yes" arrive as data (channel `SIMULATED`). Only the language reading is skipped; the inquiry, the request to Planning, the order on a "yes" and the notice to Planning use `manager`'s own functions. Sales writes no chat replies for these conversations. Doors: `POST /sales/simulated-customers/requests`, `GET .../inquiries/{id}`, `POST .../inquiries/{id}/accept`, `.../decline`, and for confirmed orders `POST .../orders/{number}/cancel` (order CANCELLED, `OrderCancelled`) and `.../change` (`OrderChangeRequested`; the order keeps its quantity until Planning answers) (simulator key). |
| `reads.py` | Read module for other agents and the observer (IB-2): product SKU, inquiry status, active products, answered simulated inquiries. |
| `views.py` | What the read-only doors show: new messages, a conversation, an inquiry, a customer. Changes nothing. |
| `data_access.py` | The only code that reads and writes the Sales Agent tables. |
| `tools.py` | The five read-only tools: `get_customer_info`, `get_order_history`, `get_product_list`, `check_order_details`, `get_order_status`. They return plain data for the language model. |
| `models.py` | The nine tables as Python classes, in the `sales_agent` schema. They use their own base (`SalesAgentBase`), separate from the shared reference tables. |
| `seed.py` | Three placeholder test products. Safe to run twice. |
| `api.py` | The API doors (routes only). See the table below. |
| `test_channel/chat.html` | The test chat page (plain HTML and JavaScript). Open `/sales/test-channel` while the backend runs. |

## The doors

Door numbers follow `dev_docs/sales_agent/3_sales_agent_backend.md`. Door 7 (health check) is the backend's existing
`/health`.

| Door | Route | What it does |
| --- | --- | --- |
| 1 | `POST /sales/test-channel/messages` | A customer message goes in (`phone`, `message_id`, `text`). Answers `202` with `received` or `duplicate`; the reply comes later. |
| 2 | `GET /sales/conversations/{id}/messages?after=<message id>` | New messages of a conversation. The test page polls this for the reply. |
| 3 | `POST /sales/planning/results` | Planning's answer to a request. Needs the header `X-Planning-Key` equal to `SALES_PLANNING_KEY`; with no key set, nobody gets in. Answers `received`, `duplicate` or `ignored`. |
| 4 | `GET /sales/conversations/{id}` | A conversation, its stage and the collected details. |
| 5 | `GET /sales/inquiries/{id}` | An inquiry with its options. |
| 6 | `GET /sales/customers/{id}` or `GET /sales/customers?phone=` | A customer, saved notes and recent orders. |
| 8 | `POST /sales/test-channel/reset` | Closes every open test conversation (nothing is deleted). |
| 9 | `POST /sales/maintenance/sweep` | Reports requests Planning has not answered in time (customer message and staff flag, once each). |
| page | `GET /sales/test-channel`, `GET` / `DELETE /sales/test-channel/history/{phone}` | The test chat page and its helpers. |

## Trying the fake Planning

The fake Planning answers by the quantity the tester types (it is not the real Planning):

| Quantity | Planning's answer |
| --- | --- |
| up to 500 | the requested quantity by the requested date |
| 501 to 1000 | the full quantity 14 days later, or 500 by the requested date |
| 1001 to 5000 | the full quantity 30 days later |
| above 5000 | nothing feasible |
| 77 | a team member must look at it |
| 13 | never answers |

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

From `backend/`: `python -m pytest tests/sales_agent` (37 tests, plus one live-model test that is skipped by default). The plain-code tests and the model tests use a fake
model, so they do not need Ollama. The database tests in `tests/sales_agent/db/` need `TEST_DATABASE_URL` (a separate
database) and are skipped without it. Run only one test session at a time against the same test database.

One backend process only: the lock that keeps two copies of a message apart, and the "busy" flag cleared at startup,
assume a single process.
