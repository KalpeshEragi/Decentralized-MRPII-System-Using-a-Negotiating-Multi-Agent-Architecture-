# Sales Agent: High-Level Architecture (System Boundary)

**Status:** design notes, decisions confirmed by the developer (2026-10-14). Implemented in `backend/app/sales_agent/` (see its `README.md`; Planning is still a fake connector).
**Scope:** the Sales Agent only. Planning, Inventory and Purchasing are treated as an outside system; only a contact point to Planning is defined.
**Related notes:** `2_sales_agent_functions.md`, `3_sales_agent_backend.md`, `4_sales_agent_database.md`.

## 1. Purpose

The Sales Agent is the customer-facing salesperson of the system. It talks with the customer, collects the order details, uses stored customer knowledge carefully, asks Planning what is feasible, explains Planning's answer honestly, and records the customer's explicit confirmation.

## 2. Inside the Sales Agent boundary (Sales owns this)

1. Talking to the customer: reading messages, replying, asking for missing details.
2. Collecting order details: product, quantity, requested delivery date.
3. Customer records and memory: customer info, saved explicit preferences, a few simple insights, order history.
4. Conversation history: every message is saved.
5. Inquiry and offer records: inquiry, options shown, option chosen, confirmed. These four stages stay separate.
6. Explaining options in friendly words.
7. Asking for and recording the customer's explicit confirmation.
8. The confirmed order record and its customer-facing status.

## 3. Outside the boundary (not Sales' job)

| Item | Who |
| --- | --- |
| Deciding feasibility: capacity, materials, supplier terms, dates | Planning |
| Stock checks | Inventory (behind Planning) |
| Supplier negotiation | Purchasing (behind Planning) |
| The deterministic "go ahead" rulebook that replaces routine human approval | A neutral execution policy (outside Sales and outside any agent). See "Autonomy direction". |
| Payment | Future work. For the prototype, customer confirmation means the upfront payment is assumed to be complete. |
| WhatsApp provider systems | External service, later |

Sales never contacts Inventory or Purchasing. Only Planning does.

## 4. The doors (contact points)

| Door | Direction | Status |
| --- | --- | --- |
| Customer channel | Customer <-> Sales | Test channel now, WhatsApp later. Same conversation core for both. |
| Request to Planning | Sales -> Planning | Placeholder. Order request + bounded customer context. |
| Results from Planning | Planning -> Sales | Placeholder. Feasible options. A separate door from the request (decision 1.1). |
| Confirmation notice | Sales -> outside | Placeholder. "Customer confirmed option X". |
| AI model | Sales <-> AI model | The existing configured model. Conversation help only. |
| Storage | Sales <-> database | Sales-owned data only. PostgreSQL on Neon. |

## 5. Options Planning may return (Planning computes them; Sales never does)

- A. The requested quantity is feasible by the requested date.
- B. The deadline is not feasible: the earliest feasible date for the full quantity.
- C. The quantity is not feasible: the quantity that is feasible by the requested date.
- D. Part now, the rest later (placeholder, later).
- E. Nothing feasible. Sales must say so honestly.

## 5a. How an order becomes real

Inquiry -> feasibility assessment and options -> option selected -> explicit confirmation -> confirmed order.
Before confirmation nothing is treated as a confirmed customer order. Provisional supplier work done by Planning before the offer is not binding; binding commitments happen only after the customer confirms.

## 6. Rules (write these on the diagram)

1. Sales never calculates dates, quantities or feasibility. It only asks and explains.
2. Sales never talks to Inventory or Purchasing.
3. Sales never promises a date that did not come from Planning.
4. Customer memory is never used to change priority or the options a customer gets. Customer flexibility is never used against the customer.
5. The AI model helps with conversation only. It never decides business facts.
6. Sales sends no priority; the business or Planning assigns it.
7. No price or cost anywhere (out of scope for the 25% milestone).

## 7. Decisions recorded

| ID | Decision |
| --- | --- |
| 1.1 | Two separate doors to Planning: requests out, results back, because supplier checking is slow. |
| 1.2 | Sales records the customer's confirmation itself and only tells others what was decided. |
| 1.3 | Sales fully owns the customer records. Others get only a small, limited summary when Sales chooses to send it. |
| 1.4 | The customer-facing order record belongs to Sales. Production plans and supplier deals stay outside. |
| Channel | Start with a test channel; real WhatsApp later; do not build the conversation twice. |
| LLM | Start with the existing configured model. Only change it if realistic conversation tests are unsatisfactory. |

## 8. Autonomy direction (confirmed by the developer and mentor)

The system should operate autonomously by default; human intervention is reserved for explicit exceptions (roughly 100 to 200 orders per day is the target). Implications for the Sales design:

- Routine offers are presented without a human approving each one, after deterministic validation.
- On customer confirmation the system re-validates feasibility, then performs the authorized commitment and order confirmation without routine human approval.
- The decision is made by deterministic rules (an execution policy), never by the LLM alone.
- Exceptions (failed supplier negotiation, unresolved feasibility, resource conflicts, requests beyond authority) escalate to a human with reason codes.
- Urgency is derived from dates, not from the customer's wording, and is separate from priority.
- Everything is auditable.

The detailed execution policy, the replacement of the C8 approval workflow, and the integration with Planning are **not designed yet**. They are integration work for later. For now Sales only needs the contact points.

## 9. Diagram checklist (what the drawing must show)

- One big box "Sales Agent" with the 8 inside items.
- Customer (through the test channel) with a two-way arrow to Sales.
- AI model with a two-way arrow to Sales.
- Database (Sales-owned only) with an arrow to Sales.
- Planning outside, with two separate arrows: request out, results back. Plus a "customer confirmed option X" arrow.
- Inventory and Purchasing drawn behind Planning with the note "never contacted by Sales".
- Planning marked "outside, placeholder for now"; WhatsApp marked "later"; payment marked "assumed paid for now".
- The rules note from section 6.
