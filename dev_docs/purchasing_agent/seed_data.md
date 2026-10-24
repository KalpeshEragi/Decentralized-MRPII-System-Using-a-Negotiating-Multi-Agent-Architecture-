# Purchasing Agent Test Fixture (PA-v1)

**Status:** Approved direction (2026-10-17). Replaces the X1 fixture for the standalone Purchasing Agent, Supplier Service and Negotiation Engine.
**Used by:** `supplier_service` / `purchasing_agent` seed and reset, Purchasing tests, manual demo through the supplier chat.

## 1. Conventions

- **Selection date** `D` = **2026-11-02** (tests use a fixed clock set to this date).
- **Timezone:** `Asia/Kolkata` (configurable; working default). The selection date is the server's date in this timezone.
- **Arrival** = `D + lead_time_days` (calendar days).
- Prices are INR per unit (`NUMERIC(12,2)`); calculations use exact decimals, never floats.
- Quantities are integers.
- Each scenario runs independently from a fresh reset, unless stated otherwise.
- Item and supplier IDs are fixed UUIDs defined in the seed module; this document names them by SKU and supplier name.

## 2. Items

| SKU | Name | Item ID (`item_id`) | Purpose |
|---|---|---|---|
| DSP-100 | Display Panel | `17b19502-e17e-5721-b38a-43fb4e5d88ed` | Cheapest single, MOQ surplus, unpriced fallback, no feasible supplier |
| BAT-200 | Battery Pack | `fb71680e-878c-5c03-8a91-10a9d1f1d971` | Necessary split, cost-saving split, split below threshold |
| MBD-300 | Main Board | `31962a4b-ab45-59ce-9ff6-a3aae8d97680` | Contract edge cases (expired, future, inactive, overlap) |
| CAM-400 | Camera Module | `b3877720-e627-53a8-9a99-df159635c17d` | Necessary split that needs an unpriced supplier |
| SPK-500 | Speaker | `dfab372b-9607-5d77-a80e-14551a1a2b23` | Three-supplier split, competing requests (effective availability) |
| CHP-600 | Charging Port | `d30e6edf-6e2a-5d0a-a95b-436b0c2f6ac2` | Cost-saving split at exactly 10% |

IDs are UUIDv5 values (`uuid5(namespace, "item:<SKU>")` in `app/supplier_service/seed.py`), so they stay the same after every reset.

## 3. Supplier Service data (`supplier_service`)

All suppliers are active, except where stated otherwise.

| Item | Supplier | Lead (days) | Arrival | MOQ | Available |
|---|---|---|---|---|---|
| DSP-100 | Alpha Displays | 10 | 11-12 | 200 | 1000 |
| DSP-100 | Beta Optics | 6 | 11-08 | 100 | 800 |
| DSP-100 | Gamma Screens | 4 | 11-06 | 50 | 2000 |
| BAT-200 | Volt Power | 7 | 11-09 | 100 | 400 |
| BAT-200 | Cell Works | 9 | 11-11 | 200 | 500 |
| BAT-200 | Ion Supply | 12 | 11-14 | 300 | 1500 |
| MBD-300 | Nova Silicon | 5 | 11-07 | 50 | 600 |
| MBD-300 | Orbit Circuits | 6 | 11-08 | 50 | 600 |
| MBD-300 | Pixel Boards | 8 | 11-10 | 100 | 600 |
| MBD-300 | Quartz Electronics | 15 | 11-17 | 100 | 1000 |
| CAM-400 | Lumen Optics | 6 | 11-08 | 100 | 300 |
| CAM-400 | Focal Point | 5 | 11-07 | 100 | 300 |
| CAM-400 | Prism Labs | 20 | 11-22 | 100 | 2000 |
| SPK-500 | Sonic Audio | 4 | 11-06 | 100 | 500 |
| SPK-500 | EchoTech | 5 | 11-07 | 100 | 300 |
| SPK-500 | Wave Acoustics | 6 | 11-08 | 100 | 300 |
| CHP-600 | PlugCo | 5 | 11-07 | 100 | 1000 |
| CHP-600 | ConnectRite | 5 | 11-07 | 100 | 400 |
| DSP-100 | Dormant Displays (`is_active = false`) | 1 | 11-03 | 10 | 5000 |

