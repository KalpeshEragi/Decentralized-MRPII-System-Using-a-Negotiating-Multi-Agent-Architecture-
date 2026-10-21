# How Real ERP/MRPII Systems Handle Purchasing and Supplier Communication

**Status:** Research report for developer review (2026-10-19). It changes no decision, doc or code. It describes
industry practice only. It does not compare anything to this project; the developer does that.

## How to read this report

| Label | Meaning |
| --- | --- |
| **[D]** | Official product documentation, read in full for this report |
| **[D-s]** | Official product documentation, seen only as a search-result excerpt (weaker evidence) |
| **[S]** | Standard message spec (X12, EDIFACT, GS1), read through a reference site that reproduces the spec |
| **[C]** | Practitioner/community post (SAP Community etc.), not official |
| **[W]** | Secondary web source (glossary, vendor marketing) |
| **[B]** | Textbook knowledge, **not re-checked online** for this report |
| **[U]** | **Unconfirmed**: searched for, but no trustworthy source found |

Citations like `[S8]` point to the source list at the end.

Important limits:
- Many SAP facts come from SAP Learning (official training) or older SAP Help pages (release 4.6C/4.7). The core
  purchasing logic has been stable for years, but field names and menus may differ in current S/4HANA.
- Several Dynamics 365 facts come from archived AX 2012 docs. These are marked.
- Official UN/EDIFACT pages (unece.org) blocked access; EDIFACT text is from sites that reproduce the standard.
- ASCM/APICS definitions (dictionary, SCOR) are behind a paywall. ASCM-specific wording is **not confirmed**.
- Infor is thinly covered: only one Infor M3 page was found.

---

## 1. Source determination (who do we buy from?)

### What systems do

- **SAP: fixed search order.** In the planning run (MRP) SAP looks for a source in this order: quota arrangement →
  source list entries flagged for MRP → scheduling agreements → contracts → info records with "automatic sourcing".
  If nothing matches, it creates a purchase proposal **without a source** [D] [S1].
- **SAP manual requisition:** quota arrangement → source list (if several valid entries, the one marked **Fixed**
  wins) → outline agreements → info records. If there is more than one candidate, the user picks from a list [D] [S1].
- **SAP fixed source:** only one source of a category can be fixed at a time; a fixed outline agreement beats a fixed
  info record [D] [S1].
- **SAP blocked sources:** a supplier-level purchasing block stops new POs, RFQs, outline agreements, quota and
  source list entries for that supplier. Goods receipts against open documents still work [D-s] [S2]. A source list
  "blocked" entry stops that one source being used or assigned manually [D-s] [S2].
- **SAP quota arrangements (split %):** Quota rating = (quota-allocated quantity + quota base quantity) / quota.
  The source with the **lowest rating** gets the next requirement. On a tie, the first item wins, not the one with
  the highest quota [D] [S3]. The quota-allocated quantity is the running total already ordered from that source;
  the base quantity is a manual correction used when a new source joins [D] [S3]. Only MRP can **split** one
  requirement across sources; a manual requisition goes to one source [D] [S3]. A "splitting quota" variant divides
  the quantity by quota share instead [D-s] [S4].
- **SAP info records and prices:** an info record holds the material–supplier relationship and its conditions
  (prices). Conditions in info records and contracts are **time-dependent** (validity periods, price scales by
  quantity); conditions in a PO are fixed for that PO [D-s] [S5].
- **SAP contracts (outline agreements):** valid for a set period and a target quantity or target value. Each
  release creates a new PO. Exceeding the target or ordering outside validity gives a **warning**, which can be set
  to an **error** to block the release [D] [S6].
- **Oracle sourcing rules:** sources have a **rank** and an **allocation %**; allocations within a rank must add up to
  100%. Rank 1 is the highest priority [D-s] [S7]. Planning splits by percentage, but a single requisition in
  Purchasing goes to the supplier with the highest allocation [D-s] [S8]. In backlog management, if the top source
  lacks supply, the next one is checked for the full quantity [D-s] [S9].
- **Oracle Approved Supplier List (ASL):** each ASL status allows or prevents business rules: PO approval, sourcing,
  schedule confirmation [D] [S10]. The ASL entry points to the source document (agreement/quotation) to use [D-s] [S8].
- **Odoo vendor pricelist:** per vendor and product: minimum quantity for the price, unit price, delivery lead time.
  A **sequence** field orders vendors when several exist [D] [S11].
