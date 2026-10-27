"use client";
// The cockpit strip over the 3D town: where the simulation stands and the headline numbers, with the two views that
// tell the demo story (disruptions and plan changes). Replaces the four KPI cards; the same figures are kept.

import type { Live } from "@/lib/api";
import type { Incident, OrderComparison } from "@/lib/insight";

export function Cockpit({ live, incidents, comparisons, onIncidents, onPlans }: {
  live: Live | null; incidents: Incident[]; comparisons: OrderComparison[];
  onIncidents: () => void; onPlans: () => void;
}) {
  const waiting = live ? Object.values(live.clock.waiting).reduce((a, b) => a + b, 0) : 0;
  const latest = incidents[incidents.length - 1];
  const handling = latest !== undefined && latest.unresolved.length > 0;  // the newest disruption still has open talks
  const state = !live ? { text: "No connection", tone: "red" }
    : handling ? { text: "Handling disruption", tone: "red" }
    : live.clock.status === "RUNNING" ? { text: "Running", tone: "green" }
    : waiting ? { text: "Agents working", tone: "blue" }
    : { text: "Paused", tone: "" };
  const atRisk = comparisons.filter((c) => c.verdict === "AT_RISK").length;
  const changed = comparisons.filter((c) => c.changes.length > 0).length;
  const k = live?.kpis;

  const stats: [string, string, string][] = [
    ["Day", live?.clock.day ?? "–", "Simulated day"],
    ["Active orders", String(k?.orders_open ?? "–"), "Committed or being planned"],
    ["At risk now", String(atRisk), "Orders whose latest plan event is PlanAtRisk"],
    ["Completed", `${k?.orders_completed ?? "–"}${k?.on_time_percent != null ? ` · ${k.on_time_percent}% on time` : ""}`, "Shipped orders"],
    ["Stock on hand", k ? Number(k.stock_on_hand).toLocaleString() : "–", "Units of all items"],
  ];
  return (
    <div className="cockpit card">
      <span className={`badge big ${state.tone}`}>{state.text}</span>
      {stats.map(([label, value, help]) => (
        <div key={label} className="stat" title={help}><small>{label}</small><b>{value}</b></div>
      ))}
      <button className={`btn ${incidents.length ? "warn" : ""}`} onClick={onIncidents}
              title="Every disruption, who reacted, and what changed">
        🚨 Disruptions <b>{incidents.length}</b>
      </button>
      <button className="btn" onClick={onPlans} title="Each order's committed plan compared with now">
        📋 Plan changes <b>{changed}</b>
      </button>
    </div>
  );
}
