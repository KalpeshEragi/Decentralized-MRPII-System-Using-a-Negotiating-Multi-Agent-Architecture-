"use client";
// One agent's real state: its status, open negotiations, what it owns right now (from the live snapshot, or for Sales
// from its read-only dashboard doors) and its recent activity (events and negotiation threads from the timeline).

import { useEffect, useMemo, useState } from "react";
import { agent } from "@/lib/agents";
import { api, Live, TimelineItem } from "@/lib/api";
import { AgentCode, AgentView, involves, ROLE, STATUS_HELP } from "@/lib/insight";
import { NegotiationThread, toEntries } from "@/components/NegotiationThread";
import { ICON, summarize } from "./AgentBoard";

const num = (v: string | number | null | undefined) =>
  v === null || v === undefined ? "–" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 });

export function AgentDetail({ view, live, items, onClose, onOpenStory }: {
  view: AgentView; live: Live | null; items: TimelineItem[]; onClose: () => void; onOpenStory: (demandId: string) => void;
}) {
  const a = agent(view.code);
  const open = (live?.negotiations_open ?? []).filter((s) => s.starter === view.code || s.owner === view.code);
  const recent = useMemo(() => toEntries(items.filter((i) => involves(i, view.code)
    && !(i.source === "event" && i.type === "SimulatedDayStarted")).slice(-60)).reverse(), [items, view.code]);

  return (
    <div className="drawer card">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <header className="drawer-head" style={{ borderColor: a.color }}>
        <span className="agent-icon big">{ICON[view.code]}</span>
        <div>
          <h3>{a.name} agent</h3>
          <div className="muted">{ROLE[view.code]}</div>
        </div>
      </header>
      <section>
        <h4>Now</h4>
        <p><span className="badge blue">{view.status}</span> {STATUS_HELP[view.status]}{view.alert ? ` — ${view.alert}` : ""}</p>
        {open.length > 0 ? (
          <table className="grid"><thead><tr><th>With</th><th>About</th><th>Round</th><th>State</th></tr></thead>
            <tbody>{open.map((s) => (
              <tr key={s.session_id}>
                <td>{s.starter === view.code ? `asked ${agent(s.owner).name}` : `asked by ${agent(s.starter).name}`}</td>
                <td>{s.resource_type.toLowerCase().replaceAll("_", " ")}</td><td>{s.round}</td>
                <td>{s.status.toLowerCase().replaceAll("_", " ")}</td>
              </tr>))}</tbody></table>
        ) : <p className="muted">No open negotiation.</p>}
      </section>
      <section>
        <h4>What it owns right now</h4>
        <Owned code={view.code} live={live} items={items} onOpenStory={onOpenStory} />
      </section>
      <section>
        <h4>Recent activity <span className="muted">(newest first, real messages and events)</span></h4>
        {recent.length === 0 && <p className="muted">Nothing yet.</p>}
        <div className="activity">
          {recent.map((e, i) => e.kind === "thread"
            ? <NegotiationThread key={e.session} steps={e.steps} />
            : <div key={i} className="notice left"><span className="time">{e.item.time.slice(11, 19)}</span> {summarize(e.item)}</div>)}
        </div>
      </section>
    </div>
  );
}