- **Dynamics 365:** a vendor can be put **on hold**, including a hold type that blocks only new POs while open
  invoices and payments still go through [D-s] [S12].
- **Currency handling:** no clear official source found on how source selection treats currency [U].

### Common rules / constraints

- Source selection is **deterministic master data**, not a free choice per order: priority lists, fixed flags, blocks,
  validity dates.
- A blocked or unapproved supplier **cannot** get a PO. Blocks stop new business but let open business finish.
- Prices and contracts have **validity periods**. Outside them, the system warns or blocks.
- Split sourcing uses explicit percentages and a running history (what was already ordered), so splits balance over
  time, not per order.

### Business value

- Repeatable, auditable supplier choice; buying under negotiated contracts instead of ad-hoc prices; spreading
  volume to keep second sources alive.

---

## 2. Order quantity rules

### What systems do

- **Lot sizing runs after net requirements:** the system first calculates the shortage, then applies the lot-size
  procedure, then rounds [D] [S13]. The order quantity need not equal the shortage [D] [S13].
- **Min/max lot size and rounding (SAP):** minimum and maximum lot size in the material master; a **rounding value**
  rounds up to a multiple (pack size); a **rounding profile** uses thresholds (example: 21 → 25, 74 → 80) [D] [S13].
- **Oracle order modifiers:** fixed order quantity (several orders of that size if needed), fixed lot multiple
  (need 110, multiple 100 → order 200), min and max order quantity [D-s] [S14] [S56]. Min order quantity and lot
  multiple can also be set **per supplier** [D-s] [S15].
- **Dynamics 365:** minimum, maximum and multiple on default order settings; action messages respect them so they
  "never cause undersupply" (demand 60 + 30 with multiple 20 → increase of 40) [D] [S16].
- **Odoo:** the vendor pricelist minimum quantity is the smallest quantity that gets the listed price [D] [S11].
- **EOQ** (economic order quantity, balancing ordering cost against holding cost) is standard textbook lot sizing [B].
  Not checked in a current ERP doc for this report.
- **Over/under-delivery tolerances (SAP):** an underdelivery is accepted as a partial delivery with a warning; an
  underdelivery tolerance % accepts it silently. An overdelivery is an **error** unless within the overdelivery
  tolerance %, or the "unlimited" flag is set [D-s] [S17] [S18]. Defaults come from material master, info record
  (supplier-specific), or the PO line [D-s] [S17].
- **Delivery completed (SAP):** setting it closes the open quantity even if not all goods arrived [D-s] [S17].
- **Dynamics 365:** over/underdelivery % define how far received quantity may exceed or fall short of the PO
  quantity (archived AX glossary) [D-s] [S19].
- **Partial deliveries:** SAP Business Network lets suppliers split a line into **confirm / backorder / reject**
  quantities [D-s] [S36]; X12 has a line status "accepted, partial shipment, balance backordered" [S] [S41].
- **Scheduling agreements (SAP):** one long-term agreement with a rolling **delivery schedule** instead of many POs.
  - **Firm zone:** schedule lines treated as firm orders (supplier may produce).
  - **Trade-off zone:** supplier may buy materials; lines less binding [D-s] [S20].
  - **Forecast schedules** are for planning only, not binding; **JIT schedules** cover the near term [D-s] [S20].
  - Practitioners say the buyer is liable for material cost in the trade-off zone if cancelled [C] [S57]. This
    depends on the contract and was **not confirmed** in official docs.

### Common rules / constraints

- Order quantities are shaped by supplier rules (MOQ, pack multiple, max) **after** the need is calculated.
- Rounding always goes **up** in these systems so the order covers the need (one Oracle Cloud doc allows rounding
  down when rounding is off [D-s] [S15]).
- Receipts are checked against tolerances; outside tolerance is a warning or a hard error.

### Business value

- Fewer, cheaper orders; matching supplier packaging; controlled acceptance of short/over shipments; stable
  supplier capacity through firm/trade-off zones.

---

## 3. Lead times and dates

### What systems do

- **SAP external procurement has three times** [D-s] [S21]:
  - **Purchasing processing time** (working days for the buyer to turn a requisition into a PO; per plant).
  - **Planned delivery time** (calendar days for the supplier; in material master, info record or agreement).
  - **Goods receipt processing time** (working days from receipt to available stock).
  - MRP schedules **backward** from the requirement date through these times [W] (TechTarget, see [S21] notes).
