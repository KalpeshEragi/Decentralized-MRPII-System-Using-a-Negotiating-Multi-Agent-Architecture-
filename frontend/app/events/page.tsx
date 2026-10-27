"use client";
// The event manager (EM-1, EM-2, EM-4): pick an agent → its events (what it publishes, what it receives) → one event's
// story (what it means, what causes it, what each receiver does with it, what follows), its payload, live numbers
// and what would break without it. The event manager assistant explains, checks and guides changes; it never
// changes code. Everything here is read from the backend's event catalogue.

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { agent } from "@/lib/agents";
import { api } from "@/lib/api";

type Subscriber = { agent: string; required: boolean; handler: boolean; reaction: string | null };
type Field = { name: string; required: boolean; type: string };
type EventRow = {
  name: string; publisher: string; description: string; version: number; status: string; decided_in: string;
  notes: string[]; built: boolean; explanation: string; caused_by: string[]; leads_to: string[];
  subscribers: Subscriber[]; payload: Field[];
  stats: { published: number; last_published: string | null; deliveries: Record<string, Record<string, number>> };
};
type AgentRow = { agent: string; publishes: string[]; handles: string[]; planned: string[] };
type Report = Record<"missing_handlers" | "unknown_events" | "retired_handlers" | "not_built" | "deprecated", string[]>;
type Impact = { risk: string; losing_input: { agent: string; reaction: string }[]; chains_stopped: string[];
  caused_by_events: string[]; steps: string[]; alternatives: string[] };
type Turn = { role: "user" | "assistant"; content: string; by?: string; seconds?: number };

const ICON: Record<string, string> = { SALES: "🤝", PLANNING: "📈", INVENTORY: "📦", PURCHASING: "🛒", WAREHOUSE: "🏭",
  HR: "👥", SIMULATOR_CLOCK: "⏱" };
const STATUS_TONE: Record<string, string> = { ACTIVE: "green", DEPRECATED: "amber", RETIRED: "red" };

export default function EventsPage() {
  const [data, setData] = useState<{ events: EventRow[]; agents: AgentRow[]; report: Report } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string>("PLANNING");
  const [eventName, setEventName] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const ask = useRef<(text: string) => void>(() => {});

  useEffect(() => {
    const load = () => api.get<{ events: EventRow[]; agents: AgentRow[]; report: Report }>("/events/catalogue")
      .then((d) => { setData(d); setError(null); }).catch((e) => setError((e as Error).message));
    load();
    const timer = setInterval(load, 8000);
    return () => clearInterval(timer);
  }, []);

  const byName = useMemo(() => Object.fromEntries((data?.events ?? []).map((e) => [e.name, e])), [data]);
  const current = eventName ? byName[eventName] : null;
  const problems = data ? [...data.report.missing_handlers, ...data.report.unknown_events, ...data.report.retired_handlers] : [];
  const open = (name: string) => { if (byName[name]) setEventName(name); };

  return (
    <div className="em">
      <header className="em-head">
        <Link href="/" className="btn">‹ Factory</Link>
        <h2>📡 Event manager</h2>
        {data && <span className={`badge big ${problems.length ? "red" : "green"}`}>
          {problems.length ? `${problems.length} wiring problem${problems.length > 1 ? "s" : ""}` : "All events wired"}</span>}
        {data && <span className="muted">{data.events.length} events · {data.events.filter((e) => e.built).length} built</span>}
        <div className="spacer" />
        <button className={`btn ${chatOpen ? "primary" : ""}`} onClick={() => setChatOpen(!chatOpen)}>💬 Ask the event manager</button>
      </header>
      {error && <div className="notice risk">{error}</div>}
      {problems.map((p) => <div key={p} className="notice risk left">{p}</div>)}
      {!data ? <p className="muted pad">Loading the catalogue…</p> : (
        <div className={`em-cols ${chatOpen ? "with-chat" : ""}`}>
          <AgentList agents={data.agents} picked={picked} onPick={(a) => { setPicked(a); setEventName(null); }} />
          <EventList agentRow={data.agents.find((a) => a.agent === picked)!} byName={byName} picked={eventName} onPick={open} />
          <section className="em-detail card">
            {current ? <EventDetail e={current} byName={byName} onOpen={open}
                                    onAsk={(q) => { setChatOpen(true); ask.current(q); }} />
              : <div className="em-empty">
                  <h3>{ICON[picked]} {agent(picked).name}</h3>
                  <p className="muted">Pick an event to see what it means, who causes it, what every receiver does with it and
                    what would break without it.</p>
                  {data.report.not_built.map((n) => <p key={n} className="muted">Not built yet: {n}</p>)}
                </div>}
          </section>
          {chatOpen && <Assistant focus={eventName} register={(fn) => { ask.current = fn; }} />}
        </div>
      )}
    </div>
  );
}

