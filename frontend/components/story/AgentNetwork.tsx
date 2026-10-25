"use client";
// The six agents of one order as a network (FE-4): Planning in the middle, the owners around it. A line glows while a
// negotiation on it is open and a pulse runs along it for each new message; an agent that publishes an event sends a
// ring wave, and every subscriber of that event gets a ping. Counts on each line: agreed / open / failed sessions.

import type { StoryNegotiation, TimelineItem } from "@/lib/api";
import { agent } from "@/lib/agents";
import type { Arrived } from "./useArrivals";

const W = 380, H = 320, CX = 190, CY = 160, R = 120;
const RING = ["SALES", "INVENTORY", "WAREHOUSE", "PURCHASING", "HR"];
export const POS: Record<string, { x: number; y: number }> = {
  PLANNING: { x: CX, y: CY },
  ...Object.fromEntries(RING.map((code, i) => {
    const angle = (-90 + i * 72) * Math.PI / 180;
    return [code, { x: CX + R * Math.cos(angle), y: CY + R * Math.sin(angle) }];
  })),
};
const EDGES: [string, string][] = [
  ["SALES", "PLANNING"], ["PLANNING", "INVENTORY"], ["PLANNING", "WAREHOUSE"], ["PLANNING", "PURCHASING"],
  ["PLANNING", "HR"], ["PURCHASING", "WAREHOUSE"],
];
const OK = new Set(["COMMITTED"]);
const BAD = new Set(["REJECTED", "ABORTED", "EXPIRED", "FAILED"]);

export function AgentNetwork({ negotiations, arrivals, focusOwner, onFocusOwner }: {
  negotiations: StoryNegotiation[]; arrivals: Arrived[]; focusOwner: string | null;
  onFocusOwner: (owner: string | null) => void;
}) {
  const talking = arrivals.filter((a) => a.item.source === "negotiation");
  const published = arrivals.filter((a) => a.item.source === "event");

  return (
    <svg className="network" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="The six agents of this order">
      {EDGES.map(([a, b]) => {
        const sessions = negotiations.filter((n) => pair(n.starter, n.owner) === pair(a, b));
        const open = sessions.filter((n) => !OK.has(n.status) && !BAD.has(n.status)).length;
        const done = sessions.filter((n) => OK.has(n.status)).length;
        const failed = sessions.filter((n) => BAD.has(n.status)).length;
        const p = POS[a], q = POS[b];
        const tone = open ? "open" : failed && !done ? "failed" : done ? "done" : "idle";
        const dim = focusOwner && a !== focusOwner && b !== focusOwner;
        return (
          <g key={`${a}-${b}`} className={`edge ${tone} ${dim ? "dim" : ""}`}>
            <line x1={p.x} y1={p.y} x2={q.x} y2={q.y} />
            {sessions.length > 0 && (
              <text x={(p.x + q.x) / 2} y={(p.y + q.y) / 2 - 6} textAnchor="middle" className="edge-count">
                {done ? `${done}✓` : ""}{open ? ` ${open}…` : ""}{failed ? ` ${failed}✕` : ""}
              </text>
            )}
          </g>
        );
      })}
      {talking.map(({ key, item }) => {
        const p = POS[item.from ?? ""], q = POS[item.to ?? ""];
        if (!p || !q) return null;
        return (
          <circle key={key} r={5} className="pulse" fill={agent(item.from).color}>
            <animateMotion dur="1.2s" fill="freeze" path={`M${p.x},${p.y} L${q.x},${q.y}`} />
          </circle>
        );
      })}
      {published.map(({ key, item }) => {
        const p = POS[item.publisher ?? ""];
        if (!p) return null;
        return <g key={key}>
          <circle cx={p.x} cy={p.y} r={22} className="wave" stroke={agent(item.publisher).color} />
          {(item.subscribers ?? []).map((s) => POS[s] && (
            <circle key={s} cx={POS[s].x + 20} cy={POS[s].y - 20} r={6} className="ping" />
          ))}
        </g>;
      })}
      {Object.entries(POS).map(([code, p]) => {
        const a = agent(code);
        const busy = talking.some(({ item }) => item.from === code || item.to === code);
        return (
          <g key={code} className={`node ${busy ? "busy" : ""} ${focusOwner === code ? "focus" : ""}`}
             transform={`translate(${p.x},${p.y})`} onClick={() => onFocusOwner(focusOwner === code ? null : code)}>
            <circle r={22} fill={a.color} />
            <text y={4} textAnchor="middle" className="node-initial">{a.initial}</text>
            <text y={38} textAnchor="middle" className="node-name">{a.name}</text>
          </g>
        );
      })}
    </svg>
  );
}

function pair(a: string, b: string): string {
  return [a, b].sort().join("|");
}

export type { TimelineItem };