- **Odoo:** expected arrival = PO confirmation date + vendor lead time. Plus a global **purchase security lead time**
  (buffer for supplier delays) and **days to purchase** (time the vendor needs to confirm the RFQ) [D] [S22]. The
  Odoo page is inconsistent about which direction the security lead time moves the date [D] [S22].
- **Dynamics 365 time fences** [D] [S23]:
  - **Freeze:** existing planned orders are not changed and no new ones are made.
  - **Firming:** planned purchase orders are auto-converted to real POs (only if the item has a vendor).
  - **Action message fence:** how far ahead change suggestions are made.
  - **Calculated delays:** if a date can't be met, plan for the earliest feasible date.
  - **Negative days:** how late an existing receipt may be before a new order is created instead.
- **Action / exception messages:**
  - Dynamics 365: **Advance, Postpone, Increase, Decrease**. They are suggestions: "You decide whether to make the
    suggested changes." They never cut below safety stock and never postpone safety-stock supply [D] [S16].
    Apply component actions before parent actions, then re-plan [D] [S16].
  - SAP: rescheduling check proposes **bring forward** (reschedule in) for a firm receipt instead of a new order
    [D-s] [S24]. Practitioners list exception 10 = bring forward, 15 = postpone, 20 = cancel; tolerances and a
    rescheduling horizon suppress small changes [C] [S25].
- **Expediting:** SAP sends up to three **reminder / urging letters** at set day offsets from the due date
  (e.g. 10-20-30 days after; negative = before) [D-s] [S26]. See §4 for acknowledgment reminders.
- **Safety time** (SAP) was searched for but no official page was read [U].

### Common rules / constraints

- Lead time is master data per item **and per supplier**. Dates are calculated, not guessed.
- Near-term plans are protected (freeze/firm zones). Changes inside them need a human decision.
- The system **suggests** reschedules; a planner/buyer applies them, and for released POs the supplier must agree.

### Business value

- On-time material with less safety stock; less "nervous" plans; early warning of late supply.

---

## 4. Supplier communication and collaboration

### What systems do

**PO send and status**
- Dynamics 365: an approved PO sent to a portal vendor goes to **In external review**. The vendor can **accept,
  reject, or accept with changes**. A PO is set **Confirmed** only after the vendor agrees; confirmation stores a
  journal copy of the agreed version and runs budget checks [D] [S30].
- Oracle Fusion: when a PO needing acknowledgment is approved, the supplier is notified and status becomes
  **Pending Supplier Acknowledgment**; overdue acknowledgments show on buyer watchlists [D-s] [S34].
- Infor M3: the buyer reports the supplier's confirmation (confirmed date, supplier order number); status becomes
  "price and delivery date confirmed" [D-s] [S40].

**Order acknowledgment / confirmation control (SAP)**
- Simple mode: an "acknowledgment required" flag plus an acknowledgment number. If none arrives, the system can
  send an **acknowledgment reminder** [D] [S27].
- Detailed mode: a **confirmation control key** says which confirmations are expected and in what order: order
  acknowledgment (category 1), shipping notification / inbound delivery (category 2), rough GR (3) [D-s] [S29].
- Each confirmation type can be **MRP-relevant** (MRP then uses the confirmed date/qty) and **GR-relevant**; a GR
  assignment flag means **no goods receipt without a prior confirmation** [D] [S27].
- Incoming EDI acknowledgments are checked against the PO. Quantities use the over/under-delivery tolerances; price
  and date tolerances are set in customizing. On deviation: warning, and **the PO is not updated** [D] [S28].
- One EDI acknowledgment (IDoc) covers one PO only, at item level [D] [S28].

**Supplier counter-offers and buyer response**
- Dynamics 365 "accept with changes": per line, the vendor can change **dates, quantities, split lines, substitute
  items**. The vendor **cannot change price or charges**; only add notes [D] [S31]. The buyer edits the PO and sends a
  **new version**; the vendor accepts again. Full version history is kept [D] [S31] [S32].
- Oracle iSupplier: supplier changes to promised date, quantity or price are shown old vs new; the buyer **accepts or
  rejects each change** (with a reason) or all at once [D] [S33]. Changes within configured **tolerances** are
  **auto-approved**; default tolerance is 0. Changes can be routed to the requester for approval [D] [S33].
