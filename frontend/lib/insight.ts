// Read-only views over the observer data (the live snapshot and the timeline) for the demo cockpit: what each agent is
// doing, which disruptions happened and what followed them, and how each order's plan changed since it was committed.
// Nothing here decides anything or invents a fact: every value is read from a published event, a negotiation message
// or the live snapshot. When the data cannot say something, the view says "unknown" instead of guessing.

import type { Live, TimelineItem } from "./api";

export const AGENT_CODES = ["SALES", "PLANNING", "INVENTORY", "PURCHASING", "WAREHOUSE", "HR"] as const;
export type AgentCode = (typeof AGENT_CODES)[number];

export const ROLE: Record<AgentCode, string> = {
  SALES: "Talks to customers, records orders and confirmations",
  PLANNING: "Builds the production plan: MPS, MRP, capacity, schedule",
  INVENTORY: "Owns stock: availability, reservations, safety stock",
  PURCHASING: "Buys materials from suppliers, handles supplier delays",
  WAREHOUSE: "Receiving docks, storage space, issue and shipping",
  HR: "Workers, skills, shifts, absences, worker-hours",
};

// Each agent's own work queues (database schema of the queue table). Event deliveries are shared, so they are not here.
const QUEUE_OWNER: Record<string, AgentCode> = {
  sales_agent: "SALES", planning: "PLANNING", inventory: "INVENTORY", purchasing_agent: "PURCHASING",
  warehouse: "WAREHOUSE", hr: "HR",
};

// -- agent status -----------------------------------------------------------------------------------------------------

/** Idle: nothing open. Working: its own queue has work. Waiting: it asked another agent and has no answer yet.
 *  Negotiating: another agent asked it and it has to answer. Alert: it published a risk fact that is still open. */
export type AgentStatus = "IDLE" | "WORKING" | "WAITING" | "NEGOTIATING" | "ALERT";

export const STATUS_HELP: Record<AgentStatus, string> = {
  IDLE: "Nothing open right now",
  WORKING: "Has unfinished work in its own queue",
  WAITING: "Asked another agent and is waiting for the answer",
  NEGOTIATING: "Another agent asked it something; it has to answer",
  ALERT: "Reported a risk that is not resolved yet",
};

export type AgentView = {
  code: AgentCode; status: AgentStatus; waitingFor: string[]; answering: string[]; queued: number;
  latest: TimelineItem | null; alert: string | null;
};

export function involves(item: TimelineItem, code: string): boolean {
  if (item.source === "event") return item.publisher === code;
  if (item.source === "negotiation") return item.from === code || item.to === code;
  if (item.source === "ai_call") return item.agent === code;
  return false;
}

export function agentViews(live: Live | null, items: TimelineItem[]): AgentView[] {
  const open = live?.negotiations_open ?? [];
  const queued: Partial<Record<AgentCode, number>> = {};
  for (const [queue, n] of Object.entries(live?.clock.waiting ?? {})) {
    const owner = QUEUE_OWNER[queue.split(".")[0]];
    if (owner) queued[owner] = (queued[owner] ?? 0) + n;
  }
  const risks = openRisks(items);
  return AGENT_CODES.map((code) => {
    const waitingFor = open.filter((s) => s.starter === code).map((s) => s.owner);
    const answering = open.filter((s) => s.owner === code).map((s) => s.starter);
    let latest: TimelineItem | null = null;
    for (let i = items.length - 1; i >= 0; i--) {
      const it = items[i];
      if (involves(it, code) && !(it.source === "event" && it.type === "SimulatedDayStarted") && it.source !== "ai_call") {
        latest = it; break;
      }
    }
    const alert = risks.get(code) ?? null;
    const status: AgentStatus = answering.length ? "NEGOTIATING" : waitingFor.length ? "WAITING"
      : queued[code] ? "WORKING" : alert ? "ALERT" : "IDLE";
    return { code, status, waitingFor, answering, queued: queued[code] ?? 0, latest, alert };
  });
}

