---
status: accepted
date: 2026-10-17
---

# Price is in scope for supplier selection only

The earlier milestone kept cost/price out of scope. Purchasing could then only pick suppliers by arrival, so it could not show that it weighs what material costs. We now keep a **Purchasing Contract** (unit price in INR, with validity dates) per supplier-item pair. Purchasing ranks suppliers and supplier combinations by **Total Purchasing Cost**, including MOQ surplus.

Price is **never negotiated**. It never appears in offer terms, the supplier chat or agent state, and a missing price is **Not Registered**, never zero. We chose this over negotiating price because it keeps the negotiation protocol (quantity and delivery date only) unchanged, and keeps every price claim traceable to a contract row rather than to supplier chat or LLM output. S5 (supplier price increase) stays out of scope.

## Consequences

- At most one active, valid contract may cover a supplier-item on a date. Overlap is rejected on write. Overlap found at selection excludes that supplier (`contract_overlap`) instead of picking a price.
- The LLM may explain cost-based choices but cannot change them or state prices that are not in the deterministic summary.
- Supersedes the "Cost/price is future scope" decision in the removed `docs/DECISIONS.md` and the "no price" constraint in `docs/smartphone_x1_fixture.md` for Purchasing.
