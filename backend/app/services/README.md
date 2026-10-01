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
| `negotiation_service.py` | Open a session for a shortage; `submit_message` replays stored messages through `NegotiationSession`, then stores message, offers, agreement, status and audit; `submit_supplier_response`; `get_session_view`; `scheduled_receipts` (committed agreements, P0-12). |
| `audit_service.py` | Append-only `decision_audit` writes (C7) with the working `decision_type` set. |

Working values still open in the contracts: `negotiation_type` (`SHORTAGE_PROCUREMENT`), participant roles (`INITIATOR`,
`RESPONDER`), offer statuses (`PROPOSED`, `SUPERSEDED`, `ACCEPTED`, `REJECTED`), reservation statuses (`ACTIVE`, `RELEASED`),
audit `decision_type` values and the audit agent chosen for each event (see `docs/contracts/C7_audit_record.md`).

Agreement validation (`mrpii/agreement.py`) checks quantity ≥ shortage and delivery date ≤ required-by. `COMMIT` needs a
validated agreement; only then does the agreement count as a scheduled receipt.