function AgentList({ agents, picked, onPick }: { agents: AgentRow[]; picked: string; onPick: (a: string) => void }) {
  return (
    <nav className="em-agents card">
      <h4>Agents</h4>
      {agents.map((a) => (
        <button key={a.agent} className={`em-agent ${picked === a.agent ? "on" : ""}`} onClick={() => onPick(a.agent)}
                style={{ borderLeftColor: agent(a.agent).color }}>
          <span className="em-agent-name">{ICON[a.agent]} {agent(a.agent).name}</span>
          <small>publishes {a.publishes.length} · receives {a.handles.length}{a.planned.length ? ` · planned ${a.planned.length}` : ""}</small>
        </button>
      ))}
    </nav>
  );
}

function EventList({ agentRow, byName, picked, onPick }: {
  agentRow: AgentRow; byName: Record<string, EventRow>; picked: string | null; onPick: (n: string) => void;
}) {
  const group = (title: string, names: string[], hint: string) => names.length > 0 && (
    <div className="em-group">
      <h5>{title} <span className="muted">{hint}</span></h5>
      {names.map((n) => {
        const e = byName[n];
        return (
          <button key={n} className={`em-event ${picked === n ? "on" : ""}`} onClick={() => onPick(n)}>
            <span className="em-event-top"><b>{n}</b>
              <span className={`badge ${e?.built ? STATUS_TONE[e.status] ?? "" : ""}`}>{e?.built ? e.status.toLowerCase() : "not built"}</span>
            </span>
            <small className="muted">{e?.description}</small>
            {e && e.stats.published > 0 && <small>{e.stats.published} published</small>}
          </button>
        );
      })}
    </div>
  );
  return (
    <section className="em-events card">
      <h4>{ICON[agentRow.agent]} {agent(agentRow.agent).name}'s events</h4>
      {group("Publishes", agentRow.publishes, "facts this agent announces")}
      {group("Receives", agentRow.handles, "and reacts to")}
      {group("Listed, not handled yet", agentRow.planned, "in the design, no handler")}
    </section>
  );
}

