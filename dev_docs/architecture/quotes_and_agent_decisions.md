# Quote-based feasibility and agents that decide

**Status: approved 2026-10-26 (QD-1 to QD-11, `DECISIONS.md`).** Build order §12: steps 1 and 2 built (think loop; D7 in Planning).

Related: `negotiation.md` (§4 messages, §6 how an agent decides, §7 owner queue, §9 stale), `high_level_architecture.md`,
each agent's note 2, `demo.md` §8 (scenarios), `DECISIONS.md` (NG-*, S8-1, IMP-2).

## 1. The problem

Two observations from the code and the demo runs (2026-10-25):

1. **Feasibility is central.** `planning_agent/plan.py` reads the other agents' data directly
   (`inventory.stock_position`, `hr.free_worker_hours`, `warehouse.free_receiving`,
   `purchasing.supply_lead_time_days`) and computes the customer's options alone. The owners are asked only afterwards,
   to confirm numbers Planning already chose. In the demo this shows as a star: every line goes through Planning.
2. **No agent decides anything.** With `ai_enabled = 1` the model rewords messages, reads chat and supplier text, and
   ranks repair alternatives after a worker absence (`planning_agent/ai.py`). Every other choice is one fixed rule:
   - Inventory, HR and Warehouse `answer()` try options in a fixed order and return the **first** that fits
     (full now → safety stock → later date → partial). The other options are computed and thrown away.
   - Planning accepts every OFFER, rejects every COUNTER_OFFER, and treats any REJECT as "the whole option failed"
     (`manager.handle_message`, `_fail_case`).
   - Planning secures the first option; competing orders are first come, first served.

   Consequence seen in LOAD-10: ten orders were offered the same free stock, the first ACCEPT won, the rest got
   `STALE`, each loser withdrew every other agreed negotiation, replanned once and 8 of 10 ended `NOT_FEASIBLE`.

`negotiation.md` §6 already allows "the LLM may suggest an offer or counter-offer inside the limits"; it was never built.

## 2. Goals and non-goals

Goals
- Each owner works out **what it can offer** from its own data and its own goals, and answers with options.
- At real **decision points**, an agent **thinks**: it reads the situation and its goals, looks up facts with its own
  tools, and proposes its own action and numbers (§5.1). Code only checks the hard limits. The thinking is recorded
  and shown.
- Demonstrate it on a **5-order scenario** (§9) where the choices visibly matter.

Non-goals
- No change to who owns which data or who commits which resource.
- The model never writes data or commits a resource itself; its proposal is checked by code first, then sent through the normal protocol.
- Load runs (LOAD-10/20/100) keep today's fixed rules (§10).
- No new infrastructure (no message broker, no extra service): the negotiation layer and work runner stay.

## 3. Rules that do not change

- Owner-only, atomic commitments; holds only on agreement; `COMMIT` re-checks (`negotiation.md` §8).
- Hard constraints are filtered by code before the model sees anything, and checked again after it answers.
- Priority is computed by the owner from trusted data, never taken from the sender's message (`negotiation.md` §7).
- Customer acceptance ≠ commitment ≠ production start.
- Every model call is logged in `observability.llm_calls`; no model call runs while a database lock is held.
- With the model off, slow or wrong, the agent's deterministic policy decides and the result stays correct.

## 4. Quote-based feasibility

### 4.1 Flow for a new customer request

```
Sales ──request──> Planning
Planning: BOM explosion + MRP + its own machine-hours  →  "needs": what is needed, how much, by when
Planning ──QUOTE_REQUEST (one per need)──> Inventory, HR, Warehouse, Purchasing   (in parallel, non-binding)
Each owner: works out its options from its own data, decides which to put forward and in what order  (§5)
Owners ──QUOTE (a list of options)──> Planning
Planning: combines the quotes into customer options (date × quantity), decides which to secure  (§5)
Planning ──REQUEST (today's protocol, binding path)──> owners  →  OFFER → ACCEPT → hold → AGREEMENT_PROPOSED
Planning ──options──> Sales ──> customer;  customer confirms ──> Planning COMMIT (unchanged)
```

What Planning keeps: the BOM, MRP, lead-time offsets and its **own** machine capacity (`work_center_days`). What
Planning gives up: reading other owners' free capacity to decide feasibility. The read modules stay for display and
for consistency checks, not for deciding.