- PeopleSoft: changes inside POA (PO acknowledgment) tolerances are approved automatically [D-s] [S35].
- SAP Business Network: per line the supplier enters **confirm / backorder / reject** quantities; rejection needs a
  reason [D-s] [S36]. The buyer configures whether rejection is allowed (no / partial / full), a quantity tolerance
  (SAP recommends ≥ 10%), and up to **three automatic reminders** for unconfirmed orders [D-s] [S37]. Supplier
  changes to price, quantity or date must be **accepted by the buyer** before fulfilment [D-s] [S37].
- Oracle Supply Collaboration: suppliers **commit** quantities against order forecasts; the system flags past-due
  commits and commit shortfalls [D-s] [S38] [S39].

**Response deadlines and reminders**
- SAP: monitoring period per confirmation category; if nothing arrives in time, an expediter is sent [D] [S27].
- SAP: up to three urging levels relative to the due date [D-s] [S26].
- SAP Business Network: up to three reminders [D-s] [S37]. Oracle: overdue acknowledgment watchlist [D-s] [S34].

**EDI standards**
- **X12:** 850 PO → 855 PO acknowledgment → 856 ship notice/manifest (ASN) [S] [S43]. Buyer changes use **860**;
  the seller answers or proposes its own changes with **865** [S] [S42].
- **X12 line status codes (element 668)** include: IA accepted, IR rejected, IQ quantity changed, DR date
  rescheduled, IP price changed, IS substitution, IB backordered, BP partial ship + backorder, IC accepted with
  changes, ID deleted [S] [S41].
- **EDIFACT:** ORDERS (order), ORDCHG (change request), ORDRSP (response). ORDRSP can acknowledge receipt, confirm
  acceptance, **propose an amendment**, or reject all or part; one PO may get several responses [S] [S44].
- **GS1 EANCOM DESADV** (despatch advice) describes a shipment in advance so the receiver can prepare; should arrive
  before the goods; recommended one DESADV per PO [S] [S45] [S46].

### Common rules / constraints

- **Sent ≠ confirmed ≠ received.** Each is a separate status.
- A supplier response is a **proposal**. The buyer's system does not change the PO until the buyer (or a tolerance
  rule) accepts it.
- Changes are **line-level**, with explicit codes (accepted, qty changed, date changed, rejected, backordered).
- Price changes are often restricted more tightly than date/qty changes (D365 forbids them in the portal).
- Every change creates a **new version**; history is kept.
- Missing answers trigger **timed reminders**, not silent waiting.

### Business value

- Fewer surprises: confirmed dates feed MRP; ASNs let receiving plan; fast, structured negotiation of changes;
  an audit trail of what was agreed.

---

## 5. Approval, authority and audit

### What systems do

- **SAP release strategy:** criteria such as document type and total value pick a strategy; release codes
  (approvers) must release in a defined sequence. An unreleased PO **cannot be sent** to the supplier. A change can
  restart approval, e.g. if value rises by more than a set % [D] [S47].
- **Dynamics 365 change management:** PO statuses Draft → In review → Approved/Rejected → Confirmed → Finalized.
  Changes after approval use **Request change**, which returns the PO to Draft; a policy sets which changes need
  re-approval [D] [S30]. Workflow supports auto-approval rules and escalation of stuck approvals [D] [S30].
  POs created by **firming planned orders** are always Approved [D] [S30].
- **Cancellation (D365):** a confirmed PO can't be deleted; only unreceived/uninvoiced quantity can be cancelled;
  under change management the cancel goes through approval [D] [S30].
- **Signing limits (D365/AX):** spending limit vs approval limit, per document type, often by job level;
  time-limited agreements (archived AX 2012 docs) [D-s] [S48].
- **Segregation of duties (D365):** rules forbid one user holding two conflicting duties, e.g. the same person
  receiving goods **and** paying the vendor; rules have severity and mitigation; compliance must be validated after
  rule changes [D] [S49].
- **Oracle iSupplier:** supplier changes can be routed into the requester's approval hierarchy [D] [S33].

### Common rules / constraints

- Authority is by **amount and document type**. Above the limit, a higher approver is needed.
- No external commitment before internal approval.
- Material changes after approval re-trigger approval.
- Confirmed versions are stored (journals) for audit [D] [S30].

### Business value

- Spend control, fraud prevention, and proof of who approved what.

---

