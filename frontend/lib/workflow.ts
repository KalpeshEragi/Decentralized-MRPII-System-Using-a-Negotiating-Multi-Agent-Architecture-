// Presentation helpers: human-readable names for backend records and the workflow stage derived from backend state.
// Nothing here decides business outcomes; it only labels what the backend reports.

import type { Decision } from "./api";
import type { Snapshot } from "./useSimulation";

export const AGENT_NAMES: Record<string, string> = {
  PRODUCTION_PLANNING_AGENT: "Planning Agent",
  INVENTORY_AGENT: "Inventory Agent",
  PURCHASING_AGENT: "Purchasing Agent",
};

export const PARTY_NAMES: Record<string, string> = {
  INVENTORY: "Inventory Agent",
  PURCHASING: "Purchasing Agent",
  SUPPLIER_INTERFACE: "Supplier Interface",
  APPROVAL_WORKFLOW: "Approval (human)",
};

/** What each recorded decision means, phrased as progress. */
export const DECISION_TEXT: Record<string, string> = {
  ORDER_RECEIVED: "Order received by the Planning Agent",
  PLAN_CREATED: "Plan computed: finished goods → MPS → capacity → BOM → MRP",
  SHORTAGE_DETECTED: "Component shortage detected",
  AVAILABILITY_ASSESSED: "Inventory Agent assessed stock availability",
  NEGOTIATION_REQUEST: "Inventory Agent → Purchasing Agent: procurement REQUEST (A2A)",
  REQUISITION_CREATED: "Purchasing Agent created a purchase requisition",
  LLM_PROPOSAL_REJECTED: "LLM proposal refused by deterministic validation; agent policy used",
  NEGOTIATION_DECISION: "Purchasing Agent decided its next negotiation step",
  NEGOTIATION_MESSAGE: "Purchasing Agent sent terms to the Supplier Interface",
  AGREEMENT_PROPOSED: "Purchasing Agent proposed an agreement",
  NEGOTIATION_REJECTED: "Negotiation rejected",
  NEGOTIATION_FAILED: "Negotiation failed: round limit reached",
  NEGOTIATION_RESULT_RECEIVED: "Negotiation result passed on",
  PLAN_ATTEMPT_STARTED: "Planning attempt recorded",
  PLAN_APPROVED: "Human approved the plan",
  AGREEMENT_COMMITTED: "Agreement COMMITTED",
  STOCK_RESERVED: "Inventory Agent reserved stock for the approved plan",
  PLAN_REJECTED: "Human rejected the plan: replanning",
  AGREEMENT_ABORTED: "Uncommitted agreement aborted",
  HUMAN_INTERVENTION_REQUIRED: "Attempt limit reached: human intervention required",
};

export const describe = (d: Decision) => DECISION_TEXT[d.decision_type] ?? d.decision_type;

export type StageState = "done" | "active" | "pending" | "failed";
export type Stage = { key: string; label: string; state: StageState };

export function stages(s: Snapshot, running: boolean): Stage[] {
  const types = new Set(s.decisions.map((d) => d.decision_type));
  const attempt = s.attempts.at(-1);
  const status = attempt?.approval_status;
  const negotiations = attempt ? attempt.negotiations : [];
  const approved = status === "APPROVED";
  const intervention = status === "HUMAN_INTERVENTION_REQUIRED";
  const replanned = s.attempts.some((a) => a.approval_status === "REJECTED");

  const done: Record<string, boolean> = {
    ORDER: s.orders.length > 0,
    PLANNING: !!s.plan || types.has("PLAN_CREATED"),
    MRP: !!s.plan || types.has("PLAN_CREATED"),
    INVENTORY: types.has("AVAILABILITY_ASSESSED"),
    PURCHASING: types.has("REQUISITION_CREATED") || (!!attempt && negotiations.length === 0),
    NEGOTIATION: !!attempt && status !== "PENDING_NEGOTIATION",
    APPROVAL: approved || intervention || (replanned && status !== "AWAITING_APPROVAL" && status !== "PENDING_NEGOTIATION"),
    COMMIT: approved,
    RESULT: approved || intervention,
  };
  const order = ["ORDER", "PLANNING", "MRP", "INVENTORY", "PURCHASING", "NEGOTIATION", "APPROVAL", "COMMIT", "RESULT"];
  const labels: Record<string, string> = {
    ORDER: "Order", PLANNING: "Planning", MRP: "MPS / MRP", INVENTORY: "Inventory", PURCHASING: "Purchasing",
    NEGOTIATION: "Negotiation", APPROVAL: "Approval", COMMIT: replanned && !approved ? "Replan" : "Commit", RESULT: "Result",
  };
  const firstOpen = order.find((k) => !done[k]);
  return order.map((key) => ({
    key,
    label: labels[key],
    state: intervention && (key === "COMMIT" || key === "RESULT")
      ? "failed"
      : done[key] ? "done" : key === firstOpen && (running || !!s.plan || key === "PLANNING") ? "active" : "pending",
  }));
}

