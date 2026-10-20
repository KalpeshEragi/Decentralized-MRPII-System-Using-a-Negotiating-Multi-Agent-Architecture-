"use client";
// The agent conversation (FE-4): every negotiation message as a chat between two agents, every published event and
// trigger as a notice. Collapsible, widenable, filterable by case. Read from the observer timeline only.

import { useEffect, useMemo, useRef, useState } from "react";
import type { TimelineItem } from "@/lib/api";
import { agent, describeEvent, describeTerms, readable } from "@/lib/agents";

type Filter = "all" | "negotiations" | "events";
const QUIET_EVENTS = new Set(["SimulatedDayStarted"]);

export function AgentChat({ items, focusCase, onFocusCase, names }: {
  items: TimelineItem[]; focusCase: string | null; onFocusCase: (caseId: string | null) => void;
  names: Record<string, string>;  // item id -> SKU, to show names instead of ids
}) {
  const [open, setOpen] = useState(true);
  const [wide, setWide] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const body = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const shown = useMemo(() => items.filter((item) => {
    if (item.source === "ai_call") return false;
    if (focusCase && item.case_id !== focusCase && item.correlation_id !== focusCase) return false;
    if (filter === "negotiations") return item.source === "negotiation";
    if (filter === "events") return item.source !== "negotiation";
    return !(item.source === "event" && QUIET_EVENTS.has(item.type ?? "") && focusCase);
  }).slice(-400), [items, filter, focusCase]);

  useEffect(() => {
    if (stick.current && body.current) body.current.scrollTop = body.current.scrollHeight;
  }, [shown.length]);

  return (
    <aside className={`chat ${open ? "" : "closed"} ${wide ? "wide" : ""}`}>
      <div className="chat-head">
        <button className="btn" title={open ? "Minimise" : "Open the agent conversation"} onClick={() => setOpen(!open)}>
          {open ? "›" : "💬"}
        </button>
        <h4>Agent conversation</h4>
        <button className="btn" title={wide ? "Narrow" : "Widen"} onClick={() => setWide(!wide)}>{wide ? "⇥" : "⇤"}</button>
      </div>
      <div className="chat-filter">
        {(["all", "negotiations", "events"] as Filter[]).map((f) => (
          <button key={f} className={`tab ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>{f}</button>
        ))}
        {focusCase && <button className="tab on" onClick={() => onFocusCase(null)}>case {focusCase.slice(0, 12)} ✕</button>}
      </div>
      <div className="chat-body" ref={body}
           onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}>
        {shown.length === 0 && <div className="notice">Nothing yet. Start a scenario and press Play.</div>}
        {shown.map((item, i) => <Line key={`${item.time}-${i}`} item={item} names={names} onFocusCase={onFocusCase} />)}
      </div>
    </aside>
  );
}

function Line({ item, names, onFocusCase }: {
  item: TimelineItem; names: Record<string, string>; onFocusCase: (caseId: string) => void;
}) {
  if (item.source === "negotiation") {
    const from = agent(item.from), to = agent(item.to);
    return (
      <div className="msg">
        <div className="avatar" style={{ background: from.color }}>{from.initial}</div>
        <div className="bubble">
          <div className="who"><b>{from.name}</b> → {to.name} · <span className="badge blue">{item.type}</span>
            {item.case_id && <> · <a href="#" onClick={(e) => { e.preventDefault(); onFocusCase(item.case_id!); }}>case</a></>}
          </div>
          {item.text && <div>{readable(item.text, names)}</div>}
          {item.terms && <div className="terms">{describeTerms(item.terms, names)}</div>}
          {item.reason_code && <div className="terms" style={{ color: "var(--red)" }}>reason: {item.reason_code}</div>}
        </div>
      </div>
    );
  }
  if (item.source === "trigger") {
    return <div className="notice trigger">⚡ Trigger <b>{item.type}</b> {item.status === "FAILED" ? "(refused)" : ""}</div>;
  }
  if (item.source === "failed_work") {
    return <div className="notice risk">⚠ Work failed in {item.queue}: {item.error?.slice(0, 120)}</div>;
  }
  const publisher = agent(item.publisher);
  const risky = item.type === "PlanAtRisk" || item.type === "PlanCommitFailed" || item.type === "SupplierDeliveryDelayed";
  return (
    <div className={`notice ${risky ? "risk" : ""}`}>
      📣 <b style={{ color: publisher.color }}>{publisher.name}</b> published: {describeEvent(item)}
    </div>
  );
}
