# backend/app/services

The only path to the database. Services load inputs, call the Phase 1 deterministic code (`app/mrpii`, `app/negotiation`),
and store the results. They make no business calculations of their own and contain no LLM code. Write operations commit.

| File | Purpose |
| --- | --- |
| `order_service.py` | Create / read orders (C1 invariants, finished products only, unique order number). Audits `ORDER_RECEIVED`. |
| `planning_service.py` | `run_plan`: finished-goods netting → MPS → capacity → BOM → MRP via `plan_order`; stores `planning.*` rows and a `PLAN_CREATED` audit record. `get_plan` reads them back (netting, capacity, validation come from the audit record). Re-planning replaces the order's rows. |
| `inventory_service.py` | Aggregated positions (C1 availability rule), `reserve` / `release`. |
| `bom_service.py` | Active BOM lines for a product. |
| `capacity_service.py` | Production lead time and `capacity_per_day` from fixture/config (`app/data/x1_fixture.py`). |
| `supplier_service.py` | Supplier options and deterministic feasibility inputs (no selection, no price). |
| `negotiation_service.py` | Open a session for a shortage; `submit_message` replays stored messages through `NegotiationSession`, then stores message, offers, agreement, status and audit; `build_supplier_message` (supplier form → C4 message, current round only); `submit_supplier_response` (Phase 2 direct path); `get_session_view`; `sessions_for_order`; `scheduled_receipts` (committed agreements, P0-12). |
| `requisition_service.py` | Purchase requisitions, one per session (id = uuid5 of the session id). Only the Purchasing Agent may create or update them. Audits `REQUISITION_CREATED`. |
| `supplier_interface_service.py` | The supplier interface (not an agent): builds the `SUPPLIER_INTERFACE` message from the form and delivers it to the Purchasing Agent over A2A (`app/core/a2a_client.py`). |
| `approval_service.py` | C8 approval workflow (not an agent): plan attempts (audit records under Planning), `attempts` / `current` with derived `PENDING_NEGOTIATION` / `AWAITING_APPROVAL`, `approve` (COMMIT each agreement), `reject` (ABORT uncommitted agreements; last attempt → `HUMAN_INTERVENTION_REQUIRED`). Max 2 attempts. |
| `audit_service.py` | Append-only `decision_audit` writes (C7) with the working `decision_type` set; `list_decisions` (decision log with agent codes). |

Working values still open in the contracts: requisition statuses (`OPEN`, `AGREEMENT_PROPOSED`, `REJECTED`, `FAILED`), `negotiation_type` (`SHORTAGE_PROCUREMENT`), participant roles (`INITIATOR`,
`RESPONDER`), offer statuses (`PROPOSED`, `SUPERSEDED`, `ACCEPTED`, `REJECTED`), reservation statuses (`ACTIVE`, `RELEASED`),
audit `decision_type` values and the audit agent chosen for each event.

Agreement validation (`mrpii/agreement.py`) checks quantity ≥ shortage and delivery date ≤ required-by. `COMMIT` needs a
validated agreement; only then does the agreement count as a scheduled receipt.