## 6. Supplier evaluation and performance

### What systems do

- **SAP supplier evaluation:** main criteria price, quality, delivery, service, invoice verification,
  sustainability; up to 20 subcriteria each; scores usually 1–100; **weighting keys** set the weight of each
  criterion [D] [S50].
- **Automatic delivery subcriteria:** on-time delivery, quantity reliability, compliance with shipping
  instructions, shipping-notification reliability. Price: price level and history. Quality: GR inspections,
  notifications, audits [D] [S50] [D-s] [S51].
- **Use in selection:** overall score for quick comparison; criterion scores for the deciding factor (a supplier
  weaker overall may win on price) [D] [S50]. SAP's overview page plots spend vs supplier performance [D-s] [S52].
- Scores are not automatically fed into SAP's source determination order from §1. The link from score to supplier
  choice is a **buyer decision** or a master-data update (e.g. quota, block) [U: no doc says it is automatic].
- **Oracle analytics:** prebuilt on-time delivery, rejected shipments, return rates (marketing page) [W] [S53].
  Native Oracle scorecard setup was **not found** [U].

### Common rules / constraints

- Scores come from transaction facts (receipt dates vs promised, received qty vs ordered, inspection results).
- Weighting is explicit and configurable; comparisons are made within the same weighting.

### Business value

- Objective supplier ranking; evidence for negotiations, re-sourcing and blocking.

---

## 7. Exceptions and disruptions

### What systems do

- **Late or short supply:** confirmations with new dates/quantities feed MRP (if MRP-relevant) [D] [S27]; MRP then
  creates reschedule/increase/new-order suggestions [D] [S16] [D] [S23]. **Negative days** decide whether to wait
  for a late PO or order anew [D] [S23].
- **Backorders:** SAP Business Network confirm/backorder/reject split [D-s] [S36]; X12 codes IB, BP, DR [S] [S41].
- **Alternative sourcing:** ranked sources and allocation % (Oracle) [D-s] [S7] [S9]; quota arrangements and
  source lists (SAP) [D] [S1] [S3]. When a supplier is blocked, it drops out of source determination [D-s] [S2].
- **Dual sourcing:** two suppliers for the same item, reducing outage risk at the cost of more overhead; differs
  from **sole** sourcing (only one supplier exists) [W] [S55]. No ASCM primary definition was confirmed [U].
- **Cancellations:** D365 cancels only the unreceived remainder [D] [S30]. X12 860 can reduce/cancel; the seller
  replies with 865 or 855 [S] [S42]. Cancellation liability in scheduling-agreement zones: see §2 [C] [S57].
- **Expediting:** reminder/urging levels [D-s] [S26]; Oracle past-due commit alerts [D-s] [S38].

### Common rules / constraints

- An exception produces a **message or suggestion**, and a person or rule decides.
- Already received/invoiced quantities can't be cancelled.
- Re-sourcing uses the same master data (ranks, quotas, blocks) as normal sourcing.

### Business value

- Faster recovery from supplier problems; less line stoppage; documented decisions.

---

## 8. Business value and KPIs of purchasing

### What systems measure

- **SAP procurement analytics:** off-contract spend (POs without contract reference), non-managed spend (payments
  without a PO), supplier evaluation by price/quantity/time/quality [D-s] [S52].
- **Supplier delivery KPIs:** on-time delivery, quantity reliability [D] [S50]; on-time delivery, rejected
  shipments, return rates [W] [S53].
- **SCOR (ASCM) performance attributes:** reliability, responsiveness, agility, cost, asset management;
  **perfect order fulfillment** as the flagship reliability metric [W] (secondary summaries only; ASCM text not
  confirmed) [U].
- **OTIF** (on time in full) is widely used [B]; no official ERP/ASCM definition was read for this report [U].
- **Inventory effect:** lead time, lot size and safety buffers drive inventory; stacking buffers (safety stock +
  safety time + padded lead time + large lots) inflates stock [C] (SAP practitioner article, not verified) [U].

### Business value (summary)

- **Cost:** contract compliance, price conditions, fewer orders.
- **Service:** on-time, in-full material for production.
- **Lead time:** shorter, reliable supplier lead times.
- **Inventory:** right quantities at the right time.
- **Risk:** blocked/approved suppliers, second sources, early warnings, audit trail.

---

## Key takeaways for a purchasing agent (facts only)