/** Risks an agent published that nothing later answered: an order still at risk (Planning), a supplier delay
 *  (Purchasing) that Planning has not reacted to, or safety stock used (Inventory) since the last day started. */
function openRisks(items: TimelineItem[]): Map<string, string> {
  const risks = new Map<string, string>();
  const atRisk = new Map<string, string>();  // demand id -> latest plan event type
  for (const it of items) {
    if (it.source !== "event") continue;
    const demand = String(it.payload?.demand_id ?? "");
    if (demand && it.type?.startsWith("Plan")) atRisk.set(demand, it.type);
  }
  const stillAtRisk = [...atRisk.values()].filter((t) => t === "PlanAtRisk").length;
  if (stillAtRisk) risks.set("PLANNING", `${stillAtRisk} order${stillAtRisk > 1 ? "s" : ""} at risk`);
  return risks;
}

// -- disruptions ------------------------------------------------------------------------------------------------------

// The published facts that start a disruption, and the agent that owns that fact.
export const DISRUPTION_EVENTS: Record<string, AgentCode> = {
  WorkforceCapacityChanged: "HR", SupplierDeliveryDelayed: "PURCHASING", StorageCapacityChanged: "WAREHOUSE",
  OrderCancelled: "SALES", OrderChangeRequested: "SALES",
};

export type Incident = {
  event: TimelineItem; origin: AgentCode; index: number;
  after: TimelineItem[];              // everything until the next disruption (or now)
  agents: AgentCode[];                // agents that published or negotiated in that window
  planOutcomes: TimelineItem[];       // Planning's answers in that window: revised, at risk, commit failed
  linked: Set<TimelineItem>;          // outcomes whose ids match the disruption's own ids (a proven link)
  sessions: string[];                 // negotiation sessions started in that window
  unresolved: string[];               // of those, still open in the live snapshot
};

export function incidents(items: TimelineItem[], live: Live | null): Incident[] {
  const starts = items.map((it, i) => ({ it, i }))
    .filter(({ it }) => it.source === "event" && it.type && it.type in DISRUPTION_EVENTS);
  const open = new Set((live?.negotiations_open ?? []).map((s) => s.session_id));
  return starts.map(({ it, i }, n) => {
    const end = starts[n + 1]?.i ?? items.length;
    const after = items.slice(i + 1, end).filter((x) => x.source !== "ai_call"
      && !(x.source === "event" && x.type === "SimulatedDayStarted"));
    const agents = new Set<AgentCode>([DISRUPTION_EVENTS[it.type!]]);
    for (const x of after) for (const c of AGENT_CODES) if (involves(x, c)) agents.add(c);
    const planOutcomes = after.filter((x) => x.source === "event"
      && ["PlanRevised", "PlanAtRisk", "PlanCommitFailed"].includes(x.type ?? ""));
    const ids = disruptionIds(it);
    const linked = new Set(planOutcomes.filter((p) => [p.payload?.production_order_id, p.payload?.order_number,
      p.payload?.demand_id].some((v) => v && ids.has(String(v)))));
    const sessions = [...new Set(after.filter((x) => x.source === "negotiation" && x.session_id).map((x) => x.session_id!))];
    return { event: it, origin: DISRUPTION_EVENTS[it.type!], index: n + 1, after, agents: [...agents], planOutcomes,
      linked, sessions, unresolved: sessions.filter((s) => open.has(s)) };
  });
}

/** Ids the disruption itself names: production orders at risk, the order a delivery was for, the order number. */
function disruptionIds(it: TimelineItem): Set<string> {
  const p = it.payload ?? {};
  const ids = new Set<string>();
  for (const r of (p.at_risk as { production_order_id?: string }[] | undefined) ?? []) {
    if (r.production_order_id) ids.add(r.production_order_id);
  }
  for (const k of ["for_ref", "order_number", "demand_id"]) if (p[k]) ids.add(String(p[k]));
  return ids;
}