/** One sentence describing where the simulation stands, from backend state only. */
export function headline(s: Snapshot): { tone: "ok" | "bad" | "info"; title: string; text: string } | null {
  const attempt = s.attempts.at(-1);
  if (!attempt) return null;
  const n = attempt.attempt_number;
  switch (attempt.approval_status) {
    case "APPROVED":
      return { tone: "ok", title: "Plan approved and committed", text: `Attempt ${n}: agreements committed; they are now scheduled receipts and stock is reserved.` };
    case "HUMAN_INTERVENTION_REQUIRED":
      return { tone: "bad", title: "HUMAN INTERVENTION REQUIRED", text: `Attempt ${n} of 2 was rejected. Automatic replanning has stopped.` };
    case "AWAITING_APPROVAL":
      return attempt.approvable
        ? { tone: "info", title: "Agreement proposed: awaiting your approval", text: "AGREEMENT_PROPOSED is not COMMITTED. Nothing is committed or reserved until you approve." }
        : { tone: "bad", title: "Plan cannot be approved", text: "At least one shortage has no agreement. Reject to replan." };
    case "PENDING_NEGOTIATION":
      return { tone: "info", title: `Attempt ${n}: negotiation in progress`, text: "Answer as the Supplier Interface in each open negotiation below." };
    default:
      return null;
  }
}

// ---- plan summary for the before/after comparison (sums of backend numbers; no planning logic) ---------------------

export type PlanTotals = {
  orders: number;
  demand: number; // ordered finished-product quantity of the planned orders
  production: number; // MPS planned quantity
  mpsEntries: number;
  capacityIssues: number;
  maxCapacityUse: string; // e.g. "4 of 5 days"
  gross: Record<string, number>; // per component
  net: Record<string, number>; // per component
  shortages: number; // shortage rows
};

export function totals(state: { orders: { id: string }[]; plans: Record<string, import("./api").Plan> }): PlanTotals {
  const plans = Object.values(state.plans);
  const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
  const gross: Record<string, number> = {};
  const net: Record<string, number> = {};
  for (const row of plans.flatMap((p) => p.requirements)) {
    gross[row.item_id] = (gross[row.item_id] ?? 0) + row.gross_requirement;
    net[row.item_id] = (net[row.item_id] ?? 0) + row.net_requirement;
  }
  const checks = plans.flatMap((p) => p.capacity_checks);
  const busiest = checks.reduce<(typeof checks)[number] | null>((m, c) => (!m || c.required_days / c.working_days > m.required_days / m.working_days ? c : m), null);
  return {
    orders: plans.length,
    demand: sum(plans.flatMap((p) => p.finished_goods.map((f) => f.order_quantity))),
    production: sum(plans.flatMap((p) => p.mps.map((m) => m.planned_quantity))),
    mpsEntries: plans.reduce((n, p) => n + p.mps.length, 0),
    capacityIssues: checks.filter((c) => !c.feasible).length,
    maxCapacityUse: busiest ? `${busiest.required_days} of ${busiest.working_days} days` : "—",
    gross, net,
    shortages: plans.reduce((n, p) => n + p.shortages.length, 0),
  };
}