1. Supplier choice follows a **fixed, data-driven priority**: quota/allocation → source list/approved list →
   contracts → info records/price lists. Blocked or unapproved suppliers are excluded.
2. Split sourcing uses **explicit percentages plus history** (lowest quota rating wins next), not random choice.
3. Prices and contracts have **validity periods and target quantities/values**; going outside them is a warning or
   a hard block.
4. Order quantity = net need, then **lot-size rule**, then **min/max/multiple** (often supplier-specific), rounded up.
5. Receipts are checked against **over/under-delivery tolerances**; short receipts are partial deliveries unless
   marked complete.
6. Lead time is split into **buyer processing + supplier delivery + receiving** times; dates are back-scheduled.
7. Near-term plans are **frozen/firmed**; changes are **suggested** (advance, postpone, increase, decrease), never
   applied automatically to released POs.
8. **Sent, acknowledged, confirmed, shipped (ASN) and received are separate states.** Only confirmations marked
   MRP-relevant change planning dates.
9. A supplier response is a **proposal**: accept, reject, or accept-with-changes per line (qty, date, split,
   substitute; price often restricted). The PO changes only after the buyer or a **tolerance rule** accepts it.
10. Every agreed change creates a **new PO version**; history is kept for audit.
11. Missing confirmations trigger **timed reminders** (typically up to three levels).
12. Standard messages exist for every step: ORDERS/850, ORDRSP/855, ORDCHG/860, 865, DESADV/856, with line
    status codes such as accepted, qty changed, date rescheduled, rejected, backordered.
13. Approval depends on **amount and document type**; an unapproved PO cannot be sent; big changes re-trigger
    approval; segregation of duties separates ordering, receiving and paying.
14. Supplier scores (on-time, quantity reliability, quality, price) are **computed from transaction facts** with
    explicit weights; they inform, but do not automatically override, source determination.
15. Exceptions (late, short, rejected, cancelled) become **messages/suggestions**; recovery uses the same
    ranked/alternative source data. Only unreceived quantity can be cancelled.

---

## Sources

