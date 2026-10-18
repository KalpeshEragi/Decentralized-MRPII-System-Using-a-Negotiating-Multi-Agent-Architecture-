# Supplier: Interface (Test-Channel Chat)

**Status:** implemented (Purchasing tickets 04–11). A test channel, not a production supplier portal.
**Code:** page `backend/app/purchasing_agent/test_channel/supplier_chat.html`; routes in `backend/app/purchasing_agent/api.py`;
views in `views.py` (`conversations`, `conversation`); reply handling in `negotiation.py`; texts in `messages.py`.
**Rules in detail:** `../purchasing_agent/purchasing_agent_architecture.md` §7.

## 1. The page

`GET /purchasing/test-channel` serves a WhatsApp-like page. The tester is the supplier.

- Left: one conversation per Leg, newest first: supplier name, SKU, quantity, required date, request ref, round
  `n/max`, Leg status.
- Right: the messages (type and round shown on each bubble) and a text box. Enter sends, Shift+Enter adds a line.
- The box is enabled only while the Engine session is `OPEN`.
- The page polls every 2 s. Text is drawn with `textContent` (never parsed as HTML).
- Each send gets a new random `message_id` (UUID).

## 2. Routes

| Route | Does |
| --- | --- |
| `GET /purchasing/test-channel` | The chat page |
| `GET /purchasing/test-channel/conversations` | All conversations (times out overdue Legs first) |
| `GET /purchasing/test-channel/conversations/{leg_id}/messages` | One conversation with its messages |
| `POST /purchasing/test-channel/conversations/{leg_id}/messages` | Body `{message_id, text}` (text 1–2000 chars). `201` handled; `200` duplicate `message_id`, ignored; `409` closed / past deadline / `offer: superseded`; `409 CONFLICT` `message_id` used on another Leg; `404` unknown Leg |

## 3. Message flow (one Leg)

```text
Purchasing: OFFER (quantity, delivery by required date)           round 1
Supplier:   free-text reply
Purchasing: "Understood: ..." echo, then one of:
            - agreed (CONFIRMATION)                 → Leg AGREED
            - COUNTER_OFFER (required date)         → next round
            - CLARIFICATION_REQUEST (no round, max 2 per pending offer)
            - closed (CONFIRMATION)                 → Leg FAILED
Later, Purchasing may send: a revised offer as COUNTER_OFFER (reallocation, new round), a CANCEL
(another Leg failed, no longer needed, manual abort, approval rejected) or a CONFIRMATION on timeout.
```

Max 3 rounds (`PURCHASING_MAX_ROUNDS`). Response deadline 24 h after each message awaiting a reply
(`PURCHASING_RESPONSE_DEADLINE_HOURS`), checked lazily; a late reply gets `409`.

## 4. Accepted replies

Free text. The shared LLM reads it into `{action, quantity, delivery_date}`; a term must really be written in the reply.
Without the LLM (or on invalid output) the strict fallback parser reads it, any letter case:

| Format | Meaning |
| --- | --- |
| `ACCEPT` | Accept the current offer |
| `COUNTER <quantity> <yyyy-mm-dd>` | Offer another quantity and/or date |
| `REJECT` | Cannot supply |
| anything else | Unclear → clarification request |

Purchasing then validates: a date later than required or in the past is never agreed; another quantity becomes the
supplier's Quantity Cap and the procurement is reallocated among the already-selected suppliers.

## 5. What the supplier sees and never sees

| Sees | Never sees |
| --- | --- |
| Own supplier name, item name and SKU, quantity asked, required/delivery date | Any price, contract or cost |
| Round count and limit, Leg and negotiation status | Other suppliers' names or quantities in Purchasing's text (guardrail) |
| Purchasing's echo of how it read each reply | Selection reasoning or audit |

Note: the page lists **every** Leg's conversation (test build, no access control), so a tester can open any supplier's chat.
A supplier may briefly see the template offer before the LLM wording replaces it.
