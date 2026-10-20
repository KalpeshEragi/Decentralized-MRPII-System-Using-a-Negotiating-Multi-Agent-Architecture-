"use client";
// The cards floating over the 3D factory: KPIs, the detail of what was clicked, one order's tracking, docks and lines.
// All figures come from the observer; nothing is computed here except display formatting.

import { useEffect, useState } from "react";
import { agent, describeEvent } from "@/lib/agents";
import { api, Live, OrderStory, TimelineItem } from "@/lib/api";

export type Selection =
  | { kind: "item"; id: string } | { kind: "line"; id: string } | { kind: "zone"; id: string }
  | { kind: "dock"; id: "inbound" | "outbound" } | null;

const num = (v: string | number | null | undefined) =>
  v === null || v === undefined ? "–" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 });

export function KpiCards({ live }: { live: Live | null }) {
  const k = live?.kpis;
  const cards = [
    { icon: "📦", label: "Stock on hand", value: num(k?.stock_on_hand), sub: "units, all items" },
    { icon: "🧾", label: "Open orders", value: num(k?.orders_open), sub: `${num(k?.orders_completed)} completed` },
    { icon: "⏱", label: "On-time delivery", value: k?.on_time_percent == null ? "–" : `${k.on_time_percent}%`,
      sub: "completed orders" },
    { icon: "⚠", label: "Plans at risk", value: num(k?.plan_at_risk), sub: `${num(k?.ai_calls)} AI calls` },
  ];
  return (
    <div className="kpis">
      {cards.map((c) => (
        <div key={c.label} className="card kpi">
          <div className="kpi-icon">{c.icon}</div>
          <div><div className="kpi-label">{c.label}</div><div className="kpi-value">{c.value}</div>
            <div className="kpi-sub">{c.sub}</div></div>
        </div>
      ))}
    </div>
  );
}

export function DetailCard({ live, selection, onClose }: { live: Live | null; selection: Selection; onClose: () => void }) {
  if (!live || !selection) return null;
  let kind = "", title = "", rows: [string, string][] = [];
  if (selection.kind === "item") {
    const s = live.stock.find((x) => x.item_id === selection.id);
    if (!s) return null;
    kind = `${s.type.toLowerCase().replaceAll("_", " ")} · Inventory`; title = `${s.name} (${s.sku})`;
    rows = [["On hand", num(s.on_hand)], ["Reserved for orders", num(s.reserved)], ["Held in negotiations", num(s.held)],
      ["Free now", num(Number(s.on_hand) - Number(s.reserved) - Number(s.held))]];
  } else if (selection.kind === "line") {
    const l = live.lines.find((x) => x.work_center === selection.id);
    if (!l) return null;
    kind = "Production line · Planning"; title = l.work_center === "SMT" ? "SMT line (main boards)" : "Assembly line";
    rows = [["Machine-hours free today", num(l.machine_hours_free)],
      ["Orders with work today", String(l.orders_today.length)],
      ...l.orders_today.map((o) => [`${o.sku}`, `${num(o.quantity)} · ${o.status}`] as [string, string])];
  } else if (selection.kind === "zone") {
    const z = live.zones.find((x) => x.zone === selection.id);
    if (!z) return null;
    kind = "Storage zone · Warehouse"; title = z.zone === "MATERIALS" ? "Materials zone" : "Finished goods zone";
    rows = [["Capacity (space units)", num(z.capacity_units)], ["Occupied now", num(z.occupied_now)],
      ["Used", `${Math.round((100 * Number(z.occupied_now)) / Math.max(1, Number(z.capacity_units)))}%`]];
  } else {
    const list = selection.id === "inbound" ? live.docks.inbound : live.docks.outbound;
    kind = "Dock · Warehouse"; title = selection.id === "inbound" ? "Receiving dock" : "Shipping dock";
    rows = list.length ? list.map((d) => [d.sku ?? "item", `${num(d.quantity)}`] as [string, string])
      : [["Today and tomorrow", "nothing planned"]];
  }
  return (
    <div className="card detail">
      <button className="close" onClick={onClose}>×</button>
      <div className="kind">{kind}</div>
      <h3>{title}</h3>
      {rows.map(([a, b], i) => <div className="row" key={i}><span>{a}</span><span>{b}</span></div>)}
    </div>
  );
}

const STEPS = ["Requested", "Committed", "Released", "In production", "Produced", "Shipped"];

function stepOf(story: OrderStory | null): number {
  if (!story) return -1;
  const types = new Set(story.events.map((e) => e.type));
  if (story.plan.status === "COMPLETED") return 5;
  if (types.has("FinishedGoodsStored")) return 4;
  if (types.has("ProductionStarted")) return 3;
  if (types.has("ProductionOrderReleased")) return 2;
  if (types.has("PlanCommitted") || story.plan.status === "COMMITTED") return 1;
  return 0;
}