### 4.2 Message types

Two new message types, outside the binding lifecycle of `negotiation.md` §4:

| Type | From → to | Contents | Effect |
| --- | --- | --- | --- |
| `QUOTE_REQUEST` | starter → owner | the usual terms (resource, quantity, needed_by, order_id, case_id) + `quote_id` | none; the owner answers within the response timeout |
| `QUOTE` | owner → starter | `options[]` (see below), `facts_version`, `valid_until`, the owner's short `rationale` | none; **no hold**, nothing reserved |

One `QUOTE` option:

| Field | Meaning |
| --- | --- |
| `option_id` | Stable within the quote |
| `kind` | `FULL_ON_TIME`, `PARTIAL_ON_TIME`, `FULL_LATER`, `USES_SAFETY_STOCK`, `OVERTIME`, `MOVED_WORKER`, `SPLIT_DELIVERY`, … (fixed list per owner) |
| `quantity`, `unit`, `available_from` | Numbers computed by code |
| `cost_to_owner` | What it costs the owner in its own terms (safety stock used, overtime hours, a slot others may want) |
| `rank` | The owner's own preference (1 = best for the owner) |

The quote session ends `QUOTED` when the answer arrives (or `EXPIRED`). A binding `REQUEST` that follows quotes the
`option_id` it is based on; the owner re-checks it like any request (`STALE` if the facts changed).

### 4.3 What each owner can quote (built from what `answer()` already computes)

| Owner | Options it already computes today and discards | Owner's own goal |
| --- | --- | --- |
| Inventory | full now · using safety stock · full on a later date · partial now | keep safety stock, serve the most urgent need first, avoid stock-outs |
| HR | hours as asked · overtime (if allowed) · hours shifted to later days · the hours that fit | no overtime unless needed, fair load, cover absences |
| Warehouse | slot / space on the day · later day · the pieces that fit | keep the dock below capacity, keep space for committed goods |
| Purchasing | supplier options (lead time, minimum order, price used only for selection, ADR-002) · split over suppliers | on-time supply at reasonable cost, reliable suppliers |

### 4.4 Direct links between owners (fewer lines through Planning)

Kept and added, each one an owner asking another owner for its own resource:
- Purchasing ↔ Warehouse receiving slot (built, WH-1).
- **Inventory → Purchasing (new):** when Inventory's quote has a shortfall, Inventory may ask Purchasing for a
  replenishment quote and include "full later via purchase" as an option. Purchasing still decides the purchase.
- Sales ↔ Planning stays the only door for customer orders.

## 5. Decision points

Only these points call the model. Everything else stays deterministic.

| # | Agent | When | Menu built by code | What the agent weighs | Fallback (no / bad answer) |
| --- | --- | --- | --- | --- | --- |
| D1 | Inventory | answering a QUOTE_REQUEST when stock is short | its feasible options (§4.3) | urgency from trusted dates, safety stock, other open needs for the same item | today's order: full → safety stock → later → partial |
| D2 | Inventory | several open requests for the same scarce item | the feasible allocations (who gets how much now / later) | due dates, slack (§7 of negotiation.md), partial vs late | smallest slack first, then FIFO |
| D3 | HR | quote or absence cover when hours are short | as asked / overtime / move a worker / later / partial | overtime limits, fairness, protected orders | today's `allocate` order |
| D4 | Warehouse | slot or space short | day / later day / partial | dock load, committed goods | first later day |
| D5 | Purchasing | choosing supplier option(s) and counter strategy | feasible supplier legs and splits | lead time, reliability seen so far, cost (selection only) | today's selection rules |
| D6 | Planning | combining quotes into customer options | feasible combinations (each a full plan) | customer date, risk, resources used, protected orders | PL-6 fixed ranking |
| D7 | Planning | a COUNTER_OFFER or a `STALE` / `INSUFFICIENT` REJECT during securing | re-ask the same owner · take the partial and ask Purchasing for the rest · accept a later date if the customer's date still holds · next option · replan | what is already held, customer date, attempts left | today: fail the option, try the next, replan once (S8-1) |
| D8 | Sales | which option to recommend to the customer | Planning's validated options | the customer's history and stated preferences | show all, in Planning's order |

Every menu item is a complete, valid action with its numbers already computed; the agent picks one key.

