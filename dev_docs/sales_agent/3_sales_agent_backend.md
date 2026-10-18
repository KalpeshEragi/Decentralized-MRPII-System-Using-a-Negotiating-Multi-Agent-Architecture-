# Sales Agent: Backend Design

**Status:** design notes, decisions confirmed by the developer (2026-10-14). Implemented in `backend/app/sales_agent/` (see its `README.md`; Planning is still a fake connector).
**Assumed stack:** FastAPI backend, PostgreSQL on Neon (as in the existing project).
**Related notes:** `1_sales_agent_high_level_architecture.md`, `2_sales_agent_functions.md`, `4_sales_agent_database.md`.

## A. Layers

| # | Layer | Job |
| --- | --- | --- |
| 1 | API doors (entrance) | Receives the customer message, checks the basic shape, says "received" fast, later sends replies out |
| 2 | Conversation manager | Runs all steps for one message |
| 3 | Sales AI | `ai_understand_and_reply`. Only thinks. Saves nothing, sends nothing. |
| 4 | Rules | check_ai_output, check_order_details, stage rules, reply checker |
| 5 | Tool handler | Runs the allowed tools only |
| 6 | Data access | The only layer that reads and writes the database |
| 7 | Connectors | AI model connector, Planning connector (fake now, real later), channel sender |
| Side | Audit, settings, error handling | |

Rule: the AI talks only to the Manager, never to the database or Planning directly.

Diagram text (box title / subtitle):
- Customer: test channel now. Operation team: view only. Planning: fake for now.
- 1 API doors: 8 doors, WhatsApp later. 2 Conversation manager: runs every step. 3 Sales AI: suggests, never acts. 4 Rules: validation checks.
- 5 Tool handler: runs allowed tools only. 6 Data access: only layer using database. 7 Connectors: link to outside. Database: Sales-owned only.
- Outside world: AI model, Planning (fake), Customer channel.

Arrow labels: 1 message / get replies; 2 view only; 3 planning result; 4 accepted request; 5 check this / OK or problem; 6 messages + context / reply + suggested step; 7 run this step; 8 call outside; 9 read / save; 10 read / write; 11 AI call, Planning request, reply to customer.

## B. API doors (endpoints)

| # | Door | Who | Takes | Returns |
| --- | --- | --- | --- | --- |
| 1 | Send a message | Customer (test channel) | Phone number, message id, text, time | "Received" + conversation id (fast) |
| 2 | Get new messages | Test channel page | Conversation id, after which message | New messages |
| 3 | Planning result arrives | Planning / fake Planning | Request id + options, "nothing feasible", or "still working" | "Received" |
| 4 | View a conversation | Our team | Conversation id | Messages, stage, collected details |
| 5 | View an inquiry | Our team | Inquiry id | Request, options, choice, status |
| 6 | View a customer | Our team | Customer id or phone | Info, preferences, insights |
| 7 | Health check | Anyone | Nothing | "OK" |
| 8 | Reset test data | Us | Nothing | "Done" |
| Later | WhatsApp door | WhatsApp | Its own format + its own security check | Same core as door 1 |

Outgoing calls (not doors): send request to Planning, send confirmation notice, send reply to the customer.

Error kinds: wrong format; not found; already done (a duplicate is answered "OK, already have it", not as an error); not allowed (wrong secret key on door 3); our fault.

## C. Functions (plumbing)

**Manager:** accept_message (skip duplicates, save, find or create the conversation, start background work, answer "received"); process_conversation (take all unanswered messages together, lock the conversation, run a turn, send the reply); run_turn (load -> AI -> check -> act -> save -> reply); build_ai_input; apply_next_step; advance_stage; handle_planning_result; close_inquiry; expire_old_inquiries (lazy check when a message arrives, plus a manual sweep).