export function OrderTracker({ live, onFocusCase }: { live: Live | null; onFocusCase: (c: string | null) => void }) {
  const orders = live?.orders ?? [];
  const [chosen, setChosen] = useState<string | null>(null);
  const [story, setStory] = useState<OrderStory | null>(null);
  const current = chosen ?? orders[0]?.demand_id ?? null;
  const day = live?.clock.day;

  useEffect(() => {
    if (!current) { setStory(null); return; }
    api.get<OrderStory>(`/observer/orders/${current}`).then(setStory).catch(() => setStory(null));
  }, [current, day, live?.kpis.orders_completed, live?.kpis.orders_open]);

  const step = stepOf(story);
  const order = orders.find((o) => o.demand_id === current);
  return (
    <div className="card tracker">
      <h4>
        <span>🚚 Order tracking</span>
        <select className="btn" value={current ?? ""} onChange={(e) => setChosen(e.target.value)}>
          {orders.length === 0 && <option value="">no orders yet</option>}
          {orders.map((o) => (
            <option key={o.demand_id} value={o.demand_id}>
              {o.order_number ?? "request"} · {num(o.quantity)} {o.sku} · {o.status.toLowerCase()}
            </option>
          ))}
        </select>
      </h4>
      <div className="steps">
        {STEPS.map((label, i) => (
          <div key={label} className={`step ${i < step || step === 5 ? "done" : i === step ? "now" : ""}`}>
            <div className="ball">{i < step || step === 5 ? "✓" : i + 1}</div>{label}
          </div>
        ))}
      </div>
      {order && (
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 10, display: "flex", gap: 12, flexWrap: "wrap" }}>
          <span>Requested by {order.requested_day}</span>
          <span>Promised {order.committed_day ?? "–"}</span>
          {story && story.negotiations.length > 0 && (
            <a href="#" onClick={(e) => { e.preventDefault(); onFocusCase(story.negotiations[0].case_id); }}>
              show its {story.negotiations.length} negotiations in the conversation
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export function DocksPanel({ live, onSelect }: { live: Live | null; onSelect: (s: Selection) => void }) {
  const [tab, setTab] = useState<"docks" | "lines" | "talks">("docks");
  if (!live) return null;
  return (
    <div className="card docks">
      <h4>
        <div className="tabs">
          <button className={`tab ${tab === "docks" ? "on" : ""}`} onClick={() => setTab("docks")}>
            Docks {live.docks.inbound.length + live.docks.outbound.length}</button>
          <button className={`tab ${tab === "lines" ? "on" : ""}`} onClick={() => setTab("lines")}>Lines {live.lines.length}</button>
          <button className={`tab ${tab === "talks" ? "on" : ""}`} onClick={() => setTab("talks")}>
            Negotiating {live.negotiations_open.length}</button>
        </div>
      </h4>
      {tab === "docks" && <>
        {live.docks.inbound.map((d) => (
          <div className="dock-row" key={d.commitment_id} onClick={() => onSelect({ kind: "dock", id: "inbound" })}>
            <b>Inbound</b><span>{num(d.quantity)} {d.sku} · {d.arrival_day}</span>
            <span className={`badge ${d.status === "RECEIVED" ? "green" : "blue"}`}>{d.status === "RECEIVED" ? "Received" : "Expected"}</span>
          </div>))}
        {live.docks.outbound.map((d) => (
          <div className="dock-row" key={d.order_ref} onClick={() => onSelect({ kind: "dock", id: "outbound" })}>
            <b>Outbound</b><span>{num(d.quantity)} {d.sku} · {d.delivery_day}</span><span className="badge amber">Due</span>
          </div>))}
        {live.docks.inbound.length + live.docks.outbound.length === 0 &&
          <div className="dock-row"><b>—</b><span>No trucks today or tomorrow</span><span className="badge">Idle</span></div>}
      </>}
      {tab === "lines" && live.lines.map((l) => (
        <div className="dock-row" key={l.work_center} onClick={() => onSelect({ kind: "line", id: l.work_center })}>
          <b>{l.work_center}</b><span>{l.orders_today.map((o) => `${num(o.quantity)} ${o.sku}`).join(", ") || "no work today"}</span>
          <span className={`badge ${l.orders_today.some((o) => o.status === "STARTED") ? "green" : "blue"}`}>
            {num(l.machine_hours_free)} h free</span>
        </div>))}
      {tab === "talks" && (live.negotiations_open.length ? live.negotiations_open.map((n) => (
        <div className="dock-row" key={n.session_id}>
          <b>{n.starter.slice(0, 4)}→{n.owner.slice(0, 4)}</b><span>{n.resource_type.toLowerCase()} · round {n.round}</span>
          <span className="badge blue">{n.status === "AGREEMENT_PROPOSED" ? "held" : "talking"}</span>
        </div>)) : <div className="dock-row"><b>—</b><span>No open negotiation</span><span className="badge">Quiet</span></div>)}
    </div>
  );
}

// Disruptions and the agents' reactions to them, newest first (the full story is in the agent conversation).
const ALERT_EVENTS = new Set(["SupplierDeliveryDelayed", "WorkforceCapacityChanged", "PlanAtRisk", "PlanRevised",
  "PlanCommitFailed", "OrderCancelled", "OrderChangeRequested", "SafetyStockBreached", "StorageCapacityChanged"]);
const CALM = new Set(["PlanRevised"]);

export function AlertFeed({ items }: { items: TimelineItem[] }) {
  const alerts = items.filter((i) => i.source === "trigger" || (i.source === "event" && ALERT_EVENTS.has(i.type ?? "")))
    .slice(-4).reverse();
  if (!alerts.length) return null;
  return (
    <div className="card alerts">
      <h4>⚡ Disruptions & reactions</h4>
      {alerts.map((a, n) => {
        const trigger = a.source === "trigger";
        const text = trigger ? `Simulator: ${String(a.type).toLowerCase().replaceAll("_", " ")}${
          a.scheduled_day ? ` (planned for ${a.scheduled_day})` : ""}` : describeEvent(a);
        const tone = trigger ? "amber" : CALM.has(a.type ?? "") ? "blue" : "red";
        return (
          <div className="alert" key={`${a.time}-${n}`}>
            <span className={`badge ${tone}`}>{trigger ? "trigger" : agent(a.publisher).name}</span>
            <span>{text}</span>
          </div>
        );
      })}
    </div>
  );
}