## 5.1 The agent thinks (not a menu picker)

The developer's requirement (2026-10-25): **the agent must think**. A menu of pre-computed keys is not enough. So at a
decision point the model is the agent's brain, working in a short loop:

```
OBSERVE   the situation: the request or event, the agent's goals and limits, its memory of this case and similar ones
THINK     reasons step by step in its own words (kept and shown as the agent's thinking)
USE TOOLS reads facts it needs, through the agent's own read-only tools (below); may call several before deciding
PROPOSE   an action with its own parameters: e.g. "offer O3 50 now and 10 on 2026-11-06", "counter O1 with the
          full 120 on 2026-11-09", "ask Purchasing for 70 batteries", "use 20 of safety stock"
CHECK     code validates the proposal against hard constraints and current facts (quantities, dates, ownership,
          safety-stock and overtime limits, facts_version). Not valid → the reason goes back to the model, which may
          revise once
ACT       a valid proposal is sent through the normal protocol; the thinking, tools used and the check are recorded
```

What the model may decide: which action to take and its parameters (quantity, date, split, who to ask, which
order to serve first, whether to use safety stock or overtime, what to counter with, when to give up), and the wording.
What it may not do: change data directly, exceed a hard limit, invent facts — the check refuses it.

Tools per agent (read-only, the agent's own data plus authorised reads; every result is from code):

| Agent | Tools |
| --- | --- |
| Inventory | `stock_position(item)`, `atp(item, day)`, `open_requests(item)`, `incoming(item)`, `order_due(order)` |
| HR | `free_hours(skill, day)`, `workers(day)`, `overtime_left(day)`, `commitments(order)` |
| Warehouse | `free_receiving(day)`, `free_space(zone, day)`, `deliveries(day)` |
| Purchasing | `supplier_options(item, qty, needed_by)`, `supplier_history(supplier)`, `open_purchases(item)` |
| Planning | `explode(product, qty)`, `machine_free(wc, day)`, `quotes(case)`, `held(case)`, `customer_date(order)` |
| Sales | `customer_history(customer)`, `options(inquiry)`, `preferences(customer)` |

The menu of §5 stays, but only as **hints** in the prompt and as the fallback when the model fails. The agent's
goals (§4.3) and memory (`negotiation.md` agent state: goals, preferred terms, limits, offer history) are part of
every prompt, so two agents in the same situation can decide differently because their goals differ.

### 5.2 Fewer model calls (free and local models)

The model budget is small (local `qwen3.5:4b`, or free cloud tiers with daily limits), so a decision costs **one
call** whenever possible:

- **Facts up front.** Code gathers the facts the agent's tools would return and puts them in the prompt. A tool round
  trip happens only when the agent asks for something that was not included (at most one extra call).
- **One call per agent per batch, never across agents.** An owner with several open requests decides them together
  in one call (D2 is exactly that: "who gets the scarce batteries"). Requests waiting at the same owner within a short
  window (starting value 2 s simulated-run time) are batched. **Two agents are never decided in one call**: one
  prompt deciding for Inventory and HR together would be a central brain and break the decentralization rule.
- **Think only when it matters.** No call when there is one valid option, when the request fits fully on time, or
  for wording (templates stay).
- Expected for S9: about 2–4 calls per order, 10–20 for the run.

### 5.3 Model providers and fallback chain

Default: local Ollama `qwen3.5:4b`. The agent writes its reasoning into its answer (`thinking`); the model's hidden
thinking mode stays off (measured 2026-10-26: it did not finish within 300 s on CPU; the visible way takes ~50 s). Optional: a chain of OpenAI-compatible providers (e.g. local Ollama, then free cloud tiers),
tried in order; a rate-limit (HTTP 429), timeout or error moves to the next; when all fail, the deterministic
fallback decides. Each provider is configured by URL, model and API key in `.env` (never in code); the call log
records which provider answered. Free tiers may use prompts for training: only simulated factory data goes in.

## 6. How a decision runs

```
1. Code reaches a decision point → builds the menu, the agent's goal, the facts it may use (trusted reads only)
   and the fallback choice → stores a DECIDE work item (inside the normal transaction)
2. Work runner (long mode, no lock held) → the think loop of §5.1: tool calls, then a structured proposal
   {"thinking": "...", "action": "<action type>", "params": {...}, "reason": "<one sentence>"}
3. New transaction: re-read the facts; validate the action and its parameters (hard constraints, facts_version)
   → apply it; if invalid, one revision round with the check's reason; still invalid → fallback
4. Record the decision (§6.1) and continue the protocol (send the QUOTE / REQUEST / reply)
```

Reuses `llm.reasoning.propose` and the pattern of `planning_agent/ai.py` (`check_ai_choice`). One shared helper
(`app/agent_decisions/`) builds prompts, calls the model, validates and records; each agent supplies its menu,
goal and fallback.

### 6.1 Decision record

Stored in the deciding agent's own `audit_log` (`event_type = "DECISION"`, details JSONB), so no new table:
`decision_point`, `case_id`, `order_id`, `thinking` (the agent's reasoning text), `tools` (each call and result),
`action` + `params`, `check` (passed / refused and why), `menu` hints, `fallback_key`, `chosen_by`
(`MODEL` / `MODEL_REVISED` / `FALLBACK`), `reason`, `fallback_reason` (`AI_OFF`, `TIMEOUT`, `INVALID`, `NOT_ON_MENU`, `STALE`),
`llm_call_id`. The observer exposes them in the timeline as `source = "decision"`.

## 7. Stale offers and competing orders

- Quotes reserve nothing, so two orders can be quoted the same stock. The binding path stays as today (hold on
  agreement, re-check on commit); the change is what happens on `STALE`: decision D7 instead of dropping the case.
- Re-asking is bounded (§10) and keeps what is already held, so one lost item no longer releases everything.
- Owners see their own open requests (D2) and can answer the more urgent one first, instead of first come first served.

## 8. What the demo shows

- **Quote board** per order: each owner's options as cards (full now / partial / later / overtime), the one it ranked
  first, and its one-line reason.
- **Thinking cards** in the agent drawer and the disruption view: what the agent saw → its thinking → the facts it
  looked up → what it proposed → the check → what the fixed rule would have done. When the fallback decided, the card
  says why (AI off, timeout, invalid).
- The agent network gets direct lines (Inventory → Purchasing, Purchasing ↔ Warehouse) instead of only Planning spokes.

## 9. Demo scenario S9: five orders, tight factory

Factory A (default state), AI on, five structured customers on day 1. Numbers are starting values to tune.

| Order | Product | Qty | Wanted in | Why it is interesting |
| --- | --- | --- | --- | --- |
| O1 | Phone | 120 | 6 days | needs main boards (MB stock 20) and batteries |
| O2 | Tablet | 80 | 6 days | 2 batteries per tablet: competes with O1 for batteries and MB |
| O3 | Phone | 60 | 4 days | urgent: inside the purchase lead times, must come from stock or partial |
| O4 | Tablet | 100 | 9 days | can wait for purchased chips (lead 7) |
| O5 | Phone | 150 | 12 days | large, flexible date |

Expected decision points (not fixed outcomes — the agents decide):
- D1/D2 at Inventory: 50 phones in stock and 20 main boards; O3 is the most urgent. Does Inventory put "50 now" to
  O3 and offer O1 "full later"? Does it release safety stock of batteries?
- D3 at HR: assembly hours for O1+O2 on the same days; overtime vs a later day.
- D5 at Purchasing: chips (lead 7, minimum 250) for O4 and O5 — one combined purchase or two?
- D6/D7 at Planning: when O2 loses batteries to O1, re-ask, take partial and buy the rest, or offer the customer a
  later date.
- D8 at Sales: which option each customer is recommended (structured customers still choose by their fixed rule).
- Then day 3: a worker absence (`WORKER_ABSENT`, A1, 2 days) → D3 and D7 again on committed orders.

Success: every order gets an answer (committed, later date offered, or a clear "not feasible" with the reason); no
double booking; each decision has a record; with AI off the run still completes with the fallbacks.

## 10. Limits

| Limit | Starting value | Why |
| --- | --- | --- |
| Decision points with the model | only D1–D8; only when more than one valid option exists | a single option needs no thinking |
| Model calls per decision | 1, at most + 1 tool round + 1 revision | facts go into the prompt (§5.2) |
| Model calls per run (S9) | about 10–20 | free and local budgets |
| Model timeout per decision | 90 s, then fallback | ~50 s per call measured on this laptop's CPU |
| AI default | **on** for runs with ≤ 10 orders; off for load runs | the agents think in the demo; load runs measure throughput |
| Re-asks after `STALE` (D7) | 2 per need | no endless loops (matches WH-1) |
| Quote validity | until the end of the simulated day | quotes are hints, not promises |
| AI decisions in a run | on only when the run has ≤ 10 orders (setting `ai_decision_max_orders`) | load runs keep fixed rules |
| Prompt facts | trusted reads only, no free text from other agents | no prompt injection between agents |

## 11. Fallbacks and failure modes

| Failure | What happens |
| --- | --- |
| AI off (`ai_enabled = 0`) | every decision point uses its fallback; behaviour equals today's except quotes replace direct reads |
| AI wording off (`ai_wording_enabled = 0`, the default) | negotiation messages keep their template text; the model is used only at decision points. Rewording every message one by one on the shared local model added ~5 s (GPU) to 30 s+ (CPU) per message |
| Model timeout / error / invalid JSON | fallback; recorded with the reason |
| Key not on the menu, or a number in the reason that is not in the menu | fallback; counts toward "repeated invalid LLM proposals" (escalation, `negotiation.md` §8) |
| Chosen option no longer valid when applied (facts changed) | re-build the menu once; then fallback |
| Owner does not answer a QUOTE_REQUEST in time | Planning treats that need as "not quoted" and can only offer options without it (or a later date) |
| Re-ask limit reached | D7 falls back to "next option / replan once" (S8-1) |

## 12. Build order (after approval)

Each step tested, small, behind settings; the frontend card for each step comes with it.

1. **[built]** Shared think loop (§5.1: prompt with goals and memory, read-only tools, structured proposal, validation with one
   revision, fallback) + decision record + observer `source = "decision"` (no behaviour change, fake model tests).
2. **[built]** D7 in Planning (`planning_agent/decisions.py`): RE_ASK, ACCEPT_COUNTER (only when the full quantity still
   comes in time — a later date for the customer goes through REPLAN), PARTIAL_AND_BUY, NEXT_OPTION, REPLAN. Applies to new
   requests while an option is being secured; repairs, customer changes and commits keep their fixed handling.
3. Quote messages in the negotiation layer; Inventory quotes (D1, D2); Planning reads Inventory's quote instead of
   `stock_position`.
4. HR, Warehouse, Purchasing quotes (D3–D5); Planning stops reading their free capacity for feasibility (D6).
5. Scenario S9 + quote board + decision cards; Sales recommendation (D8).
6. Inventory → Purchasing direct replenishment quote.

## 13. Open decisions (to approve)

| ID | Question | Recommendation |
| --- | --- | --- |
| QD-1 | New message types `QUOTE_REQUEST` / `QUOTE`, or a flag on `REQUEST`? | New types: a quote must never be mistaken for a binding step |
| QD-2 | Planning keeps its own machine-hours, or a separate "production capacity" owner? | Planning keeps it (no seventh agent) |
| QD-3 | Decision records in each agent's `audit_log` or a shared table? | Each agent's own `audit_log` (ownership) |
| QD-4 | Is Inventory allowed to ask Purchasing directly (§4.4)? | Yes, for a quote only; Purchasing decides |
| QD-5 | AI decisions only for small runs (`ai_decision_max_orders`)? | Yes, 10 |
| QD-6 | Does D7 change S8-1 ("replan once")? | Yes: re-ask first (≤ 2), then S8-1 |
| QD-7 | The agent thinks and proposes its own action and parameters (§5.1), code only validates; menu = hints + fallback | Yes (developer's requirement 2026-10-25) |
| QD-8 | Model size: `qwen3.5:4b` may be too weak for multi-step tool use | Try 4B first on S9; if proposals fail the check often, move to a larger local model (decision then) |
| QD-9 | Show the agent's thinking text in the UI? | Yes, collapsed under each thinking card |
| QD-10 | Model for now | Developer decided 2026-10-25: local `qwen3.5:4b` first, thinking on for decisions |
| QD-11 | Provider fallback chain (free cloud tiers after local) and one-call-per-agent batching (§5.2–5.3)? | Batching per agent: yes. Provider chain: later, optional, after S9 runs on the local model |
