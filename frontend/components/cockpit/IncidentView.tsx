"use client";
// Every disruption as one story: BEFORE (the fact that changed, from the owner's own event), DURING (the agents that
// published or negotiated afterwards, with the real negotiation threads) and AFTER (what Planning published, and what
// is still open). "Afterwards" means until the next disruption; an outcome is marked "linked" only when its ids match
// the disruption's own ids, otherwise it is shown as following it in time.

import { useState } from "react";
import { agent } from "@/lib/agents";
import type { TimelineItem } from "@/lib/api";
import { describeDisruption, explainChange, Incident } from "@/lib/insight";
import { NegotiationThread, toEntries } from "@/components/NegotiationThread";
import { ICON, summarize } from "./AgentBoard";

export function IncidentView({ incidents, names, onClose, onOpenStory }: {
  incidents: Incident[]; names: Record<string, string>; onClose: () => void; onOpenStory: (demandId: string) => void;
}) {
  const [picked, setPicked] = useState<number>(incidents.length);  // newest first
  const current = incidents.find((i) => i.index === picked) ?? incidents[incidents.length - 1];

  return (
    <div className="overlay card">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <h3>🚨 Disruptions and how the agents responded</h3>
      {incidents.length === 0 ? (
        <p className="muted">No disruption yet. Use ⚡ Disruption in the top bar (or a scenario such as S2 or S5) and advance the day.</p>
      ) : <div className="incident-layout">
        <nav className="incident-list">
          {[...incidents].reverse().map((i) => (
            <button key={i.index} className={`tab block ${i === current ? "on" : ""}`} onClick={() => setPicked(i.index)}>
              <b>#{i.index} {ICON[i.origin]} {i.event.type?.replace(/([a-z])([A-Z])/g, "$1 $2")}</b>
              <small>{i.event.time.slice(11, 19)} · {i.unresolved.length ? `${i.unresolved.length} still open` : `${i.planOutcomes.length} plan outcome${i.planOutcomes.length === 1 ? "" : "s"}`}</small>
            </button>
          ))}
        </nav>
        {current && <IncidentStory incident={current} names={names} onOpenStory={onOpenStory} />}
      </div>}
    </div>
  );
}

function IncidentStory({ incident, names, onOpenStory }: {
  incident: Incident; names: Record<string, string>; onOpenStory: (demandId: string) => void;
}) {
  const { event } = incident;
  const threads = toEntries(incident.after.filter((x) => x.source === "negotiation"));
  const facts = incident.after.filter((x) => x.source === "event" && !incident.planOutcomes.includes(x));
  return (
    <div className="incident-story">
      <div className="phase before">
        <h4>BEFORE → the fact that changed</h4>
        <p><b style={{ color: agent(incident.origin).color }}>{agent(incident.origin).name}</b> published{" "}
          <code>{event.type}</code> at {event.time.slice(11, 19)}.</p>
        <p className="big-line">{describeDisruption(event, names)}</p>
        <Details item={event} />
      </div>

      <div className="phase during">
        <h4>DURING → who reacted</h4>
        <div className="chips">{incident.agents.map((c) => (
          <span key={c} className="badge" style={{ background: `${agent(c).color}22`, color: agent(c).color }}>
            {ICON[c]} {agent(c).name}{c === incident.origin ? " (source)" : ""}</span>))}</div>
        {threads.length === 0 && facts.length === 0 && <p className="muted">No agent has acted on it yet. Advance the day or wait for the agents.</p>}
        {threads.map((e) => e.kind === "thread" && <NegotiationThread key={e.session} steps={e.steps} />)}
        {facts.length > 0 && <div className="activity">{facts.slice(0, 30).map((f, i) =>
          <div key={i} className="notice left"><span className="time">{f.time.slice(11, 19)}</span> 📣 {agent(f.publisher).name}: {summarize(f)}</div>)}</div>}
      </div>

      <div className="phase after">
        <h4>AFTER → what changed in the plan</h4>
        {incident.planOutcomes.length === 0
          ? <p className="muted">Planning published no plan change after this disruption{incident.unresolved.length ? " yet" : ""}. If the absence or delay was fully absorbed by its owner, the plan stays as it was.</p>
          : incident.planOutcomes.map((p, i) => {
            const c = explainChange(p);
            return (
              <div key={i} className={`change ${c.tone}`}>
                <div><b>{String(p.payload?.order_number ?? "order")}</b> · {p.type}
                  {incident.linked.has(p) ? <span className="badge green" title="Its ids match the disruption's own ids">linked</span>
                    : <span className="badge" title="Happened after this disruption; no shared id proves the link">followed</span>}
                  <button className="btn small" onClick={() => onOpenStory(String(p.payload?.demand_id))}>Why? →</button></div>
                <div>{c.text}</div>
              </div>);
          })}
        {incident.unresolved.length > 0
          ? <p className="badge red">⏳ {incident.unresolved.length} negotiation{incident.unresolved.length > 1 ? "s" : ""} still open — not resolved yet</p>
          : incident.sessions.length > 0 && <p className="badge green">All {incident.sessions.length} negotiations finished</p>}
      </div>
    </div>
  );
}

function Details({ item }: { item: TimelineItem }) {
  return (
    <details className="tech"><summary>Technical record</summary>
      <pre>{JSON.stringify({ type: item.type, publisher: item.publisher, subscribers: item.subscribers,
        correlation_id: item.correlation_id, payload: item.payload }, null, 2)}</pre>
    </details>
  );
}
