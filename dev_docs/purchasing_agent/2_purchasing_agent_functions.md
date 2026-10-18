# Purchasing Agent: Agent Design (Role, Rules, Methods, Tools)

**Status:** implemented standalone (branch `purchasing-agent`, 2026-10-18).
**Detailed rules:** `purchasing_agent_architecture.md` §6 (selection), §7 (negotiation), §9 (LLM).
**Related notes:** `1_purchasing_agent_high_architecture.md`, `3_purchasing_agent_backend.md`, `4_purchasing_agent_database.md`.
**Diagram:** `diagrams/Purchasing Agent Tools and Capabilities.png`.

## 1. Role

The buyer. It finds the best feasible way to cover a shortage, negotiates quantity and date with each chosen
supplier, and proposes one combined agreement for a human to approve. Unlike the Sales Agent, the decisions are made
entirely by deterministic code. The LLM is a helper for language only.

## 2. Instructions (rules it must follow)

- Select only feasible options: active supplier, arrives by the required date, effective availability ≥ MOQ.
- Rank by Total Purchasing Cost (unit price × quantity ordered, MOQ surplus included) when prices are known.
  Otherwise use the unpriced fallback ("cost ranking unavailable").
- Never negotiate price. Offer terms are quantity and delivery date only.
- Never agree a late or past delivery date. Never change the requester's required date.
- Echo how each reply was read ("Understood: …") before acting on it.
- Ask for clarification when a reply is unclear (max 2 per pending offer). Never guess.
- Never add a new supplier after selection.

## 3. Methods (what the agent does)

1. Accept a Procurement Request (or return the existing one for a repeated `request_ref`).
2. Read supplier options and valid contracts on the selection date (today in the configured timezone).
3. Compute effective availability under a per supplier-item lock.
4. Select: priced single vs Cost-Saving Split, else unpriced fallback, else Necessary Split, else FAILED.
5. Open one Leg + one Engine session per selected supplier and send an offer.
6. For each supplier reply: interpret → validate → agree / counter / reallocate / clarify / fail.
7. When every Leg is AGREED, propose the agreement. When any Leg fails, fail the request and cancel the other Legs.
8. Apply a human's approval or rejection.

## 4. Tools / services

All are plain code. The LLM requests no tools.

| # | Function | Module | Type | What it does |
| --- | --- | --- | --- | --- |
| 1 | `submit_request` | `service.py` | Write | Idempotent intake, selection, Legs, sessions, offers, audit |
| 2 | `supplier_items_for`, `get_item`, `get_supplier` | `supplier_service/service.py` | Read | Supplier master data |
| 3 | `price_state` | `selection.py` | Pure | Price, Not Registered or `contract_overlap` on a date |
| 4 | `effective_availability` | `availability.py` | Read + lock | Available quantity minus other requests' holds |
| 5 | `select_suppliers` | `selection.py` | Pure | Singles, every combination, MOQ-first allocation, ranking, reasons |
| 6 | `reallocate` | `selection.py` | Pure | Same rules over the selected suppliers with their caps |
| 7 | `receive_supplier_message` | `negotiation.py` | Write | One supplier reply, end to end |
| 8 | `interpret` | `interpretation.py` | LLM + parser | Reply text → action and terms |
| 9 | `validate` | `negotiation.py` | Pure | Reply + offer + required date → decision |
| 10 | `fail_procurement`, `cancel_leg` | `negotiation.py` | Write | All-or-nothing failure; cancel one Leg |
| 11 | `approve`, `reject` | `approval.py` | Write | Human decision |
| 12 | `abort` | `abort.py` | Write | Tester's manual stop |
| 13 | `expire_overdue`, `expire_holds_on_item` | `deadlines.py` | Write | Lazy deadline check; release stale holds |
| 14 | `register`, `list_contracts` | `contracts.py` | Write / Read | Purchasing Contracts |
| 15 | `MessageWriter`, `explain_selection` | `writer.py` | LLM | Message wording and selection explanation, with guardrails |
| 16 | `apply_wordings`, `apply_explanation` | `wording.py` | Write | Apply LLM text after the commit, only while still valid |

## 5. The control steps around the LLM

| Step | Does | On failure |
| --- | --- | --- |
| Interpret | The LLM extracts `{action, quantity, delivery_date}`. Code checks that each term is really written in the reply. | Strict fallback parser (`ACCEPT`, `COUNTER <qty> <yyyy-mm-dd>`, `REJECT`). Unreadable → unclear. |
| Validate | Pure code compares the reply with the current offer and required date. | — (deterministic) |
| Word | The LLM rewords a committed template message. A guardrail check runs on the result. | The template stays. |
| Explain | The LLM explains the selection. A guardrail check runs on the text. | No explanation (NULL); the deterministic `reasoning_summary` is always stored. |

## 6. Inputs and outputs

**Procurement Request:** `request_ref`, `item_id`, `shortage_quantity` (whole units), `required_date`, `priority`, `requested_by`.
**Supplier reply:** `message_id` (UUID), free `text`.
**Outputs:** request status, split type, Legs with negotiation, audit records, scheduled receipts.

## 7. Boundaries (must not do)

- Negotiate price, show a price to a supplier, or treat Not Registered as zero.
- Let the LLM change suppliers, quantities, dates, prices or allocations.
- Write supplier master data or another module's tables.
- Commit anything without a human approval of the whole agreement.
- Restart supplier selection or add a replacement supplier after a failure.

## 8. Guardrails (summary)

Wording is rejected when it drops or changes a term, adds another number, date, code or month, writes a quantity or
date in words, uses money words, or names another supplier. An explanation is rejected when it states a number not
in the decision, prices or zeroes a Not Registered supplier, claims a cost comparison without a cost ranking, or
mentions negotiating price. Full list: `purchasing_agent_architecture.md` §9.