/** The disruption in one plain sentence, from its own payload. */
export function describeDisruption(it: TimelineItem, names: Record<string, string> = {}): string {
  const p = it.payload ?? {};
  switch (it.type) {
    case "WorkforceCapacityChanged": {
      const risk = (p.at_risk as unknown[] | undefined)?.length ?? 0;
      return `Worker ${p.worker} is absent. HR covered what it could${risk ? `; ${risk} production day${risk > 1 ? "s" : ""} still short of worker-hours` : " — nothing left uncovered"}.`;
    }
    case "SupplierDeliveryDelayed":
      return `Supplier delivery of ${names[String(p.item_id)] ?? "an item"} (${p.quantity}) moved from ${p.old_date} to ${p.new_date}.`;
    case "StorageCapacityChanged":
      return `Capacity of ${String(p.resource ?? "").toLowerCase().replaceAll("_", " ")} changed to ${p.units}.`;
    case "OrderCancelled": return `Customer cancelled order ${p.order_number}.`;
    case "OrderChangeRequested": return `Customer asked to change order ${p.order_number} to ${p.quantity}.`;
    default: return it.type ?? "";
  }
}

// -- plan comparison --------------------------------------------------------------------------------------------------

export type PlanChange = { item: TimelineItem; text: string; tone: "red" | "amber" | "green" | "blue" };

export type BaselineOrder = { id: string; start_day: string; end_day: string; quantity: string };

export type OrderComparison = {
  demandId: string; label: string; sku: string | null;
  baseline: { quantity: string; deliveryDay: string; productionOrders: BaselineOrder[] } | null;
  current: Live["orders"][number] | null;
  changes: PlanChange[];
  verdict: "UNCHANGED" | "RESCHEDULED" | "AT_RISK" | "QUANTITY_CHANGED" | "CANCELLED" | "COMPLETED" | "NOT_COMMITTED" | "FAILED";
};

export const VERDICT: Record<OrderComparison["verdict"], { label: string; tone: string; help: string }> = {
  UNCHANGED: { label: "Unchanged", tone: "green", help: "The committed plan has not changed" },
  RESCHEDULED: { label: "Rescheduled inside", tone: "blue", help: "Work moved between days; the delivery date is kept" },
  AT_RISK: { label: "At risk", tone: "red", help: "Planning reported the delivery date may not hold" },
  QUANTITY_CHANGED: { label: "Quantity changed", tone: "amber", help: "The committed quantity changed" },
  CANCELLED: { label: "Cancelled", tone: "red", help: "The customer cancelled" },
  COMPLETED: { label: "Completed", tone: "green", help: "Produced and shipped" },
  NOT_COMMITTED: { label: "Not committed yet", tone: "amber", help: "Still being planned or waiting for the customer" },
  FAILED: { label: "Could not commit", tone: "red", help: "The plan could not be committed" },
};

export function planComparisons(items: TimelineItem[], live: Live | null): OrderComparison[] {
  const byDemand = new Map<string, TimelineItem[]>();
  for (const it of items) {
    if (it.source !== "event" || !it.type?.startsWith("Plan")) continue;
    const id = String(it.payload?.demand_id ?? "");
    if (!id) continue;
    byDemand.set(id, [...(byDemand.get(id) ?? []), it]);
  }
  const orders = live?.orders ?? [];
  const ids = new Set([...orders.map((o) => o.demand_id), ...byDemand.keys()]);
  return [...ids].map((demandId) => {
    const events = byDemand.get(demandId) ?? [];
    const current = orders.find((o) => o.demand_id === demandId) ?? null;
    const committed = events.find((e) => e.type === "PlanCommitted");
    const p = committed?.payload ?? {};
    const baseline = committed ? {
      quantity: String(p.quantity), deliveryDay: String(p.delivery_day),
      productionOrders: (p.production_orders as BaselineOrder[] | undefined) ?? [],
    } : null;
    const changes = events.filter((e) => e !== committed && e.type !== "PlanCommitted").map(explainChange);
    const label = current?.order_number || String(committed?.payload?.order_number ?? "") || `#${demandId.slice(0, 6)}`;
    return { demandId, label, sku: current?.sku ?? null, baseline, current, changes,
      verdict: verdict(baseline, current, events) };
  }).sort((a, b) => a.label.localeCompare(b.label));
}

