# Purchasing Agent: Database Design

**Status:** implemented: migration `004` (three schemas) and `005` (Engine message type `CONFIRMATION`).
**Database:** PostgreSQL on Neon (`DATABASE_URL`; tests use `TEST_DATABASE_URL`).
**Full column list:** `../OVERALL_DATABASE_SCHEMA.md` §5 (Supplier Service, Purchasing) and §8 (Negotiation Engine).
**Related notes:** `1_purchasing_agent_high_architecture.md`, `2_purchasing_agent_functions.md`, `3_purchasing_agent_backend.md`.
**Diagram:** `diagrams/Purchasing Agent Relational Database Schema.png`.

## 1. Ground rules

1. Three schemas, each with its own owner and declarative base: `supplier_service`, `purchasing_agent`, `negotiation_engine`.
2. Purchasing writes only `purchasing_agent`. It reads the others only through their `service.py`.
3. Cross-schema references are **logical** (a UUID with no database FK), checked on write by the owning module.
4. Prices only in `purchasing_contracts` and the Leg's price snapshot, never in negotiation terms.
5. Statuses are fixed lists, enforced by CHECK constraints.
6. Legacy `purchasing` and `negotiation` schemas are untouched and unused.

## 2. The tables

### supplier_service (Supplier Service)
- **items:** id · sku (unique) · name · unit
- **suppliers:** id · name (unique) · contact_info · rating_data · is_active
- **supplier_items:** id · supplier_id (FK) · item_id (FK) · lead_time_days (≥ 0) · min_order_qty (> 0) · available_qty (≥ 0); unique (supplier, item)

### purchasing_agent (Purchasing)
- **purchasing_contracts:** id · supplier_id · item_id · unit_price (INR, > 0) · valid_from · valid_until (empty = open-ended) · is_active · created_at
- **procurement_requests:** id · item_id · shortage_quantity · required_date · priority · requested_by · request_ref (unique) · status · split_type · cost_ranking_available · constrained_quantity · status_reason · decided_at · created_at · updated_at
- **purchase_requisitions** (one row = one Leg): id · procurement_request_id (FK) · supplier_id · purchasing_contract_id (FK, empty = Not Registered) · unit_price_at_selection · allocated_quantity · quantity_cap · agreed_quantity · agreed_delivery_date · negotiation_session_id (unique) · status · status_reason · created_at · updated_at
- **decision_audit:** id · procurement_request_id (FK) · decision_type · context · decision · reasoning_summary · llm_explanation · created_at

### negotiation_engine (Negotiation Engine)
- **negotiation_sessions:** id · session_type (`PURCHASING_SUPPLIER`) · status · status_reason · correlation_id (the request) · objective · round_count · max_rounds · response_deadline · started_at · completed_at
- **negotiation_participants:** id · session_id (FK) · participant_type (AGENT / SUPPLIER) · participant_ref · role (INITIATOR / RESPONDENT) · joined_at
- **negotiation_messages:** id · session_id (FK) · message_id (unique) · sequence_number · round_number · sender_type · sender_ref · message_type · text · terms · interpretation_source · causation_id · created_at

## 3. Relationships

| One | Many | Link |
| --- | --- | --- |
| suppliers, items | supplier_items | FK |
| procurement_requests | purchase_requisitions | FK |
| procurement_requests | decision_audit | FK |
| purchasing_contracts | purchase_requisitions | FK (the contract used at selection) |
| negotiation_sessions | participants, messages | FK |
| purchase_requisitions | negotiation_sessions | 1:1 logical (`negotiation_session_id`) |
| supplier_service | purchasing_agent | logical (`supplier_id`, `item_id`) |

## 4. Statuses

| Record | Statuses |
| --- | --- |
| Procurement Request | RECEIVED → NEGOTIATING → AGREEMENT_PROPOSED → COMMITTED or APPROVAL_REJECTED; FAILED |
| Leg | PENDING, AGREED, FAILED, ABORTED, COMMITTED |
| Leg reason | `supplier_rejected`, `round_limit_exceeded`, `timeout`, `unclear_response`, `split_failed`, `no_longer_needed`, `manually_aborted`, `approval_rejected` |
| Audit decision type | `SUPPLIER_SELECTION`, `REALLOCATION`, `RE_SOURCING`, `RESPONSE_VALIDATION`, `RESPONSE_DEADLINE`, `APPROVAL`, `MANUAL_ABORT` |
| Engine session | OPEN, AGREED, REJECTED, TIMED_OUT, CANCELLED (AGREED → OPEN only on an explicit reopen) |
| Message (Purchasing) | OFFER, COUNTER_OFFER, CLARIFICATION_REQUEST, CANCEL, CONFIRMATION |
| Message (supplier) | ACCEPT, COUNTER_OFFER, REJECT, UNCLEAR |

The code constants are `RequestStatus`, `LegStatus` and `LegReason` in `models.py`.

## 5. Rules: database vs code

| Enforced by the database | Enforced by code |
| --- | --- |
| Status / type value lists | Contract overlap (the write service, so bad seeded data stays testable) |
| `unit_price` > 0, `valid_until` ≥ `valid_from` | Logical references exist |
| `allocated_quantity` > 0; contract and price snapshot both set or both empty | Effective availability and holds (advisory lock per supplier-item) |
| 0 ≤ `round_count` ≤ `max_rounds` | Response deadline (lazy check) |
| Unique `request_ref`, `message_id`, (`session_id`, `sequence_number`) | Duplicate `message_id` ignored in the same session; 409 if used in another |
| Message type matches sender; `interpretation_source` only for supplier messages | Rewording a message only while it is the session's latest |

**Holds:** a PENDING Leg holds `allocated_quantity`; an AGREED or COMMITTED Leg holds `agreed_quantity`. FAILED and
ABORTED Legs hold nothing. **`causation_id`** = the `message_id` this message responds to (see the schema doc §8).

## 6. Decisions recorded

| Decision | Note |
| --- | --- |
| Own schema per module | Like Sales' `sales_agent`; legacy demo resets can't touch them. |
| No offers table | Offer terms are stored on the message (`terms`). |
| Price snapshot on the Leg | The decision stays traceable if contracts change later. |
| Second migration `005` | Adds `CONFIRMATION`; the spec said one migration (recorded in `../PROJECT_STATUS.md`). |

## 7. Seed and reset

`python -m app.purchasing_agent.seed` (from `backend/`) resets the three schemas and loads the PA-v1 fixture
(`seed_data.md`). It includes deliberately overlapping contracts to test the `contract_overlap` exclusion.
