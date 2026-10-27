"use client";
// The rule editor (RE-1, RE-6): the factory's business rules by owner — General and one tab per agent. Each rule shows
// what it changes, its value with unit, the default and the safe bounds; change or reset it. Your values form a rule
// profile that survives scenario starts. System settings (simulator, AI plumbing) are never shown here.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Rule = {
  key: string; owner: string; label: string; description: string; kind: string; unit: string; min: string; max: string;
  whole: boolean; in_use: boolean; decided_in: string; value: number | string; default: number | string; changed: boolean;
  personalised: boolean; last_change: { by: string; at: string; from: unknown; to: unknown; note: string | null } | null;
};
type Group = { owner: string; label: string; rules: Rule[] };
type Change = { key: string; label: string; from: unknown; to: unknown; action: string; by: string; note: string | null; at: string };

const ICON: Record<string, string> = { GENERAL: "⚙", SALES: "🤝", PLANNING: "📈", INVENTORY: "📦", PURCHASING: "🛒",
  WAREHOUSE: "🏭", HR: "👥" };
const COMING: Record<string, string> = {
  INVENTORY: "Next: per-item rules — safety stock, target stock level (% of max) and maximum stock per item.",
  WAREHOUSE: "Next: receiving and shipping per day and zone capacities (today changed by the capacity trigger).",
};

/** A percent rule is stored as a share (0.5) and shown as 50 %. */
const shown = (r: Rule, v: unknown) => r.kind === "percent" ? `${+(Number(v) * 100).toFixed(2)}` : String(v);
const stored = (r: Rule, text: string) => r.kind === "percent" ? String(Number(text) / 100) : text;
const withUnit = (r: Rule, v: unknown) => `${shown(r, v)} ${r.unit}`;

export default function RulesPage() {
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [hidden, setHidden] = useState(0);
  const [tab, setTab] = useState("GENERAL");
  const [history, setHistory] = useState<Change[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.get<{ groups: Group[]; hidden_system_settings: number }>("/rules")
      .then((d) => { setGroups(d.groups); setHidden(d.hidden_system_settings); setError(null); })
      .catch((e) => setError((e as Error).message));
    api.get<Change[]>("/rules/history").then(setHistory).catch(() => setHistory([]));
  }, []);
  useEffect(load, [load]);

  const group = groups?.find((g) => g.owner === tab);
  const personalised = groups?.flatMap((g) => g.rules).filter((r) => r.changed).length ?? 0;
  return (
    <div className="em rules">
      <header className="em-head">
        <Link href="/" className="btn">‹ Factory</Link>
        <h2>⚙ Rules</h2>
        <span className="muted">The factory's business rules. Your changes apply from the next decision and survive scenario restarts.</span>
        <div className="spacer" />
        {groups && <span className={`badge big ${personalised ? "blue" : ""}`}>{personalised} personalised</span>}
      </header>
      {error && <div className="notice risk">{error}</div>}
      {!groups ? <p className="muted pad">Loading rules…</p> : (
        <div className="rules-cols">
          <nav className="em-agents card">
            <h4>Owner</h4>
            {groups.map((g) => (
              <button key={g.owner} className={`em-agent ${tab === g.owner ? "on" : ""}`} onClick={() => setTab(g.owner)}>
                <span className="em-agent-name">{ICON[g.owner]} {g.label}</span>
                <small>{g.rules.length} rule{g.rules.length === 1 ? "" : "s"}{g.rules.some((r) => r.changed)
                  ? ` · ${g.rules.filter((r) => r.changed).length} changed` : ""}</small>
              </button>
            ))}
            <p className="muted small-note">{hidden} system settings (simulator, AI, seeds) are not shown: the system needs them as they are.</p>
          </nav>
          <section className="rules-list">
            <h3>{ICON[tab]} {group?.label} rules</h3>
            {group?.rules.length === 0 && <p className="muted">No business rules of this agent yet.</p>}
            {group?.rules.map((r) => <RuleCard key={r.key} rule={r} onChanged={load} />)}
            {COMING[tab] && <div className="notice left">{COMING[tab]}</div>}
          </section>
          <aside className="em-chat card rules-history">
            <h4>History</h4>
            {history.length === 0 && <p className="muted">No changes yet.</p>}
            {history.map((c, i) => (
              <div key={i} className="history-row">
                <b>{c.label}</b> <span className="muted">{c.action === "RESET" ? "reset" : "changed"} {String(c.from)} → {String(c.to)}</span>
                <small className="muted">{c.at.slice(0, 16).replace("T", " ")} · {c.by}{c.note ? ` · ${c.note}` : ""}</small>
              </div>
            ))}
          </aside>
        </div>
      )}
    </div>
  );
}

function RuleCard({ rule, onChanged }: { rule: Rule; onChanged: () => void }) {
  const [text, setText] = useState(shown(rule, rule.value));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => setText(shown(rule, rule.value)), [rule.value, rule.kind]);

  const dirty = text.trim() !== shown(rule, rule.value);
  async function save() {
    setBusy(true); setMessage(null);
    try {
      await api.put(`/rules/${rule.key}`, { value: stored(rule, text.trim()), note: note || null });
      setMessage({ ok: true, text: "Saved. Agents use it from their next decision." }); setNote(""); onChanged();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : String(e) });
    } finally { setBusy(false); }
  }
  async function reset() {
    setBusy(true); setMessage(null);
    try { await api.del(`/rules/${rule.key}`); setMessage({ ok: true, text: "Back to the default." }); onChanged(); }
    catch (e) { setMessage({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }
  return (
    <div className={`card rule-card ${rule.changed ? "changed" : ""} ${rule.in_use ? "" : "unused"}`}>
      <div className="rule-head">
        <b>{rule.label}</b>
        {rule.changed && <span className="badge blue">personalised</span>}
        {!rule.in_use && <span className="badge">not used yet</span>}
        <span className="muted rule-decided">{rule.decided_in}</span>
      </div>
      <p className="rule-desc">{rule.description}</p>
      <div className="rule-edit">
        <input className="btn field" type="number" value={text} disabled={!rule.in_use || busy}
               step={rule.whole && rule.kind !== "percent" ? 1 : "any"}
               min={shown(rule, rule.min)} max={shown(rule, rule.max)} onChange={(e) => setText(e.target.value)} />
        <span className="rule-unit">{rule.unit}</span>
        {dirty && <input className="btn field note" placeholder="why? (optional)" value={note} onChange={(e) => setNote(e.target.value)} />}
        <button className="btn primary" disabled={!dirty || busy || !rule.in_use} onClick={save}>Save</button>
        <button className="btn" disabled={!rule.changed || busy} onClick={reset}>Reset</button>
      </div>
      <small className="muted">Default {withUnit(rule, rule.default)} · allowed {withUnit(rule, rule.min)} to {withUnit(rule, rule.max)}
        {rule.last_change && ` · last changed ${rule.last_change.at.slice(0, 16).replace("T", " ")} by ${rule.last_change.by}`}</small>
      {message && <div className={`badge ${message.ok ? "green" : "red"} result`}>{message.text}</div>}
    </div>
  );
}
