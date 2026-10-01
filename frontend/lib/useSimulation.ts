"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, ApiError, orNull,
  type Attempt, type Decision, type Item, type Negotiation, type OrderOverview, type Plan, type Procurement,
  type ShortageWithSuppliers,
} from "./api";

export type Snapshot = {
  items: Record<string, Item>;
  orders: OrderOverview[];
  plans: Record<string, Plan>; // every planned order's persisted plan (combined demand, computed by the backend)
  plan: Plan | null; // the selected order's plan
  shortages: ShortageWithSuppliers[]; // selected order
  attempts: Attempt[]; // selected order
  negotiations: Record<string, Negotiation>; // selected order's attempts
  decisions: Decision[]; // all orders
};

export type Operation = { label: string; startedAt: number; decisionsBefore: number; agents: boolean };
/** Before/after pair of backend plans, kept when Run / Replan changes the plan. */
export type PlanState = { orders: OrderOverview[]; plans: Record<string, Plan> };
export type PlanChange = { before: PlanState; after: PlanState };

const EMPTY: Snapshot = { items: {}, orders: [], plans: {}, plan: null, shortages: [], attempts: [], negotiations: {}, decisions: [] };
const POLL_MS = 2000;

const toError = (e: unknown) => (e instanceof ApiError ? e : new ApiError("UNKNOWN", String(e)));

/** All UI state comes from the backend. `run` executes one long action while polling the real progress. */
export function useSimulation() {
  const [snapshot, setSnapshot] = useState<Snapshot>(EMPTY);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [operation, setOperation] = useState<Operation | null>(null);
  const [liveProcurement, setLiveProcurement] = useState<Procurement[]>([]);
  const [change, setChange] = useState<PlanChange | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const busy = useRef(false);

  const load = useCallback(async (preferredOrder?: string | null): Promise<Snapshot> => {
    const [itemList, orders, decisions] = await Promise.all([api.items(), api.orders(), api.decisions()]);
    const items = Object.fromEntries(itemList.map((i) => [i.id, i]));
    const planned = orders.filter((o) => o.status === "PLANNED");
    const planList = await Promise.all(planned.map((o) => orNull(api.plan(o.id))));
    const plans = Object.fromEntries(planList.filter((p): p is Plan => !!p).map((p) => [p.order_id, p]));
    const id = preferredOrder && orders.some((o) => o.id === preferredOrder) ? preferredOrder : planned[0]?.id ?? orders[0]?.id ?? null;
    setOrderId(id);
    let next: Snapshot = { ...EMPTY, items, orders, plans, decisions };
    if (id) {
      const plan = plans[id] ?? null;
      const [attempts, shortages] = await Promise.all([api.attempts(id), plan ? api.shortages(id) : Promise.resolve([])]);
      const ids = [...new Set(attempts.flatMap((a) => a.negotiations.map((n) => n.negotiation_id)))];
      const views = await Promise.all(ids.map((n) => api.negotiation(n)));
      next = { ...next, plan, attempts, shortages, negotiations: Object.fromEntries(views.map((v) => [v.id, v])) };
    }
    setSnapshot(next);
    setLiveProcurement([]);
    return next;
  }, []);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      await load(orderId);
    } catch (e) {
      setError(toError(e));
    } finally {
      setLoading(false);
    }
  }, [load, orderId]);

  useEffect(() => { void refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selectOrder = useCallback((id: string) => {
    if (busy.current) return;
    setLoading(true);
    load(id).catch((e) => setError(toError(e))).finally(() => setLoading(false));
  }, [load]);

  /** Run one backend action. Only one at a time; the page stays usable and shows real progress while it runs.
   *  `trackChange` keeps the plans before and after, so the UI can show what changed. */
  const run = useCallback(async (label: string, action: () => Promise<unknown>,
    options: { success?: string; agents?: boolean; trackChange?: boolean; select?: (result: unknown) => string | null } = {}) => {
    if (busy.current) return false;
    busy.current = true;
    setError(null);
    setNotice(null);
    const before: PlanState = { orders: snapshot.orders, plans: snapshot.plans };
    setOperation({ label, startedAt: Date.now(), decisionsBefore: snapshot.decisions.length, agents: options.agents ?? true });
    const currentOrder = orderId;
    const poll = setInterval(async () => {
      try {
        const [decisions, procurement] = await Promise.all([
          api.decisions(), currentOrder ? api.procurement(currentOrder) : Promise.resolve([]),
        ]);
        setSnapshot((s) => ({ ...s, decisions }));
        setLiveProcurement(procurement);
      } catch { /* polling is best effort; the action result decides */ }
    }, POLL_MS);
    let ok = false;
    try {
      const result = await action();
      const after = await load(options.select?.(result) ?? currentOrder);
      if (options.trackChange) setChange({ before, after: { orders: after.orders, plans: after.plans } });
      if (options.success) setNotice(options.success);
      ok = true;
    } catch (e) {
      setError(toError(e));
      try { await load(currentOrder); } catch { /* keep what is shown */ }
    } finally {
      clearInterval(poll);
      setOperation(null);
      busy.current = false;
    }
    return ok;
  }, [load, orderId, snapshot]);

  return {
    snapshot, orderId, selectOrder, loading, operation, liveProcurement, change, setChange, error, notice, refresh, run,
  };
}