**Rules and checks:** check_ai_output; check_order_details; check_reply_values (every date and number must come from Planning's options or the customer); is_action_allowed (which step in which stage); is_confirmation_valid; is_offer_expired.

**Tools:** see `2_sales_agent_functions.md`, section 4.

**Data access:** find_customer_by_phone, create_customer, get_or_create_conversation, save_message, get_recent_messages, save_conversation_state, create_inquiry, save_options, save_selection, save_confirmation, get_orders_for_customer, save_preference, list_preferences, save_insight, list_insights, save_audit_note.

**Connectors:** call_ai_model; read_structured_answer (retry once); send_to_channel (the test channel stores the reply for door 2); planning_connector (send request, send confirmation notice; fake now); fake_planning (scripted: feasible, later date, smaller quantity, nothing feasible, still working, no answer).

**Other:** update_insights (after each confirmed order, fixed rules, can revise or retire an insight); load_settings; write_audit.

## D. Flows

### Stages of an inquiry (lean version, 7 stages)

GATHERING -> WAITING_FOR_PLANNING -> OPTIONS_PRESENTED -> AWAITING_CONFIRMATION -> CONFIRMED.
Side stages: NEEDS_STAFF; CLOSED with `closed_reason` in NO_OPTION, DECLINED, EXPIRED, ABANDONED, REPLACED.
A change of request starts a new inquiry; the old one is CLOSED (REPLACED).

### Flow 1: customer message
1. Door 1 receives the message. 2. accept_message: duplicate? save, answer "received".
3. Background: process_conversation locks the conversation and collects all unanswered messages.
4. run_turn loads state and the customer summary. 5. build_ai_input -> ai_understand_and_reply.
6. check_ai_output. 7. If details are complete, check_order_details; if not valid, ask the customer; if valid, send_request_to_planning and move to WAITING_FOR_PLANNING.
8. check_reply_values, then the reply goes out. Everything saved, audit note written.

### Flow 2: Planning answers
Door 3 (secret key checked) -> handle_planning_result stores options, stage OPTIONS_PRESENTED -> a turn runs: the AI explains the options, check_reply_values verifies every date and number, reply sent.

### Flow 3: choose and confirm
Customer picks -> record_selected_option -> the AI repeats product, quantity, date and "payment assumed" -> AWAITING_CONFIRMATION.
Customer says yes -> is_confirmation_valid must pass -> record_confirmation -> confirmed order saved, notice sent to Planning, customer told -> CONFIRMED.
Anything unclear -> ask again. A change -> new inquiry.

### Waiting and expiry
Messages that arrive while a turn runs are kept and handled together in the next turn. Offers have a valid-until time; a late "yes" gets "this offer has expired, let me check again". Expiry is lazy plus a manual sweep (there are no timers).

## E. Data shapes (bold = required)

- **Incoming message:** channel, sender phone, message id, text, time.
- **Conversation state:** conversation id, customer id (may be empty), stage, collected details (each may be missing), current inquiry id, time of last message.
- **AI input:** new messages together, state, short customer summary, Planning options if any, product names.
- **AI output:** reply text, next step, details found, optional preference suggestion, short reason.
- **Order request to Planning:** request id, inquiry id, customer (id, phone, name), product, quantity (> 0), requested date (not in the past), order date (today). Customer context: up to 5 past orders, saved preferences (each "always" or "this order"), up to 3 insights marked INFERRED with evidence, a list of unclear items. Informational only. No price or cost. **No priority.**
- **Planning result:** request id, status (READY, WORKING, NOTHING_FEASIBLE, NEEDS_STAFF), options, reason code, time.
- **One option:** option id, kind (REQUESTED, LATER_DATE, LESS_QUANTITY; part-now-rest-later later), quantity, delivery date, valid until, reason code.
- **Confirmation notice:** inquiry id, option id, customer id, confirming message id, time, "payment assumed".
- **Responses:** `{status, data}` or `{error code, plain message, details}`.
- **Validity rules:** quantity above 0; date not in the past; product must exist; no unknown fields; context size limits; an option sent to the customer must come from a Planning result, never from the AI.

## F. Errors and tests

| Situation | What we do | Test |
| --- | --- | --- |
| Wrong format at a door | Wrong-format error | Missing fields, wrong types |
| Same message twice | "Already received", nothing repeated | Send twice, expect one reply |
| Missing order details | Ask only for what is missing | No date, then add it |
| AI unreachable or timeout | Safe reply, message kept for retry, staff flag after 2 failures | Fake AI that fails |
| AI answer in a broken format | Retry once, then a safe reply | Fake AI with garbage |
| AI proposes a forbidden step | Refuse, ask the customer | Fake AI says "confirm" too early |
| Reply has a date or number not from Planning | Regenerate once, then a plain template | Fake AI invents a date |
| Planning never answers | After the wait limit, tell the customer it needs more time, flag staff | Fake Planning with no answer |
| Planning result for unknown request | Not-found error, nothing changes | Wrong id |
| Planning result in wrong shape | Wrong-format error, nothing changes | Bad options |
| Nothing feasible | Tell the customer honestly, close with NO_OPTION | Fake scenario |
| Customer writes while we think | Handle together next turn | Two quick messages |
| Customer changes the request | New inquiry, old one REPLACED | Change quantity after options |
| Unclear "yes" | Ask again | "maybe", "ok but later" |
| "Yes" after expiry | Not accepted, re-check | Late yes |
| Database fails | Do not claim success; apologize; keep message for retry | Simulated failure |
| Sending to channel fails | Keep the reply and retry; mark failed after limit | Simulated failure |

Test set: realistic conversations (incomplete requests, corrections, returning customer, all Planning scenarios, confirmation, decline, silence), first with a fake AI, then with the real configured model. Plus the fairness test (identical results with or without delay history) and a duplicate-delivery test.

## G. Decisions recorded

| ID | Decision |
| --- | --- |
| A.1 | Say "received" immediately, think in the background inside the same program, send the reply when ready. |
| A.2 | One Sales folder with the same internal layout, repeated for every future agent. |
| A.3 | Only the data access layer touches the database. |
| A.4 | A fake Planning connector with scripted answers now; real later. |
| B.1 | Small set of doors only; no edit or delete doors. |
| B.2 | Include the read-only view doors (4, 5, 6). |
| B.3 | Prototype security: no login locally; a shared secret key on door 3. |
| Priority | Sales sends no priority. |
| Time limits (starting values) | AI wait 60 seconds, Planning wait 10 minutes (prototype), offer valid 24 hours. Set in settings. |
| AI failure | Safe message to the customer, staff flag after 2 failures. |
| Part now, rest later | Kept as a placeholder option, marked "later". |

## H. Open or later

- Real WhatsApp integration: account, webhook, signature check, hosting, message window and template rules, pricing. **Not researched yet** (web research was not done). Must be verified before choosing a path.
- Protecting the view doors outside local testing.
- The Planning contact point contract, and the execution policy that replaces human approval (see `1_sales_agent_high_level_architecture.md`, section 8).
- Neon is serverless: the first request after idle may be slow, so connection retry is needed. Exact Neon limits not checked.