function Owned({ code, live, items, onOpenStory }: {
  code: AgentCode; live: Live | null; items: TimelineItem[]; onOpenStory: (demandId: string) => void;
}) {
  if (!live) return <p className="muted">Waiting for the backend…</p>;
  switch (code) {
    case "SALES": return <SalesOwned live={live} onOpenStory={onOpenStory} />;
    case "PLANNING": return <>
      <Table head={["Order", "Product × qty", "Status", "Committed day", "Requested"]}
             rows={live.orders.map((o) => [o.order_number ?? "–", `${o.sku} × ${num(o.quantity)}`, o.status,
               o.committed_day ?? "–", o.requested_day])}
             onRow={(i) => onOpenStory(live.orders[i].demand_id)} />
      <Table head={["Line", "Machine-hours free today", "Orders with work today"]}
             rows={live.lines.map((l) => [l.work_center, num(l.machine_hours_free), String(l.orders_today.length)])} />
    </>;
    case "INVENTORY": return <Table head={["Item", "On hand", "Reserved", "Held", "Free"]}
      rows={live.stock.map((s) => [`${s.name} (${s.sku})`, num(s.on_hand), num(s.reserved), num(s.held),
        num(Number(s.on_hand) - Number(s.reserved) - Number(s.held))])} />;
    case "PURCHASING": {
      const delays = items.filter((i) => i.type === "SupplierDeliveryDelayed");
      return <>
        <Table head={["Delivery (today / tomorrow)", "Qty", "Arrives", "Status"]}
               rows={live.docks.inbound.map((d) => [d.sku ?? "–", num(d.quantity), d.arrival_day, d.status])}
               empty="No supplier delivery due today or tomorrow." />
        <Table head={["Supplier delay", "Qty", "Was", "Now"]}
               rows={delays.map((d) => [live.stock.find((s) => s.item_id === d.payload?.item_id)?.sku ?? "item", num(String(d.payload?.quantity)),
                 String(d.payload?.old_date), String(d.payload?.new_date)])} empty="No supplier delay so far." />
      </>;
    }
    case "WAREHOUSE": return <>
      <Table head={["Zone", "Capacity", "Occupied", "Used"]}
             rows={live.zones.map((z) => [z.zone, num(z.capacity_units), num(z.occupied_now),
               `${Math.round((100 * Number(z.occupied_now)) / Math.max(1, Number(z.capacity_units)))}%`])} />
      <Table head={["Shipping (tomorrow)", "Qty", "Delivery day"]}
             rows={live.docks.outbound.map((s) => [s.sku ?? "–", num(s.quantity), s.delivery_day])} empty="Nothing to ship tomorrow." />
    </>;
    case "HR": return <Table head={["Worker", "Main skill", "Also", `Today (${live.clock.day})`]}
      rows={live.workers.map((w) => [`${w.name} (${w.code})`, w.primary_skill, w.secondary_skills.join(", ") || "–",
        w.absent ? "ABSENT" : "available"])} />;
  }
}

type SalesOverview = { inquiries: number; inquiry_stages: Record<string, number>; orders_placed: number;
  order_statuses: Record<string, number>; conversion_rate: number | null; closed_reasons: Record<string, number>;
  ai_failures: number; customers: number };

/** Sales' own figures come from its read-only dashboard doors; production progress comes from Planning's orders. */
function SalesOwned({ live, onOpenStory }: { live: Live; onOpenStory: (demandId: string) => void }) {
  const [overview, setOverview] = useState<SalesOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get<SalesOverview>("/sales/dashboard/overview").then(setOverview).catch((e) => setError((e as Error).message));
  }, [live.clock.day, live.orders.length]);
  return <>
    {overview ? <div className="facts">
      <div><small>Customers</small><b>{overview.customers}</b></div>
      <div><small>Inquiries</small><b>{overview.inquiries}</b></div>
      <div><small>Orders placed</small><b>{overview.orders_placed}</b></div>
      <div><small>Conversion</small><b>{overview.conversion_rate == null ? "–" : `${Math.round(overview.conversion_rate * 100)}%`}</b></div>
      <div><small>AI failures</small><b>{overview.ai_failures}</b></div>
      <div className="wide"><small>Inquiry stages</small>{Object.entries(overview.inquiry_stages).map(([k, v]) =>
        <span key={k} className="badge">{k.toLowerCase().replaceAll("_", " ")} {v}</span>)}</div>
      {Object.keys(overview.closed_reasons).length > 0 && <div className="wide"><small>Why inquiries closed</small>
        {Object.entries(overview.closed_reasons).map(([k, v]) => <span key={k} className="badge amber">{k.toLowerCase().replaceAll("_", " ")} {v}</span>)}</div>}
    </div> : <p className="muted">{error ? `Sales figures unavailable: ${error}` : "Loading Sales figures…"}</p>}
    <Table head={["Order", "Product × qty", "Plan status", "Committed day"]}
           rows={live.orders.filter((o) => o.order_number).map((o) => [o.order_number!, `${o.sku} × ${num(o.quantity)}`, o.status, o.committed_day ?? "–"])}
           onRow={(i) => onOpenStory(live.orders.filter((o) => o.order_number)[i].demand_id)} empty="No confirmed order yet." />
  </>;
}

function Table({ head, rows, onRow, empty = "None." }: {
  head: string[]; rows: string[][]; onRow?: (i: number) => void; empty?: string;
}) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  return (
    <table className="grid">
      <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i} className={onRow ? "click" : ""} onClick={onRow ? () => onRow(i) : undefined}>
          {r.map((c, j) => <td key={j} className={c === "ABSENT" ? "red" : ""}>{c}</td>)}
        </tr>))}</tbody>
    </table>
  );
}