## 4. Purchasing Contracts (`purchasing_agent.purchasing_contracts`)

| Supplier | Item | Unit price | valid_from | valid_until | is_active | Price state on D |
|---|---|---|---|---|---|---|
| Alpha Displays | DSP-100 | 1,200.00 | 2026-01-01 | — | true | 1,200.00 |
| Beta Optics | DSP-100 | 1,250.00 | 2026-01-01 | 2026-12-31 | true | 1,250.00 |
| Gamma Screens | DSP-100 | — | — | — | — | Not Registered (no contract) |
| Volt Power | BAT-200 | 800.00 | 2026-06-01 | — | true | 800.00 |
| Cell Works | BAT-200 | 900.00 | 2026-06-01 | — | true | 900.00 |
| Ion Supply | BAT-200 | 1,000.00 | 2026-06-01 | — | true | 1,000.00 |
| Nova Silicon | MBD-300 | 1,100.00 | 2026-01-01 | 2026-10-31 | true | Not Registered (expired) |
| Nova Silicon | MBD-300 | 1,150.00 | 2026-12-01 | — | true | Not Registered (future) |
| Orbit Circuits | MBD-300 | 1,050.00 | 2026-01-01 | — | **false** | Not Registered (inactive) |
| Pixel Boards | MBD-300 | 1,400.00 | 2026-01-01 | — | true | **Excluded: `contract_overlap`** |
| Pixel Boards | MBD-300 | 1,350.00 | 2026-10-01 | — | true | (overlaps the row above) |
| Quartz Electronics | MBD-300 | 1,500.00 | 2026-01-01 | — | true | 1,500.00 |
| Lumen Optics | CAM-400 | 2,000.00 | 2026-01-01 | — | true | 2,000.00 |
| Focal Point | CAM-400 | — | — | — | — | Not Registered (no contract) |
| Prism Labs | CAM-400 | 1,800.00 | 2026-01-01 | — | true | 1,800.00 |
| Sonic Audio | SPK-500 | 300.00 | 2026-01-01 | — | true | 300.00 |
| EchoTech | SPK-500 | 320.00 | 2026-01-01 | — | true | 320.00 |
| Wave Acoustics | SPK-500 | 340.00 | 2026-01-01 | — | true | 340.00 |
| PlugCo | CHP-600 | 100.00 | 2026-01-01 | — | true | 100.00 |
| ConnectRite | CHP-600 | 87.50 | 2026-01-01 | — | true | 87.50 |

The overlapping Pixel Boards pair is bad data on purpose. The seed inserts it directly, bypassing the contract write check, so the selection-time exclusion path can be tested. The normal contract write path must reject it (see §6, T-CON-2).

## 5. Selection scenarios (expected deterministic outcomes)

Values verified by a reference calculation of the rules in `purchasing_agent_architecture.md` §6.

