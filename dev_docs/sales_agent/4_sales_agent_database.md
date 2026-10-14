# Sales Agent: Database Design (lean version)

**Status:** design notes, decisions confirmed by the developer (2026-10-14). Nothing here is created or migrated.
**Database:** PostgreSQL on Neon, as in the existing project (`DATABASE_URL`; a separate test database via `TEST_DATABASE_URL`).
**Schema:** a separate schema `sales_agent` (decision D4.8). The existing `sales` schema already has `customers` and `customer_orders`; at integration, map this design's `customers` and `orders` to those.
**Related notes:** `1_sales_agent_high_level_architecture.md`, `2_sales_agent_functions.md`, `3_sales_agent_backend.md`.

## 1. Ground rules

1. Sales owns every table here, except `products`, which is shared reference data that Sales only reads.
2. No price or cost fields anywhere.
3. No priority field. Sales does not set priority.
4. Facts are not copied. Past orders and dates are read from `orders` and `inquiries`; they are not stored again as "memory".
5. All times in UTC. Ids are UUIDs. "JSON" below means PostgreSQL JSONB.
6. Statuses are fixed lists enforced by the database.

## 2. The 9 tables

(PK = primary key, FK = link to another table.)

### customers
id (PK) · phone (unique, international format) · name (may be empty) · created_at · updated_at

### products (shared reference, read-only for Sales)
id (PK) · sku · name · active. Later replaced by a link to the shared item master.

### conversations
id (PK) · customer_id (FK, may be empty for an unknown number) · channel (TEST or WHATSAPP) · sender_ref · status (OPEN, IDLE, CLOSED) · current_inquiry_id (FK) · busy (yes/no, one turn at a time) · last_message_at

### messages
id (PK) · conversation_id (FK) · direction (IN or OUT) · provider_message_id (unique per channel, so duplicates are skipped) · text · created_at · processed (IN: has the AI handled it) · delivery_status (OUT: QUEUED, SENT, FAILED)

### inquiries (the request, before it is an order)
id (PK) · conversation_id (FK) · customer_id (FK, may be empty) · stage (see section 4) · closed_reason · product_id (FK, empty while gathering) · quantity · requested_date · offer_valid_until · selected_option_id (FK) · confirmed_at · confirmation_message_id (FK) · planning_request_ref (unique) · planning_request (JSON, what we sent including the customer context) · planning_result (JSON, what came back) · created_at · updated_at

### options (what Planning offered; copied exactly)
id (PK) · inquiry_id (FK) · kind (REQUESTED, LATER_DATE, LESS_QUANTITY, PART_NOW_REST_LATER later) · quantity · delivery_date · valid_until · reason_code · status (OFFERED, SELECTED, EXPIRED, RELEASED)

### orders (confirmed customer orders only)
id (PK) · order_number (unique) · customer_id (FK) · inquiry_id (FK) · option_id (FK) · product_id (FK) · quantity · delivery_date · status (CONFIRMED now; later statuses come from outside) · payment_status (ASSUMED_PAID for the prototype) · confirmed_at

### customer_memory (preferences and insights in one table)
id (PK) · customer_id (FK) · kind (PREFERENCE or INSIGHT) · type (from an allowed list, for example PREFERS_WHATSAPP_UPDATES, WANTS_EARLY_DATE_CHANGE_NOTICE, FREQUENT_PRODUCT) · value (short detail, JSON) · scope (GENERAL or THIS_ORDER) · inquiry_id (FK, only if scope is THIS_ORDER) · source (STATED = customer said it, INFERRED = our rule found it) · strength (LOW, MEDIUM, HIGH; inferred only) · status (ACTIVE, SUPERSEDED, RETIRED) · evidence (JSON list of what supports it, e.g. message 12, order 3) · created_at · updated_at

### audit_log
id (PK) · time · actor (SALES_AI, SYSTEM, PLANNING, HUMAN) · event_type (for example AI_TURN, CHECK_FAILED, OPTIONS_PRESENTED, CONFIRMATION_ACCEPTED, ESCALATED) · conversation_id · inquiry_id · details (JSON: rules checked, reasons, the AI's structured answer)

## 3. Relationships

### One to many
| One | Many | Note |
| --- | --- | --- |
| customers | conversations | Customer may be empty (unknown number) |
| customers | inquiries | Same |
| customers | orders | |
| customers | customer_memory | |
| conversations | messages | |
| conversations | inquiries | One chat can hold several inquiries over time |
| products | inquiries | |
| products | orders | |
| inquiries | options | |
| inquiries | customer_memory | Only for preferences that apply to "this order" |
| conversations | audit_log | Loose link |
| inquiries | audit_log | Loose link |

### One to one (optional on one side)
| One | One | Note |
| --- | --- | --- |
| inquiries | orders | An inquiry becomes at most one order |
| options | orders | The chosen option becomes at most one order |
| conversations | inquiries | The current active inquiry (a pointer) |
| inquiries | messages | The message that carried the customer's "yes" |

### Many to many (neither needs its own table)
| A | B | How |
| --- | --- | --- |
| customers | products | Through `orders` |
| customer_memory | messages, orders, inquiries | A list inside each memory row (`evidence`) |

## 4. Inquiry stages (7)

| Stage | Meaning |
| --- | --- |
| GATHERING | Collecting details |
| WAITING_FOR_PLANNING | Request sent |
| OPTIONS_PRESENTED | Options shown |
| AWAITING_CONFIRMATION | Waiting for the "yes" |
| CONFIRMED | Became an order |
| NEEDS_STAFF | A person must look |
| CLOSED | With `closed_reason`: NO_OPTION, DECLINED, EXPIRED, ABANDONED, REPLACED |

## 5. Rules the database itself should enforce

- One phone number per customer; one message id per channel.
- Only one active inquiry per conversation.
- One order per inquiry; unique order number.
- Memory `type` only from the allowed list; no "tolerates delay" or "flexible" type.
- Unique `planning_request_ref`, so a repeated Planning answer is ignored.

## 6. Decisions recorded

| ID | Decision |
| --- | --- |
| Lean version | 9 tables, 7 stages. Left out for now: a separate Planning message table (kept as two JSON notes on the inquiry; every message is also in the audit log), a separate evidence table (a list inside the memory row), and the fields attempts, replaced_by_inquiry_id, superseded_by, last_checked_at, status_updated_at. |
| D4.1 | One memory table for preferences and insights. |
| D4.2 | A small read-only `products` table now; link to the shared item master at integration. |
| D4.3 | One product per inquiry and order for now. Several products would need an order-lines table later. |
| D4.4 | Keep messages and phone numbers during the prototype; define a retention rule before real customers. |
| D4.5 | Store the full Planning request and result (proof of what was offered). |
| D4.6 | Collected details are columns (empty while gathering), not JSON. |
| D4.7 | Statuses are fixed lists in the database. |
| D4.8 | Separate schema `sales_agent`; map to the existing `sales` tables at integration. |

## 7. Neon notes

Neon is serverless: the first request after idle may be slow or fail once, so the backend needs a connection retry. Exact Neon limits (connections, storage, sleep time) have not been checked. Tests use their own database.