function EventDetail({ e, byName, onOpen, onAsk }: {
  e: EventRow; byName: Record<string, EventRow>; onOpen: (n: string) => void; onAsk: (q: string) => void;
}) {
  const [impact, setImpact] = useState<Impact | null>(null);
  useEffect(() => setImpact(null), [e.name]);
  const chip = (name: string) => byName[name]
    ? <button key={name} className="chip on link" onClick={() => onOpen(name)}>{name}</button>
    : <span key={name} className="chip optional">{name}</span>;
  return (
    <div className="em-story">
      <div className="em-title">
        <h3>{e.name}</h3>
        <span className={`badge ${e.built ? STATUS_TONE[e.status] ?? "" : ""}`}>{e.built ? e.status : "NOT BUILT"}</span>
        <span className="muted">v{e.version} · decided in {e.decided_in || "–"}</span>
      </div>
      <p className="em-explain">{e.explanation}</p>

      <div className="em-flow">
        <div className="em-flow-col"><small>Caused by</small>{e.caused_by.length ? e.caused_by.map(chip) : <span className="muted">–</span>}</div>
        <div className="em-flow-arrow">→</div>
        <div className="em-flow-col center"><small>Published by</small>
          <span className="chip on" style={{ borderColor: agent(e.publisher).color, color: agent(e.publisher).color }}>
            {ICON[e.publisher]} {agent(e.publisher).name}</span>
          <b className="em-flow-name">{e.name}</b></div>
        <div className="em-flow-arrow">→</div>
        <div className="em-flow-col"><small>Leads to</small>{e.leads_to.length ? e.leads_to.map(chip) : <span className="muted">–</span>}</div>
      </div>

      <h4>Who receives it and what they do</h4>
      {e.subscribers.map((s) => (
        <div key={s.agent} className={`em-receiver ${s.handler ? "" : s.required ? "missing" : "planned"}`}
             style={{ borderLeftColor: agent(s.agent).color }}>
          <b>{ICON[s.agent]} {agent(s.agent).name}</b>
          <span className="muted">{s.handler ? (s.required ? "required" : "handles it") : s.required ? "required — NO HANDLER" : "listed, not handled yet"}</span>
          <p>{s.reaction ?? "Does nothing with it yet (in the design for later)."}</p>
        </div>
      ))}

      <h4>What it carries</h4>
      {e.payload.length ? (
        <table className="grid"><thead><tr><th>Field</th><th>Type</th><th>Required</th></tr></thead>
          <tbody>{e.payload.map((f) => <tr key={f.name}><td><code>{f.name}</code></td><td>{f.type}</td><td>{f.required ? "yes" : "no"}</td></tr>)}</tbody>
        </table>) : <p className="muted">No payload definition yet: {e.notes.join("; ") || "not built"}.</p>}

      <h4>Live</h4>
      <p className="muted">{e.stats.published} published{e.stats.last_published ? `, last at ${e.stats.last_published.slice(11, 19)}` : ""}.</p>
      {Object.keys(e.stats.deliveries).length > 0 && (
        <table className="grid"><thead><tr><th>Delivered to</th><th>Done</th><th>Waiting</th><th>Failed</th><th>Stale (ignored)</th></tr></thead>
          <tbody>{Object.entries(e.stats.deliveries).map(([who, s]) => (
            <tr key={who}><td>{agent(who).name}</td><td>{s.DONE ?? 0}</td><td>{(s.PENDING ?? 0) + (s.RUNNING ?? 0)}</td>
              <td className={s.FAILED ? "red" : ""}>{s.FAILED ?? 0}</td><td>{s.IGNORED_STALE ?? 0}</td></tr>))}</tbody></table>)}

      <h4>Changing or removing it</h4>
      <div className="em-actions">
        <button className="btn" onClick={() => api.get<Impact>(`/events/${e.name}/impact`).then(setImpact)}>⚠ What breaks if I remove it?</button>
        <button className="btn" onClick={() => onAsk(`Explain ${e.name}: why does it exist and what depends on it?`)}>💬 Explain it to me</button>
        <button className="btn" onClick={() => onAsk(`I want to change the payload of ${e.name}. What should I watch out for?`)}>💬 Change its payload</button>
      </div>
      {impact && (
        <div className={`em-impact ${impact.risk}`}>
          <b>Removing it: {impact.risk} risk</b>
          {impact.losing_input.length > 0 && <ul>{impact.losing_input.map((l) => <li key={l.agent}><b>{agent(l.agent).name}</b> loses: {l.reaction}</li>)}</ul>}
          {impact.chains_stopped.length > 0 && <p>These would no longer happen: {impact.chains_stopped.join(", ")}.</p>}
          <p><b>Safe way:</b></p>
          <ol>{impact.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
          <p><b>Alternatives:</b> {impact.alternatives.join(" ")}</p>
        </div>
      )}
    </div>
  );
}

function Assistant({ focus, register }: { focus: string | null; register: (fn: (text: string) => void) => void }) {
  const [turns, setTurns] = useState<Turn[]>([{ role: "assistant", content:
    "Hi, I'm the event manager. Ask me what an event does, what depends on it, or tell me about an event you want to add, " +
    "change or remove — I'll check it against the catalogue and tell you the safe way (or a better alternative)." }]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const body = useRef<HTMLDivElement>(null);

  const send = async (message: string) => {
    if (!message.trim() || busy) return;
    const history = turns.filter((t, i) => i > 0).map(({ role, content }) => ({ role, content }));
    setTurns((t) => [...t, { role: "user", content: message }]);
    setText("");
    setBusy(true);
    try {
      const r = await api.post<{ answer: string; by: string; seconds: number }>(
        "/events/assistant", { message, history, focus }, 150_000);
      setTurns((t) => [...t, { role: "assistant", content: r.answer, by: r.by, seconds: r.seconds }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "assistant", content: `Sorry, I could not answer: ${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  };
  register(send);
  useEffect(() => { body.current?.scrollTo(0, body.current.scrollHeight); }, [turns, busy]);

  const examples = [
    focus ? `What breaks if I remove ${focus}?` : "Which events does Planning depend on?",
    "I need an event when an item falls below its target stock. Inventory publishes it, Planning and Purchasing react.",
    "Why is SupplierQuantityReduced not built, and what would it take?",
  ];
  return (
    <aside className="em-chat card">
      <h4>💬 Event manager {focus && <span className="muted">· about {focus}</span>}</h4>
      <div className="em-chat-body" ref={body}>
        {turns.map((t, i) => (
          <div key={i} className={`em-msg ${t.role}`}>
            <div className="em-bubble">{t.content}</div>
            {t.by && <small className="muted">{t.by === "MODEL" ? `thought for ${t.seconds}s` : "from the checks (model unavailable)"}</small>}
          </div>
        ))}
        {busy && <div className="em-msg assistant"><div className="em-bubble muted">Thinking… (local model, up to a minute)</div></div>}
      </div>
      <div className="em-examples">{examples.map((q) => <button key={q} className="chip link" onClick={() => send(q)} disabled={busy}>{q}</button>)}</div>
      <form className="em-input" onSubmit={(ev) => { ev.preventDefault(); send(text); }}>
        <textarea value={text} onChange={(ev) => setText(ev.target.value)} placeholder="Ask about an event, or describe one you want…"
                  onKeyDown={(ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(text); } }} rows={2} />
        <button className="btn primary" disabled={busy || !text.trim()}>Send</button>
      </form>
    </aside>
  );
}