| ID | Request (item, qty, required date) | Expected outcome | Why |
|---|---|---|---|
| A1 | DSP-100, 500, 11-20 | **SINGLE** Alpha 500 = 600,000 | Cheapest priced single. Best split {Alpha 400, Beta 100} = 605,000. Gamma is faster but Not Registered, so it is not chosen. |
| A2 | DSP-100, 150, 11-20 | **SINGLE** Beta 150 = 187,500 | MOQ surplus: Alpha must order 200 = 240,000, despite its lower unit price. |
| A3 | DSP-100, 300, 11-07 | **SINGLE** Gamma 300, `cost ranking unavailable` | Only Gamma arrives in time (Alpha 11-12, Beta 11-08). Unpriced fallback. Dormant Displays is never considered (inactive supplier). |
| A4 | DSP-100, 300, 11-05 | **FAILED**, no feasible supplier, Constrained Quantity 0 | No active supplier arrives by 11-05. |
| B1 | BAT-200, 800, 11-12 | **NECESSARY_SPLIT** Volt 400 + Cell 400 = 680,000, latest arrival 11-11 | No single covers 800 (Ion arrives 11-14, too late). |
| B2 | BAT-200, 800, 11-20 | **COST_SAVING_SPLIT** Volt 400 + Cell 400 = 680,000 | The best single is Ion 800 = 800,000; the split saves 15%. Other splits: {Volt, Ion} 720,000, {Volt, Cell, Ion} 720,000, {Cell, Ion} 750,000. |
| B3 | BAT-200, 450, 11-20 | **SINGLE** Cell 450 = 405,000 | The best split {Volt 250, Cell 200} = 380,000 saves only 6.2% (< 10%). |
| B4 | BAT-200, 1000, 11-12 | **FAILED**, Constrained Quantity 900 | Volt 400 + Cell 500 = 900 < 1000; Ion is too late. |
| C1 | MBD-300, 300, 11-12 | **SINGLE** Nova 300, `cost ranking unavailable` | Nova (expired and future contracts) and Orbit (inactive contract) are Not Registered. Pixel is excluded (`contract_overlap`), and Quartz is too late. Nova arrives earliest. |
| C2 | MBD-300, 300, 11-20 | **SINGLE** Quartz 300 = 450,000 | The only priced usable supplier wins over faster unpriced ones. Pixel is still excluded. |
| D1 | CAM-400, 500, 11-10 | **NECESSARY_SPLIT** Focal 300 + Lumen 200, `cost ranking unavailable` | No single covers and Prism is too late. The only split includes unpriced Focal. Fallback allocation fills the earliest-arriving supplier first. |
| E1 | SPK-500, 1000, 11-12 | **NECESSARY_SPLIT** Sonic 500 + EchoTech 300 + Wave 200 = 314,000 | Three suppliers are needed: every pair is ≤ 800. |
| E2 | E2a: SPK-500, 400, 11-12; then E2b: SPK-500, 300, 11-12, while E2a's Leg is still PENDING | E2a: **SINGLE** Sonic 400 = 120,000. E2b: **SINGLE** EchoTech 300 = 96,000 | Effective availability: Sonic = 500 − 400 held = 100, so it can't cover E2b. Without the hold, E2b would pick Sonic 300 = 90,000. |
| F1 | CHP-600, 500, 11-20 | **COST_SAVING_SPLIT** ConnectRite 400 + PlugCo 100 = 45,000 | The best single is PlugCo 500 = 50,000. The split costs exactly 90%, so the saving is exactly 10%, the boundary, and it qualifies. |

## 6. Negotiation scenarios (supplier chat)

The tester plays the supplier in free text. Purchasing's interpretation is echoed back in each reply.