| # | Label | Source |
| --- | --- | --- |
| S1 | D | SAP Learning, Identifying Additional Aspects of Source Determination: https://learning.sap.com/courses/purchasing-in-sap-s-4hana/identifying-additional-aspects-of-source-determination |
| S2 | D-s | SAP Learning, Blocking Sources of Supply: https://learning.sap.com/courses/purchasing-in-sap-s-4hana/blocking-sources-of-supply |
| S3 | D | SAP Learning, Controlling Source Determination with Quota Arrangements: https://learning.sap.com/courses/purchasing-in-sap-s-4hana/controlling-source-determination-with-quota-arrangements-1 |
| S4 | D-s | SAP Help 4.6C, Splitting Quota Arrangement: https://help.sap.com/SAPHelp_46c/helpdata/EN/f4/7d268644af11d182b40000e829fbfe/content.htm |
| S5 | D-s | SAP Learning, Working with Purchasing Info Records: https://learning.sap.com/courses/purchasing-in-sap-s-4hana/working-with-purchasing-info-records-1 |
| S6 | D | SAP Learning, Working with Contracts: https://learning.sap.com/courses/purchasing-in-sap-s-4hana/working-with-contracts |
| S7 | D-s | Oracle Cloud SCM, Assignment Sets, Sourcing Rules, and Bills of Distribution: https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25d/faupc/assignment-sets-sourcing-rules-and-bills-of-distribution.html |
| S8 | D-s | Oracle EBS, Defining Sourcing Rules: https://docs.oracle.com/cd/A60725_05/html/comnls/us/mrp/defsrule.htm |
| S9 | D-s | Oracle Cloud, Sourcing Rules in Backlog Management: https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/24b/faubm/sourcing-rules-and-bills-of-distribution-in-backlog-management.html |
| S10 | D | Oracle EBS, Defining Approved Supplier Statuses: https://docs.oracle.com/cd/A60725_05/html/comnls/us/po/asl01.htm |
| S11 | D | Odoo 17, Vendor pricelists: https://www.odoo.com/documentation/17.0/applications/inventory_and_mrp/purchase/products/pricelist.html |
| S12 | D-s | Microsoft Learn, D365 SCM 2023 wave 1 procurement feature updates (vendor PO hold): https://learn.microsoft.com/cs-cz/dynamics365/release-plan/2023wave1/finance-operations/dynamics365-supply-chain-management/procurement-sourcing-feature-state-updates-10032 |
| S13 | D | SAP Learning, Understanding the Lot Size Calculation: https://learning.sap.com/courses/consumption-based-planning-and-forecasting-in-sap-cloud-erp/understanding-the-lot-size-calculation |
| S14 | D-s | Oracle EBS MRP, Order Modifiers: https://docs.oracle.com/cd/A60725_05/html/comnls/us/mrp/ordmod.htm |
| S15 | D-s | Oracle Cloud, How Order Modifiers Are Applied: https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25a/faurp/how-order-modifiers-are-applied-when-replenishments-are.html |
| S16 | D | Microsoft Learn, Action messages: https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/action-messages |
| S17 | D-s | SAP Learning, Applying Tolerances and the Delivery Completed Indicator: https://learning.sap.com/courses/inventory-management-and-physical-inventory-in-sap-s-4hana/applying-tolerances-and-the-delivery-completed-indicator |
| S18 | D-s | SAP Help 4.6C, Underdeliveries, Overdeliveries, and Final Deliveries: https://help.sap.com/saphelp_46c/helpdata/en/a5/63343943a211d189410000e829fbbd/content.htm |
| S19 | D-s | Microsoft (archived AX glossary), PO overdelivery percentage: https://technet.microsoft.com/EN-US/library/dynamicsaxglossary.640220.aspx |
| S20 | D-s | SAP Learning, Creating Scheduling Agreements with Release Documentation: https://learning.sap.com/courses/purchasing-in-sap-s-4hana/creating-scheduling-agreements-with-release-documentation |
| S21 | D-s | SAP Learning, Exploring Scheduling: https://learning.sap.com/courses/consumption-based-planning-and-forecasting-in-sap-cloud-erp/exploring-scheduling ; backward scheduling note from TechTarget [W]: https://www.techtarget.com/searchsap/definition/SAP-Planned-Delivery-Time |
| S22 | D | Odoo 17, Lead times: https://www.odoo.com/documentation/17.0/applications/inventory_and_mrp/inventory/warehouses_storage/replenishment/lead_times.html |
| S23 | D | Microsoft Learn, Master plans overview: https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/master-plans |
| S24 | D-s | SAP Help 4.6C, Rescheduling Check: https://help.sap.com/SAPHelp_46c/helpdata/EN/f4/7d2c9744af11d182b40000e829fbfe/content.htm |
| S25 | C | SAP Community, Differences between exception 20 and 10: https://answers.sap.com/questions/11048371/differences-between-exception-20-and-10-in-md04.html |
| S26 | D-s | SAP Help 4.6C, Reminders and Urging Letters: https://help.sap.com/saphelp_46C/helpdata/EN/6a/c1041badb111d1b6120000e8a738dc/content.htm |
| S27 | D | SAP Learning, Monitoring Purchase Orders: https://learning.sap.com/courses/purchasing-in-sap-s-4hana/monitoring-purchase-orders |
| S28 | D | SAP Help 4.6C, Receiving Acknowledgments via EDI: https://help.sap.com/saphelp_46c/helpdata/en/aa/38b05e61c711d2b459006094b9476a/content.htm |
| S29 | D-s | SAP Help 4.6C, Setting up confirmation control: https://help.sap.com/saphelp_46c/helpdata/En/c2/1c4b6e5733d1118b3f0060b03ca329/content.htm |
| S30 | D | Microsoft Learn, Approve and confirm purchase orders: https://learn.microsoft.com/en-us/dynamics365/supply-chain/procurement/purchase-order-approval-confirmation |
| S31 | D | Microsoft Learn, Vendor collaboration with customers: https://learn.microsoft.com/en-us/dynamics365/supply-chain/procurement/vendor-collaboration-work-customers-dynamics-365-operations |
| S32 | D-s | Microsoft Learn training, PO statuses and versions: https://learn.microsoft.com/en-us/training/modules/configure-manage-vendor-collaboration-dyn365-supply-chain-mgmt/8-po-versions |
| S33 | D | Oracle EBS 12.2 iSupplier/Purchasing, Respond to supplier changes: https://docs.oracle.com/cd/E26401_01/doc.122/e48972/T463224T463234.htm |
| S34 | D-s | Oracle Fusion Procurement 24D, Purchasing documents requiring supplier acknowledgment: https://docs.oracle.com/en/cloud/saas/procurement/24d/oaprc/how-you-manage-purchasing-documents-requiring-supplier.html |
| S35 | D-s | Oracle PeopleSoft Purchasing 9.2, Using PO Acknowledgements: https://docs.oracle.com/en/applications/peoplesoft/financials-and-supply-chain-management/9.2.056/peoplesoft-purchasing/using-purchase-order-acknowledgements.html |
| S36 | D-s | SAP Business Network (Ariba) support, How do I create an order confirmation?: https://support.ariba.com/Item/view/174466 |
| S37 | D-s | SAP Learning, Understanding PO Confirmation Rules (Business Network): https://learning.sap.com/learning-journeys/discovering-sap-business-network-supplier-portal-implementation-and-adoption/understanding-purchase-order-confirmation-rules_ab2cf161-eb37-41a6-a46b-8c3a4ced9da3 ; buyer-acceptance rule from a customer supplier guide [W]: https://www.umicore.com/storage/group/supplier-guidelines-send-a-order-confirmation-042023.pdf |
| S38 | D-s | Oracle Cloud, Overview of Supply Collaboration: https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/25c/faucc/overview-of-supply-collaboration.html |
| S39 | D-s | Oracle Cloud, Configure Automatic Commits to Order Forecasts: https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26a/faucc/configure-automatic-commits-to-order-forecasts.html |
| S40 | D-s | Infor M3, Report Confirmation of PO: https://docs.infor.com/m3udi/16.x/en-us/m3beud/prochs/pps670.html |
| S41 | S | X12 004010 element 668 Line Item Status Code (Stedi reference): https://www.stedi.com/edi/x12-004010/element/668 |
| S42 | S | X12 865 PO Change Acknowledgment/Request – Seller Initiated (Stedi reference): https://www.stedi.com/x12-004040/865 |
| S43 | S | X12 856 Ship Notice/Manifest (Stedi reference): https://www.stedi.com/edi/x12-004010/856 |
| S44 | S | UN/EDIFACT ORDRSP D.97A (reproduced UNSM text): https://www.stylusstudio.com/edifact/D97A/ORDRSP.htm |
| S45 | S | GS1 EANCOM 2002 DESADV introduction: https://gs1.org/sites/gs1/files/docs/eancom/ean02s3/part2/desadv/intro.htm |
| S46 | S | GS1 EANCOM 2002 ORDRSP introduction: https://gs1.org/sites/default/files/docs/eancom/ean02s4/part2/ordrsp/intro.htm |
| S47 | D | SAP Help 4.6C, Release procedure for purchase orders: https://help.sap.com/saphelp_46C/helpdata/EN/ac/2d547bb435d1118b3f0060b03ca329/content.htm |
| S48 | D-s | Microsoft Learn (archived AX 2012), About signing limits: https://learn.microsoft.com/en-us/dynamicsax-2012/appuser-itpro/about-signing-limits |
| S49 | D | Microsoft Learn, Set up segregation of duties: https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/fin-ops/sysadmin/set-up-segregation-duties |
| S50 | D | SAP Learning, Evaluating Suppliers Using Logistics Information System: https://learning.sap.com/courses/purchasing-in-sap-s-4hana/evaluating-suppliers-using-logistics-information-system |
| S51 | D-s | SAP Help 4.6C, Vendor evaluation criteria: https://help.sap.com/saphelp_46c/helpdata/en/8d/b97d1f414511d188fc0000e8322f96/content.htm |
| S52 | D-s | SAP Learning, Procurement Overview Page and Procurement Analytics: https://learning.sap.com/courses/detailing-intelligent-procurement-and-procurement-analytics/introducing-procurement-overview-page-and-real-time-reporting-and-monitoring-for-procurement_b1220cd8-8141-476c-bd30-0de739fdb2f6 |
| S53 | W | Oracle Fusion SCM Analytics product tour (marketing): https://www.oracle.com/fusion-data-intelligence/scm-analytics/product-tour/ |
| S55 | W | TechTarget, Dual sourcing: https://www.techtarget.com/searcherp/definition/dual-sourcing |
| S56 | D-s | Oracle EBS Inventory, Order Modifiers: https://docs.oracle.com/cd/A60725_05/html/comnls/us/inv/ordrmod.htm |
| S57 | C | SAP Community archive, firm/trade-off zone discussion: https://archive.sap.com/discussions/thread/538250 |
