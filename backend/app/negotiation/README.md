# backend/app/negotiation

Pure in-memory negotiation protocol (Phase 1, C4). No persistence, transport or business decisions.

| File | Purpose |
| --- | --- |
| `protocol.py` | `ProtocolError` and `ProtocolErrorCode`; re-exports `MAX_ROUNDS` (3). |
| `messages.py` | Stateless validation: `parse_message`, `validate_message` (routes and required terms per message type). |
| `session.py` | `NegotiationSession`: state machine, sequence and duplicate checks, round tracking, agreement terms, `outcome`. |

Message and status shapes are in `app/schemas/negotiation.py`.

Flow: Inventory `REQUEST` → Purchasing `OFFER` (round 1) / `COUNTER_OFFER` (rounds 2–3) ↔ supplier interface `ACCEPT` /
`COUNTER_OFFER` / `REJECT` → Purchasing `AGREEMENT_PROPOSED` → `COMMIT`.

- `OfferTerms` is exactly `quantity`, `required_date`, `delivery_date`, `priority` (no price/cost, lead time or inventory impact).
- The supplier-side sender type is `SUPPLIER_INTERFACE`: the supplier form/service, not a Supplier Agent (none in the 25%).
- `REJECT` from the supplier interface, or from Purchasing at any point on its turn (even before round 3), ends the
  session `REJECTED` (terminal). `FAILED` means a Purchasing `COUNTER_OFFER` was needed after round 3: round limit
  reached, no agreement. Planning receives the normalized outcome `FAILED` for both.
- `COMMIT` is an approval/lifecycle action. Only sender type `APPROVAL_WORKFLOW` (to Inventory) may send it, and only
  from `AGREEMENT_PROPOSED`; Inventory and Purchasing cannot. The human approval workflow itself is C8 (later phase).
- A refused message raises `ProtocolError` and leaves the session unchanged.

Whether an agreement is feasible is checked deterministically outside this package.