| ID | Base | Supplier behaviour | Expected result |
|---|---|---|---|
| N1 | A1 | Alpha: "ok, 500 by 12 Nov works" | Leg AGREED → request AGREEMENT_PROPOSED. Approve → COMMITTED, one scheduled receipt. |
| N2 | E1 | EchoTech: "we can only do 250" | Cap EchoTech at 250 and reallocate: Sonic 500 + EchoTech 250 + Wave 250 = 315,000. Wave's Leg is reopened with 250 (counts as a round for Wave). No date was stated, so none is assumed: EchoTech gets a revised offer of 250 by the required date 11-12 (a round for EchoTech) and must explicitly accept it. Only when Sonic, Wave and EchoTech have all accepted → AGREEMENT_PROPOSED. (With a stated on-time date, e.g. "250 by 7 Nov", EchoTech is agreed on its own terms at once.) |
| N3 | B1 | Cell Works: "max 300" (rounds 1–3) | Volt 400 + Cell 300 = 700 < 800, so no valid allocation, and re-sourcing finds none either (Ion arrives 11-14, too late). Purchasing counters Cell back with 400 while rounds remain. After round 3 the Leg is FAILED (`round_limit_exceeded`); the request is FAILED with Constrained Quantity 700; Volt's Leg is ABORTED (`split_failed`) and adds no scheduled receipt. |
| N4 | A1 | Alpha: "500 but delivery 25 Nov" | Late date: Purchasing counters with required date 11-20 and never changes the deadline (no re-sourcing: the supplier is asked to expedite first). |
| N5 | A1 | Alpha: "hmm let me see" ×3 | Two CLARIFICATION_REQUESTs (no round used), then the Leg is FAILED (`unclear_response`). Re-sourcing without Alpha: **SINGLE** Beta 500 = 625,000 (new Leg, offer 500 by 11-20); the request stays NEGOTIATING. |
| N6 | A1 | Alpha: "no, we can't" | Leg FAILED (`supplier_rejected`). Re-sourcing without Alpha: **SINGLE** Beta 500 = 625,000; the request stays NEGOTIATING. |
| N7 | A1 | No reply; clock moved past `response_deadline` | The next read only records it: session TIMED_OUT, Leg FAILED (`timeout`), request still NEGOTIATING with `re_sourcing_needed: true`, no new Leg. `POST .../re-source` then picks **SINGLE** Beta 500; a second call changes nothing. |
| N8 | B2 | Both agree, then the human rejects the approval | Request APPROVAL_REJECTED; both Legs ABORTED (`approval_rejected`); holds released. |
| N9 | A1 | LLM unavailable; supplier types "COUNTER 450 2026-11-12" | Fallback parser reads it (`interpretation_source = FALLBACK_PARSER`). Alpha capped at 450 can't cover 500 alone, so Purchasing re-sources with the threshold re-checked: the best split Alpha 400 + Beta 100 = 605,000 saves only 3.2% against Beta 500 = 625,000, so **SINGLE** Beta 500 wins. Alpha's Leg is ABORTED `no_longer_needed` (cap 450 remembered); Beta gets a new Leg and offer. |
| N10 | A1 | The same supplier message is delivered twice (same `message_id`) | The second delivery is ignored; no extra round. |
| N11 | A1 | The same `request_ref` is submitted twice | The second call returns the existing request; no new Legs. |
| N12 | B2 | Cell Works: "max 300" | Volt 400 + Cell 300 = 700 < 800: reallocation fails, so Purchasing re-sources (Ion arrives 11-14 ≤ 11-20). Ion alone = 800,000; {Volt 400, Ion 400} = 720,000 and {Volt 300, Cell 200, Ion 300} = 720,000 tie on cost and arrival, fewer suppliers wins. 720,000 is exactly 10% under Ion alone → **COST_SAVING_SPLIT** Volt 400 + Ion 400. Cell's Leg is ABORTED `no_longer_needed` (cap 300, 1 round used); Volt's Leg is unchanged; Ion gets a new Leg priced at its current contract (1,000.00). |
| N13 | N12 | Then Ion Supply: "max 350" | Volt 400 + Ion 350 = 750 < 800: reallocation fails. Re-sourcing brings Cell back (remembered cap 300 ≥ MOQ 200, 2 rounds left): no single covers; the only feasible combination is **NECESSARY_SPLIT** Volt 300 + Cell 200 + Ion 300 = 720,000. Cell gets a new Leg and Engine session (`max_rounds` 2) with a fresh offer of 200; its old Leg stays ABORTED. Volt gets a revised offer of 300 (a round); Ion is countered with 300 by 11-20. |

## 7. Pure-logic boundary cases (unit tests, inline data, not seeded)

- Cost-saving split at exactly 10% (qualifies) and at 9.99% (does not).
- A Leg forced to MOQ creates surplus that is counted in the cost.
- Tie-breakers: equal cost → earlier (latest) arrival → fewer suppliers → larger total effective availability → supplier names.
- Re-sourcing: a returning supplier whose remembered cap is below its MOQ, or whose remembered date is after the required date, is unusable; a supplier with no rounds left or that failed in the request is excluded; the threshold is re-checked.
- A supplier with effective availability < MOQ is unusable.
- A cost-saving split is never formed with an unpriced supplier.
- Contract write path rejects an overlapping active contract (T-CON-2); `valid_until < valid_from` is rejected.
- Contract on the boundary dates (`valid_from = D`, `valid_until = D`) is valid.
