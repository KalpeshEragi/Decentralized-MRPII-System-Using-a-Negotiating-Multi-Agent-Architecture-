# Supplier: Overview (Role and Boundaries)

**Status:** implemented standalone (branch `purchasing-agent`, 2026-10-18).
**Related notes:** `2_supplier_interface.md`, `3_supplier_backend.md`, `4_supplier_database.md`.
**Decisions:** `../DECISIONS.md` (Suppliers row), `../adr/ADR-002-price-in-supplier-selection.md`.

## 1. What "Supplier" is

Suppliers are **simulated outside parties, not an MRPII agent**. In the code they are two things:

| Part | What it is | Code |
| --- | --- | --- |
| Supplier Service | Read-only supplier master data: items, suppliers, supplier items (lead time, MOQ, available quantity) | `backend/app/supplier_service/` |
| Supplier-facing interface | The Purchasing test-channel chat. A human tester plays the supplier of one Leg | `backend/app/purchasing_agent/test_channel/supplier_chat.html`, `/purchasing/test-channel` routes in `purchasing_agent/api.py` |

**MOQ** = minimum order quantity. **Leg** = one supplier's part of a procurement (`/GLOSSARY.md`).

## 2. What it is not

- Not an agent: no decisions, no LLM, no own state machine, no queue.
- Not a price source: prices live in Purchasing Contracts (`purchasing_agent.purchasing_contracts`), owned by Purchasing.
- Not a negotiation store: sessions and messages live in the Negotiation Engine (`negotiation_engine`).
- No supplier login or per-supplier portal: the test channel shows every Leg's conversation to whoever opens it.

## 3. Boundaries

| Rule | Where |
| --- | --- |
| Supplier master data is only read by other modules, through `supplier_service/service.py` | Purchasing, Negotiation Engine |
| Nothing writes supplier master data at runtime; only the seed loads it | `supplier_service/seed.py` |
| Purchasing decides everything about a supplier (eligible, ranked, quantity, date, agree/fail) | `purchasing_agent/` |
| The supplier only answers offers in free text; Purchasing reads and validates the answer | `purchasing_agent/negotiation.py` |
| A supplier never sees a price | message templates, views, LLM guardrails |
| Inactive suppliers are returned by the service; Purchasing excludes them (`inactive_supplier`) | `purchasing_agent/selection.py` |

## 4. Who uses it

```text
Tester (as supplier) ──chat page──> /purchasing/test-channel ──> Purchasing (negotiation.py)
                                                                   │
Purchasing ──read──> Supplier Service (items, suppliers, supplier items)
Purchasing ──store messages──> Negotiation Engine ──check participant exists──> Supplier Service
```

## 5. Legacy code (not used)

`backend/app/services/supplier_service.py` (legacy `purchasing.suppliers` tables) belongs to the earlier three-agent
prototype and is not the new Supplier Service. The legacy supplier interface (`supplier_interface_service.py`,
`/supplier-interface/...`, `/negotiations/{id}/supplier-responses`, `/a2a/supplier-interface`) was removed 2026-10-18.

## 6. Future (not built)

- Supplier disruptions (delay, quantity cut) and Invalidated Agreements (Scenario Manager).
- Mapping `supplier_service.items` to `core.items` at integration.
- Updating available quantity when receipts are used up; a supplier data write API.
- Access control / per-supplier view of the chat.
