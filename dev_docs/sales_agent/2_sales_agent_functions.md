# Sales Agent: AI Agent Design (Role, Rules, Methods, Tools)

**Status:** design notes, decisions confirmed by the developer (2026-10-14). Nothing here is implemented.
**Related notes:** `1_sales_agent_high_level_architecture.md`, `3_sales_agent_backend.md`, `4_sales_agent_database.md`.

## 1. Role

The customer-facing salesperson. It talks with the customer, collects the order details, uses what we already know about the customer carefully, asks Planning what is possible, explains the answer honestly, and records the customer's explicit "yes".

## 2. Instructions (rules it must follow)

- Ask only for what is missing. Never ask again for something already given.
- If a message is unclear, ask. Never guess silently, even if old orders suggest an answer.
- Never invent a date, quantity or "yes, we can do it". Only present options that came from Planning.
- Never use what we know about the customer (for example past delays they accepted) to give them worse options.
- Never invent customer details or pretend to remember something that was never saved.
- Before asking for confirmation, repeat the exact product, quantity and date.
- Never say payment was made. For now, confirmation means "assumed paid".
- If nothing is feasible, say so honestly.
- Style: short, friendly, easy messages. English first. Ask for all missing details in one message, at most two items.

## 3. Methods (what the AI thinks and does)

1. Understand what the customer wants: new order, question, change, yes, no, or chatting.
2. Pull out product, quantity and date from the message.
3. Work out what is still missing.
4. Use history to ask a smart question ("same product as last time?").
5. Decide when there is enough to send to Planning.
6. Explain the options in simple words.
7. Understand which option the customer picked.
8. Understand whether the customer really confirmed.
9. Notice an explicit preference the customer states.

## 4. Tools (functions the agent may request)

**Decision 2.1 (updated to option C):** the AI never runs tools itself. It requests them and the Manager runs them.
- Read-only tools: the AI may request them freely, several per turn; the Manager runs them and returns the result.
- Save or commit tools: always go through the rules and checks first.

| # | Tool | Type | Input | Output | Goes to |
| --- | --- | --- | --- | --- | --- |
| 1 | get_customer_info | Read | Phone number | Customer record + saved preferences, or "not found" | AI (background) |
| 2 | get_order_history | Read | Customer id | Last few orders: product, quantity, requested date, status | AI (background) |
| 3 | get_product_list | Read | Nothing | Product names and ids | check_order_details, AI |
| 4 | check_order_details | Read | Product, quantity, date | OK + product id, or not OK + reasons | AI (ask again) or send_request_to_planning |
| 5 | get_order_status | Read | Order number or customer id | Status in plain words | AI |
| 6 | send_request_to_planning | Write | Valid order details + customer context | "Received" + request id | Saved on the inquiry, then wait (placeholder connector) |
| 7 | save_preference | Write | Customer id, allowed preference type, "always" or "this order", source message | Saved, or refused if the type is not allowed | Audit record |
| 8 | record_selected_option | Write | Inquiry id, option id | "Saved" | AI (asks for confirmation) |
| 9 | record_confirmation | Write | Inquiry id, option id, id of the "yes" message | Order marked confirmed | Planning contact point (confirmation notice) + AI |
| 10 | close_inquiry | Write | Inquiry id, reason | "Closed" | Manager |

Receiving Planning's answer is **not a tool**. It is a door (`Planning result arrives`) handled by the Manager (`handle_planning_result`).

Insights are **not** written by the AI. They are updated by fixed rules in our code (`update_insights`).

There is deliberately no tool that calculates dates, checks stock or decides feasibility.

## 5. The two control steps

| Step | Does | Input | Output |
| --- | --- | --- | --- |
| ai_understand_and_reply | The AI reads the messages and decides what to do | New messages, collected details, stage, customer summary, Planning options if any | Fixed-format answer (section 6) |
| check_ai_output | Our code checks the AI's answer: right format? step allowed in this stage? details valid? any date or number in the reply that did not come from Planning or the customer? | AI answer + stage + Planning options | OK -> do the step; problem -> ask the AI once more, or use a safe default reply |

## 6. Inputs and outputs per turn

**Receives:** the customer's messages (together, if several), who sent them and when; what is already collected and the stage; a small bounded customer summary; Planning's options when available; the product names.

**Produces (fixed format):** reply text; order details found; next step (ask_more, send_request, explain_options, record_selection, ask_confirmation, record_confirmation, close, pass_to_staff); optional preference suggestion; a short reason for the audit record.

## 7. Boundaries (must not do)

- Calculate or promise dates, quantities or feasibility.
- Contact Inventory, Purchasing or suppliers.
- Change priority or treat customers differently because of memory.
- Save free-form opinions or arbitrary insights about a customer.
- Confirm an order without a clear "yes" to a specific option.
- Handle payment.
- Change or cancel confirmed orders (not in the first version).

## 8. Decisions recorded

| ID | Decision |
| --- | --- |
| 2.1 | Option C: the AI requests tools, the Manager runs them. Read-only freely; save and commit tools only after rules and checks. (Originally the strict option A; updated on the developer's question.) |
| 2.2 | The AI can only suggest explicit preferences from an allowed list. Insights come only from fixed rules, each with evidence, and are revisable. |
| 2.3 | Order-status questions are answered (read-only). Cancel, change and complaint messages get a polite "a team member will follow up" and a saved note. |
| 2.4 | English first, short and friendly. Other languages later. |

## 9. Confirmation safeguards (the riskiest moment)

A misread "yes" would create a binding order, so confirmation is guarded by code, not by prompt:
1. Valid only in stage AWAITING_CONFIRMATION, for one specific option.
2. Sales must have repeated the exact quantity, date and "payment assumed" in the message just before; the "yes" must come after that.
3. The AI returns a structured classification (CONFIRM, DECLINE, QUESTION, CHANGE, UNCLEAR). Only CONFIRM proceeds. Anything else leaves the state unchanged.
4. Any change of quantity, date or option invalidates the confirmation and starts a new inquiry.
5. An expired offer cannot be confirmed.

## 10. Fairness safeguards

- The customer context sent to Planning is informational only and never an input to feasibility, capacity, supplier or priority calculations.
- Memory types come from an allowed list; there is no "tolerates delay" or "flexible" type.
- "Customer accepted option B on order X" is a fact on that inquiry only, never a general customer trait.
- Test: the same request from a customer with no history and a customer with many accepted delays must produce identical requests and identical options.
