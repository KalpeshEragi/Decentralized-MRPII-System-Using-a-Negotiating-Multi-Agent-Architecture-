// Thin client for the FastAPI backend. The backend is the source of truth; nothing here computes business results.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const READ_TIMEOUT_MS = 30_000;
const ACTION_TIMEOUT_MS = 10 * 60_000; // agent actions wait for A2A negotiation steps and optional LLM calls

export class ApiError extends Error {
  constructor(public code: string, message: string, public details: { field?: string; issue: string }[] = []) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, timeoutMs = READ_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") {
      throw new ApiError("TIMEOUT", "The backend did not answer in time. It may still be working; refresh to see the latest state.");
    }
    throw new ApiError("UNREACHABLE", `Cannot reach the backend at ${API_URL}. Is uvicorn running?`);
  } finally {
    clearTimeout(timer);
  }
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const error = data?.error; // C5 error body
    throw new ApiError(error?.code ?? `HTTP_${response.status}`, error?.message ?? "Request failed", error?.details ?? []);
  }
  return data as T;
}

const get = <T,>(path: string) => request<T>("GET", path);
const act = <T,>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}, ACTION_TIMEOUT_MS);

// ---- shapes (subset of the backend responses the UI reads) --------------------------------------------------------

export type Item = { id: string; sku: string; name: string; item_type: string; unit: string };
export type Order = {
  id: string; order_number: string; order_date: string; due_date: string; priority: number; status: string;
  lines: { item_id: string; quantity: number }[];
};
export type OrderOverview = Order & { customer_id: string; customer_name: string | null };
export type NewOrder = {
  customer_name: string; order_number?: string; order_date: string; due_date: string; priority: number;
  lines: { item_id: string; quantity: number }[];
};
export type Requirement = {
  mps_entry_id: string; item_id: string; gross_requirement: number; available_quantity: number;
  scheduled_receipts: number; projected_available_quantity: number; net_requirement: number;
  required_by: string; status: string;
};
export type Plan = {
  order_id: string; planning_date: string; status: string;
  finished_goods: { item_id: string; order_quantity: number; available_finished_goods: number; net_production_requirement: number }[];
  mps: { id: string; item_id: string; planned_quantity: number; planned_start: string; planned_end: string; priority: number }[];
  requirements: Requirement[];
  shortages: { item_id: string; shortage_quantity: number; required_by: string; priority: number }[];
  capacity_checks: { mps_entry_id: string; item_id: string; required_quantity: number; capacity_per_day: number; required_days: number; working_days: number; max_quantity: number; feasible: boolean }[];
  validation: { valid: boolean; violations: { code: string; message: string }[] };
};
export type SupplierFeasibility = {
  supplier: string; lead_time_days: number; min_order_qty: number; available_qty: number;
  arrival_date: string; usable: boolean; covers_alone: boolean;
};
export type ShortageWithSuppliers = { shortage: Plan["shortages"][number]; suppliers: SupplierFeasibility[] };
export type Terms = { quantity: number; required_date: string | null; delivery_date: string | null; priority: number | null };
export type Message = {
  message_id: string; sequence_number: number; message_type: string; sender: string; receiver: string;
  payload: { terms: Terms | null; message: string | null }; timestamp: string;
};
export type Negotiation = {
  id: string; status: string; round_number: number; max_rounds: number; awaiting_supplier: boolean;
  outcome: "AGREEMENT" | "FAILED" | null; objective: { item_id: string; shortage_quantity: number; required_by: string; priority: number };
  messages: Message[]; agreement: { agreed_terms: Terms; validated: boolean; committed: boolean } | null;
  reaction_error?: string;
};
export type Attempt = {
  order_id: string; attempt_number: number; approval_status: string; plan_status: string; approvable: boolean;
  blockers: string[]; attempts_remaining: number; decision_reason: string | null;
  negotiations: { negotiation_id: string; item_id: string; session_status: string; outcome: string | null }[];
};
export type Procurement = {
  negotiation_id: string; item_id: string; shortage_quantity: number; session_status: string;
  round_number: number; awaiting_supplier: boolean; outcome: string | null;
};
export type Decision = { id: string; agent: string; decision_type: string; context: Record<string, string>; reasoning_summary: string; created_at: string };

export const api = {
  health: () => get<{ status: string }>("/health"),
  items: () => get<Item[]>("/orders/items/catalog"),
  orders: () => get<OrderOverview[]>("/orders/overview"),
  createOrder: (order: NewOrder) => act<Order>("/orders", order),
  plan: (orderId: string) => get<Plan>(`/plans/${orderId}`),
  shortages: (orderId: string) => get<ShortageWithSuppliers[]>(`/plans/${orderId}/shortages`),
  attempts: (orderId: string) => get<Attempt[]>(`/plans/${orderId}/attempts`),
  negotiation: (id: string) => get<Negotiation>(`/negotiations/${id}`),
  decisions: (orderId?: string) => get<Decision[]>(orderId ? `/agents/decisions?order_id=${orderId}` : "/agents/decisions"),
  procurement: (orderId: string) => get<Procurement[]>(`/agents/planning/orders/${orderId}/procurement-results`),

  reset: () => act<{ order_id: string | null }>("/simulation/reset?include_order=false"),
  runPlanning: () => act<{ new_orders: string[]; plans: { order_id: string; order_number: string; plan_status: string }[] }>("/agents/planning/run"),
  approve: (orderId: string, attempt: number) => act<unknown>(`/plans/${orderId}/attempts/${attempt}/approve`),
  reject: (orderId: string, attempt: number, reason: string) => act<unknown>(`/plans/${orderId}/attempts/${attempt}/reject`, { reason }),
};

/** 404 means "not there yet" (e.g. an order that has not been planned): return null instead of failing. */
export async function orNull<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && error.code === "NOT_FOUND") return null;
    throw error;
  }
}
