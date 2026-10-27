// Thin client for the FastAPI backend (FE-6): the panel only reads the observer doors and uses the simulation doors.
// Nothing here computes a business result; the backend is the source of truth.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/backend";  // forwarded to the backend (next.config.mjs)
// Local demo only: the simulator's door key (SIMULATION_DOOR_KEY in the backend's .env).
const DOOR_KEY = process.env.NEXT_PUBLIC_SIMULATION_DOOR_KEY ?? "";

export class ApiError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, timeoutMs = 30_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers: { "Content-Type": "application/json", "X-Door-Key": DOOR_KEY },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw new ApiError("TIMEOUT", "The backend did not answer in time.");
    throw new ApiError("UNREACHABLE", `Cannot reach the backend at ${API_URL}. Is it running?`);
  } finally {
    clearTimeout(timer);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // RFC 9457 problem details (API-1): {code, detail, errors}
    throw new ApiError(data.code ?? `HTTP_${response.status}`, data.detail ?? data.title ?? response.statusText);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown = {}, timeoutMs?: number) => request<T>("POST", path, body, timeoutMs),
  put: <T>(path: string, body: unknown = {}) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

// -- shapes the panel reads ----------------------------------------------------------------------------------------

export type Live = {
  clock: { day: string; hour: number; shift: [number, number]; status: "PAUSED" | "RUNNING";
    waiting: Record<string, number>; pause_reason: string | null };
  ai_enabled: boolean;
  workers: { code: string; name: string; primary_skill: string; secondary_skills: string[]; absent: boolean }[];
  run: { id: number; scenario: string; start_day: string } | null;
  kpis: {
    stock_on_hand: string;
    orders_open: number;
    orders_completed: number;
    on_time_percent: number | null;
    plan_at_risk: number;
    ai_calls: number;
  };
  stock: { item_id: string; sku: string; name: string; type: string; on_hand: string; reserved: string; held: string }[];
  zones: { zone: string; capacity_units: string; occupied_now: string }[];
  lines: { work_center: string; machine_hours_free: string;
    orders_today: { id: string; sku: string | null; quantity: string; status: string; quantity_completed: string }[] }[];
  docks: {
    inbound: { commitment_id: string; sku: string | null; quantity: string; status: string; arrival_day: string }[];
    outbound: { order_ref: string; sku: string | null; quantity: string; delivery_day: string }[];
  };
  orders: { demand_id: string; order_number: string | null; sku: string | null; quantity: string; status: string; committed_day: string | null; requested_day: string }[];
  negotiations_open: { session_id: string; case_id: string; starter: string; owner: string; resource_type: string; status: string; round: number }[];
};

export type TimelineItem = {
  time: string;
  source: "event" | "negotiation" | "trigger" | "ai_call" | "failed_work";
  type?: string;
  publisher?: string;
  subscribers?: string[];
  payload?: Record<string, unknown>;
  correlation_id?: string;
  from?: string;
  to?: string;
  case_id?: string;
  session_id?: string;
  terms?: Record<string, unknown> | null;
  options?: Record<string, unknown>[] | null;  // QUOTE: the owner's quoted options
  reason_code?: string | null;
  text?: string | null;
  order_label?: string | null;     // what the negotiation is for: "PO MB×90", "SO-1001"
  resource_label?: string | null;  // the resource in words: an item's SKU, a skill, a zone
  params?: Record<string, unknown>;
  status?: string;
  scheduled_day?: string | null;
  agent?: string;
  purpose?: string;
  outcome?: string;
  queue?: string;
  error?: string;
};

export type Scenario = { name: string; description: string; triggers: { day: number; kind: string; params: Record<string, unknown> }[] };

export type ProductionOrderRow = {
  id: string; item_id: string; quantity: string; status: string; start_day: string; end_day: string;
  for_kind: string; for_ref: string; label: string | null; sku: string | null; work_centers: string[];
};

export type StoryNegotiation = {
  session_id: string; case_id: string; starter: string; owner: string; resource_type: string; resource_ref: string;
  resource_label: string | null; status: string; asked: Record<string, unknown>; order_id: string | null;
  order_label: string | null; started_at: string | null; agreed_terms: Record<string, unknown> | null;
  last_reason_code: string | null;
};

export type StoryEvent = {
  event_id: string; type: string; publisher: string; entity: string; correlation_id: string | null;
  payload: Record<string, unknown>; subscribers: string[]; time: string;
};

export type OrderStory = {
  plan: {
    demand_id: string; request_ref: string; order_number: string | null; status: string; quantity: string;
    item_id: string; sku: string | null; label: string | null;
    requested_day: string; committed_quantity: string | null; committed_day: string | null;
    production_orders: ProductionOrderRow[];
  };
  sales: { stage: string; order_number: string | null } | null;
  customer: CustomerConversation | null;
  refs: string[];  // every id this order is known by: picks its lines out of the timeline
  cases: { case_id: string; kind: string; status: string; depth: number; created_at: string | null }[];
  negotiations: StoryNegotiation[];
  events: StoryEvent[];
};

export type CustomerConversation = {
  inquiry_id: string; stage: string; closed_reason: string | null; quantity: string | null;
  requested_date: string | null; created_at: string; confirmed_at: string | null;
  options: { kind: string; quantity: string; delivery_date: string; status: string; reason_code: string | null; created_at: string }[];
  messages: { direction: "IN" | "OUT"; text: string; time: string }[];
};

export type TriggerResult = { id: number; kind: string; status: string; result: Record<string, unknown> | null };

export type RunSummary = { id: number; scenario: string; status: string; start_day: string; end_day: string | null };

export type RunReport = {
  run: { id: number; scenario: string; seed: number; start_day: string; end_day: string | null };
  metrics: {
    orders: number; completed: number; completed_on_time: number; plan_at_risk_events: number;
    orders_by_status: Record<string, number>; events_by_type: Record<string, number>;
    ai_calls_by_outcome: Record<string, number>;
  };
  triggers: { kind: string; status: string; scheduled_day: string | null; params: Record<string, unknown> }[];
};
