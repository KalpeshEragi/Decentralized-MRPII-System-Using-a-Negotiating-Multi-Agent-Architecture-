# Rule editor, event manager and a factory that keeps moving

**Status: approved 2026-10-27 (RE-1..5, EM-1..3, RP-1..4, `DECISIONS.md`).** Three requirements designed together
because they touch the same settings, events and agents. Build order §6: step 1 (event manager) built.
Direction kept: the LLM is each agent's brain at decision points; code validates (QD-7,
`quotes_and_agent_decisions.md`).

## 1. What exists today (inspected 2026-10-27)

| Area | Today | Gap |
| --- | --- | --- |
| Business rules | `simulation/settings.py`: one versioned table with documented defaults (overtime, safety-stock release, time fence, horizons, …). Per-item safety stock is Inventory's own data. Some rules are code constants (Sales offer validity 24 h, Planning `MAX_REASKS`, Purchasing `SLOT_RETRIES`). | No owner per rule, no grouping, no bounds, no screen; simulator, system and business settings are mixed; agents cannot get user guidance |
| Events | `events/channel.py` `CATALOGUE`: event → publisher, subscribers. Agents call `channel.subscribe` in their own code. | No payload definition, description or version; several listed subscribers have no handler (e.g. `PlanCommitted` → Inventory, Warehouse, HR); no way to see or retire an event |
| Idle factory | With no customer orders nothing happens. Inventory may lend safety stock to an urgent order (RD-6) and publishes `SafetyStockBreached`. | RD-6's refill ("Planning immediately plans a refill") is **not built**: nobody subscribes. No target stock level, no stock-replenishment orders |

## 2. Rule editor

### 2.1 What a rule is

One registry (`backend/app/rules/registry.py`) lists every **business rule** once:

| Field | Meaning |
| --- | --- |
| `key` | e.g. `overtime_max_hours_per_day` |
| `owner` | `GENERAL` or the agent that owns it (`SALES`, `PLANNING`, `INVENTORY`, `PURCHASING`, `WAREHOUSE`, `HR`) |
| `label`, `description` | plain words for the screen |
| `kind` | `number`, `percent`, `hours`, `days`, `yes_no`, `per_item` |
| `unit`, `min`, `max`, `default` | the bounds keep the system working; a value outside them is refused |
| `visibility` | `BUSINESS` (shown and editable) or `SYSTEM` (never shown: protocol, simulator and AI plumbing) |

Three kinds of rule:

1. **Parameters** — one value (e.g. overtime per day 2 h → 4 h). Stored in the existing versioned settings table.
2. **Per-item policies** — one value per item (e.g. keep battery stock at least 20 % of its maximum). Stored by the
   **owner** through its own input (Inventory's stock policy), never in a shared table (ownership rule).
3. **Agent guidelines** — free sentences the user adds or deletes per agent, e.g. "Prefer overtime to a late
   delivery" (HR) or "Keep chips above 30 % before the festival season" (Inventory). They go into that agent's
   think-loop prompt as guidance. They never override a parameter or a hard check: the validator still decides.

Add / update / delete:

| Kind | Add | Update | Delete |
| --- | --- | --- | --- |
| Parameter | — (the list is fixed by the registry) | change the value | reset to default |
| Per-item policy | add a policy for an item | change it | remove (item falls back to the general value) |
| Agent guideline | add a sentence | edit it | delete it |

### 2.2 Which rules are shown (first list)

| Tab | Business rules (shown) |
| --- | --- |
| General | time fence (days), hold validity (days), later-date horizon (days), dampener days and quantity share |
| Sales | offer validity (hours, today a constant), Planning wait limit (minutes), AI failures before staff |
| Planning | option re-picks, release lead (days), re-asks after a stale answer (today `MAX_REASKS`) |
| Inventory | safety-stock release share (%), release only within slack (days), per item: safety stock and **target stock level (% of max)** (§4) |
| Purchasing | slot retries; supplier-selection preferences already in Purchasing's config |
| Warehouse | receiving and shipping per day, zone capacities (today changed only by a trigger) |
| HR | overtime per day (hours), overtime per week (hours) |

Hidden (`SYSTEM`): simulation start day, quiet limit, simulated suppliers, customer driver settings (they belong to the
simulator panel), `ai_enabled`, `ai_decision_max_orders`, seeds, protocol limits (rounds), work-runner and timeouts.

### 2.3 Doors and screen

- `GET /rules` (grouped by owner, with value, default, bounds, version), `PUT /rules/{key}`,
  `PUT /rules/items/{item}/{key}`, `DELETE …` (reset), `POST/PUT/DELETE /rules/guidelines/{agent}`. Write doors need
  the simulator door key. Every change is versioned and audited (who, when, old → new).
- Agents read rules live (as `setting()` does today); a change applies from the next decision.
- Frontend page **Rules**: tabs General · Sales · Planning · Inventory · Purchasing · Warehouse · HR; each rule as a
  card (value, unit, plain description, default, bounds, reset); per-item table for Inventory; guideline list with add,
  edit, delete; a change history.
- Optional "command" box: the user types "allow 4 hours of overtime a day"; the model proposes a rule change
  (`overtime_max_hours_per_day: 2 → 4`), shown for the user to confirm; nothing changes without the click (§5 RE-4).

## 3. Event manager

### 3.1 One definition per event

`backend/app/events/catalogue.py` holds every event once:

| Field | Meaning |
| --- | --- |
| `name`, `version` | e.g. `SupplierDeliveryDelayed` v1 |
| `publisher` | the only agent allowed to publish it |
| `subscribers` | who receives it, each with `required` (must have a handler) or `optional` |
| `payload` | a Pydantic model: the fields, their types, required or not |
| `description` | one sentence: what fact it announces |
| `status` | `ACTIVE`, `DEPRECATED` (still delivered, publishers warned, shown amber), `RETIRED` (refused) |

### 3.2 What the manager does

- **Publish check:** unknown or retired event, wrong publisher, or a payload that does not match → refused (tests and
  development) or logged loudly (demo), so a broken event never spreads silently.
- **Subscribe check:** only pairs in the catalogue; a handler for a retired event is refused at start.
- **Start-up report:** required subscribers without a handler, handlers nobody publishes to, deprecated events still
  published. Shown in the screen and in the log.
- **Adding an event:** one catalogue entry + the publisher's call + each subscriber's handler. No other file changes.
- **Removing an event:** mark `DEPRECATED`, stop publishing, then `RETIRED`; old stored events stay readable.
- **Live numbers:** per event: published count, last published, deliveries pending / failed per subscriber.
- `GET /events/catalogue` and a frontend page **Events**: table (event, publisher, subscribers, status, counts), a
  publisher × subscriber matrix, and per event its payload fields and recent examples.

The catalogue stays in code (reviewed, versioned with the handlers); the screen is read-only in the first step (§5 EM-2).

## 4. A factory that keeps moving (replenishment)

### 4.1 The idea

Stock that was lent to a customer order (safety stock) or simply used up is refilled, so the factory works on quiet
days too: production for stock on the lines, purchases arriving at the dock. Customer orders always come first.

### 4.2 Who does what (ownership kept)

1. **Inventory** keeps per item a **safety stock** and a **target stock level** (rule editor, §2). Each morning and
   after stock moves, it compares projected available stock (ATP) with its targets. When an item falls below, it
   publishes a fact: `ReplenishmentNeeded {item, quantity, needed_by, reason: SAFETY_STOCK_USED | BELOW_TARGET}`.
   Inventory does not plan production or choose suppliers.
2. **Planning** subscribes. For a made item (MAKE) it plans a **stock production order** (`for_kind = STOCK`) on
   free machine- and worker-hours only, and secures components and hours by the normal negotiation. For a bought
   item it asks **Purchasing** for supply for stock. Stock orders never take resources already promised to a customer
   order, and inside the time fence they are not moved.
3. **Purchasing** buys as today (supplier choice, receiving slot with Warehouse).
4. The **RD-6 refill**: Planning's handler for `SafetyStockBreached` is exactly this path (reason
   `SAFETY_STOCK_USED`), so the approved but missing refill is built here.

