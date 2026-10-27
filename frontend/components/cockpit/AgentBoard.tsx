"use client";
// The six agents at a glance: what each is doing now, what it waits for, and its latest action. Status words are
// derived from the live snapshot (open negotiations, its own work queue) and the published facts — see insight.ts.

import { agent, describeEvent, describeTerms } from "@/lib/agents";
import type { TimelineItem } from "@/lib/api";
import { AgentCode, AgentStatus, AgentView, STATUS_HELP } from "@/lib/insight";

export const ICON: Record<AgentCode, string> = {
  SALES: "🤝", PLANNING: "📈", INVENTORY: "📦", PURCHASING: "🛒", WAREHOUSE: "🏭", HR: "👥",
};

const TONE: Record<AgentStatus, string> = { IDLE: "", WORKING: "blue", WAITING: "amber", NEGOTIATING: "blue", ALERT: "red" };
const WORD: Record<AgentStatus, string> = {
  IDLE: "Idle", WORKING: "Working", WAITING: "Waiting", NEGOTIATING: "Negotiating", ALERT: "Alert",
};

export function AgentBoard({ views, involved, onOpen }: {
  views: AgentView[]; involved: Partial<Record<AgentCode, "origin" | "involved">>; onOpen: (code: AgentCode) => void;
}) {
  return (
    <div className="agent-board">
      {views.map((v) => {
        const a = agent(v.code);
        const mark = involved[v.code];
        return (
          <button key={v.code} className={`card agent-card ${mark ?? ""}`} onClick={() => onOpen(v.code)}
                  style={{ borderLeftColor: a.color }} title="Open this agent's details">
            <div className="agent-card-head">
              <span className="agent-icon">{ICON[v.code]}</span>
              <b>{a.name}</b>
              {mark && <span className="badge red" title="Took part in the latest disruption">
                {mark === "origin" ? "⚡ source" : "⚡ involved"}</span>}
              <span className={`badge ${TONE[v.status]}`} title={STATUS_HELP[v.status]}>{WORD[v.status]}</span>
            </div>
            <div className="agent-now">{nowLine(v)}</div>
            {v.latest && <div className="agent-latest">Latest: {summarize(v.latest)}</div>}
          </button>
        );
      })}
    </div>
  );
}

function nowLine(v: AgentView): string {
  const names = (codes: string[]) => [...new Set(codes)].map((c) => agent(c).name).join(", ");
  if (v.answering.length) return `Answering ${names(v.answering)} (${v.answering.length} open)`;
  if (v.waitingFor.length) return `Waiting for ${names(v.waitingFor)}`;
  if (v.queued) return `${v.queued} task${v.queued > 1 ? "s" : ""} in its queue`;
  if (v.alert) return v.alert;
  return "Nothing open";
}

/** One timeline line in a few words. */
export function summarize(item: TimelineItem): string {
  if (item.source === "event") return describeEvent(item);
  if (item.source === "negotiation") {
    const what = item.resource_label ? `${item.resource_label} ` : "";
    return `${(item.type ?? "").replaceAll("_", " ").toLowerCase()} ${agent(item.from).name} → ${agent(item.to).name}`
      + (item.terms ? ` · ${what}${describeTerms(item.terms)}` : "") + (item.order_label ? ` (${item.order_label})` : "");
  }
  return item.type ?? item.source;
}