function verdict(baseline: OrderComparison["baseline"], current: OrderComparison["current"], events: TimelineItem[]): OrderComparison["verdict"] {
  const status = current?.status ?? "";
  if (status === "CANCELLED") return "CANCELLED";
  if (["COMPLETED", "SHIPPED"].includes(status)) return "COMPLETED";
  if (events.some((e) => e.type === "PlanCommitFailed") && !baseline) return "FAILED";
  if (!baseline) return "NOT_COMMITTED";
  const last = [...events].reverse().find((e) => e.type === "PlanAtRisk" || e.type === "PlanRevised");
  if (last?.type === "PlanAtRisk") return "AT_RISK";
  if (current && Number(current.quantity) !== Number(baseline.quantity)) return "QUANTITY_CHANGED";
  if (events.some((e) => e.payload?.reason?.toString().startsWith("QUANTITY"))) return "QUANTITY_CHANGED";
  if (events.some((e) => e.payload?.reason === "WORKFORCE_REPAIR")) return "RESCHEDULED";
  return "UNCHANGED";
}

/** One plan event in words, built only from its payload. */
export function explainChange(e: TimelineItem): PlanChange {
  const p = e.payload ?? {};
  const reason = String(p.reason ?? "");
  const words = reason.toLowerCase().replaceAll("_", " ");
  if (e.type === "PlanAtRisk") {
    if (reason === "SUPPLIER_DELAY") {
      return { item: e, tone: "red", text: `At risk: material arrives ${p.arrival_day}, needed by ${p.needed_by} (${p.days_late} day${Number(p.days_late) > 1 ? "s" : ""} late). Delivery ${p.delivery_day} → estimated ${p.estimated_delivery_day}. Planning does not move a committed date without the customer.` };
    }
    return { item: e, tone: "red", text: `At risk: ${p.missing_hours ?? "?"} ${String(p.skill ?? "").toLowerCase()} worker-hours missing on ${p.day} (${words}). Delivery ${p.delivery_day ?? "?"} may not hold.` };
  }
  if (e.type === "PlanCommitFailed") return { item: e, tone: "red", text: `Plan could not be committed: ${words}.` };
  switch (reason) {
    case "WORKFORCE_REPAIR":
      return { item: e, tone: "blue", text: `Work moved from ${p.from_day} to ${p.to_day} after HR agreed the hours on the new day. Delivery date kept.` };
    case "QUANTITY_INCREASED": case "QUANTITY_DECREASED": case "QUANTITY_DECREASED_DAMPENED":
      return { item: e, tone: "amber", text: `Quantity is now ${p.quantity} (${words}).` };
    case "CHANGE_REJECTED": return { item: e, tone: "amber", text: `Customer change refused: ${String(p.detail ?? "not feasible").toLowerCase().replaceAll("_", " ")}. Quantity stays ${p.quantity}.` };
    case "CANCELLED": return { item: e, tone: "red", text: `Cancelled: ${(p.cancelled_production_orders as unknown[] | undefined)?.length ?? 0} production orders cancelled, ${(p.continuing_production_orders as unknown[] | undefined)?.length ?? 0} already running finish into stock.` };
    case "ORDER_COMPLETED": return { item: e, tone: "green", text: "Order completed; leftovers released." };
    case "COMMIT_FAILED": return { item: e, tone: "red", text: "Commit failed; what was held is released." };
    default: return { item: e, tone: "amber", text: words || (e.type ?? "") };
  }
}