### 4.3 Where the agents think (think loop, design §5.1)

| # | Agent | Decision | Fallback |
| --- | --- | --- | --- |
| D9 | Inventory | which items to refill first and how much (target, upcoming demand, money tied up, space) | refill every item below target to target, most urgent first |
| D10 | Planning | when to produce for stock (which free days, batch size) without hurting customer orders | earliest free capacity, one order per item |
| D1/D2 | Inventory | lend safety stock to an urgent customer order or not (today a fixed share and slack rule) | today's RD-6 rule |

### 4.4 What the demo shows

A scenario **IDLE**: no customer orders; several items start below target. Over the days: Inventory publishes
`ReplenishmentNeeded`, Planning plans stock orders (thinking cards show why), lines run, trucks arrive, stock rises
to target. Then an urgent order arrives: Inventory lends safety stock (D1), Planning refills it afterwards.

## 5. Open decisions (to approve)

| ID | Question | Recommendation |
| --- | --- | --- |
| RE-1 | One rule registry with owner, bounds and `BUSINESS`/`SYSTEM` visibility over the existing settings table | Yes |
| RE-2 | Per-item policies stored by the owning agent (Inventory) through its own input | Yes (ownership) |
| RE-3 | Agent guidelines: free sentences in the agent's prompt, never overriding hard checks | Yes |
| RE-4 | Natural-language "command" box that proposes a rule change for the user to confirm | Later, after the editor works |
| RE-5 | Code constants (offer validity, re-asks, slot retries) move into the registry | Yes, one by one |
| EM-1 | One event catalogue with payload models, status and checks at publish and subscribe | Yes |
| EM-2 | Event screen read-only (no runtime subscribe / unsubscribe from the UI) | Yes: changing wiring at runtime could lose events |
| EM-3 | Payload mismatch: refuse in tests, log loudly in the demo | Yes |
| RP-1 | New event `ReplenishmentNeeded` (Inventory → Planning, Purchasing) | Yes |
| RP-2 | Target stock level per item as % of a maximum stock per item (the "20 % / 30 % full" rule) | Yes; maximum per item set in the rule editor |
| RP-3 | Stock production orders use only free capacity and never displace customer commitments | Yes |
| RP-4 | Decision points D9 (Inventory refill) and D10 (Planning stock production) through the think loop | Yes |

## 6. Build order (after approval)

1. **[built]** Event manager (catalogue, checks, report, doors, Events page) — the base for the new event of step 4.
   Code: `backend/app/events/catalogue.py`, `manager.py`, `api.py`; page `frontend/app/events/page.tsx`.
2. Rule registry, rule doors, Rules page with parameters (no per-item yet).
3. Per-item policies (Inventory: safety stock, target level, maximum) and agent guidelines in prompts.
4. Replenishment: `ReplenishmentNeeded`, Planning's stock orders, Purchasing for stock, RD-6 refill; scenario IDLE.
5. D9, D10 and D1 through the think loop; thinking cards for them.
