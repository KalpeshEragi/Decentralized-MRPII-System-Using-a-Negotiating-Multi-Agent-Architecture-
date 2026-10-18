# Purchasing Agent: High-Level Architecture (System Boundary)

**Status:** implemented standalone (branch `purchasing-agent`, tickets 01–11, 2026-10-18). Other agents are replaced by test inputs.
**Scope:** the Purchasing Agent, plus the two modules it works with: the Supplier Service and the Negotiation Engine.
**Detailed rules:** `purchasing_agent_architecture.md`. **Price decision:** `../adr/ADR-002-price-in-supplier-selection.md`.
**Related notes:** `2_purchasing_agent_functions.md`, `3_purchasing_agent_backend.md`, `4_purchasing_agent_database.md`.
**Diagram:** `diagrams/Purchasing Agent System Boundary Diagram.png`.

## 1. Purpose

The Purchasing Agent is the system's buyer. It takes a **Procurement Request** (item, shortage quantity, required
date), picks the best feasible supplier or combination of suppliers, negotiates quantity and delivery date with
each one in a chat, and proposes a combined **Procurement Agreement** that a human approves or rejects.

## 2. Inside the Purchasing boundary (Purchasing owns this)

1. Procurement Requests: intake (idempotent), status and outcome.
2. Purchasing Contracts: unit price per supplier-item with validity dates.
3. Supplier selection: single supplier, Cost-Saving Split or Necessary Split (deterministic).
4. Legs (requisitions): one per selected supplier, with its quantity, cap, price snapshot and status.
5. Holds on supplier quantity (effective availability), so two requests never double-book a supplier.
6. Reading and validating supplier replies; counter-offers and reallocation.
7. All-or-nothing failure with the Constrained Quantity.
8. Approval handling and scheduled receipts.
9. Decision audit.

## 3. Outside the boundary (not Purchasing's job)

| Item | Who |
| --- | --- |
| Supplier master data (items, suppliers, lead time, MOQ, available quantity) | Supplier Service (read only for Purchasing) |
| Session, message, round and deadline storage | Negotiation Engine (shared infrastructure, no business decisions) |
| Deciding the shortage and required date | The requester (test API now; which agent at integration) |
| Stock and reservations | Inventory |
| Production plans | Planning |
| Receiving slots and space | Warehouse (future integration, WH-1) |
| Supplier disruptions (delay, quantity cut) | Future scope |

## 4. The doors (contact points)

| Door | Direction | Status |
| --- | --- | --- |
| Procurement Requests | Requester → Purchasing | Built: test API `POST /purchasing/procurement-requests`. A2A from another agent later. |
| Request status and audit | Anyone → Purchasing | Built: read API. |
| Approval | Human → Purchasing | Built: approve / reject API. |
| Manual abort | Tester → Purchasing | Built. |
| Purchasing Contracts | Tester → Purchasing | Built: register and list. |
| Supplier chat | Supplier ↔ Purchasing | Built: WhatsApp-like test-channel page, one conversation per Leg. |
| Scheduled receipts | Purchasing → readers | Built: read API. Pub/Sub outcome event later. |
| AI model | Purchasing ↔ shared Ollama client | Built. Never required. |
| Storage | Purchasing ↔ database | Own schema `purchasing_agent`; reads `supplier_service` and `negotiation_engine` through their interfaces. |

## 5. Outcomes Purchasing can reach

- **SINGLE:** one supplier covers the shortage (priced, or the unpriced fallback "cost ranking unavailable").
- **COST_SAVING_SPLIT:** a fully priced combination that costs ≥ 10% less than the best priced single.
- **NECESSARY_SPLIT:** no single supplier can cover; several suppliers together can.
- **FAILED:** nothing feasible, or a Leg failed; the **Constrained Quantity** says what could have been covered.

## 5a. How a procurement becomes real

Request → selection → one Leg + negotiation per supplier → every Leg AGREED → AGREEMENT_PROPOSED → human approves →
COMMITTED (scheduled receipts). A rejected approval, a failed Leg or a manual abort ends it with nothing committed.
An agreed Leg is never a scheduled receipt until the whole agreement is approved.

## 6. Rules

1. Code decides suppliers, quantities, dates and costs. The LLM only reads replies, words messages and explains.
2. Price is used for selection only. It is never negotiated, never sent to a supplier, never shown in the chat.
3. A supplier without a valid contract is **Not Registered**: price unknown, never zero.
4. The requester's required date is never changed. A late or past delivery date is never agreed.
5. All or nothing: either every Leg agrees or the whole procurement fails.
6. New suppliers are never added during negotiation.
7. Purchasing never writes supplier master data or another module's tables.
8. Request priority affects processing order only, never supplier ranking.

## 7. Decisions recorded

| ID | Decision |
| --- | --- |
| ADR-002 | Price is in scope for supplier selection only (2026-10-17). |
| Engine | A new Negotiation Engine holds protocol state; its statuses are separate from Leg statuses (2026-10-17). |
| Limits | Max 3 rounds per Leg, max 2 clarifications per pending offer, 24h response deadline checked lazily (all settings). |
| Holds | Only other requests' Legs reduce a request's effective availability (2026-10-18). |
| Approval | A human approves or rejects; reject cancels every supplier session (2026-10-18). |
| Locks | No lock is held during LLM calls (2026-10-18, code review). |

## 8. Integration direction (future)

Not built: A2A requests from the requesting agent, Pub/Sub outcome events to Planning, cross-agent approval/commit
instead of the human approval, a Warehouse receiving step (WH-1), supplier disruptions and Invalidated Agreements, and
a Negotiation Engine generalised beyond Purchasing.
