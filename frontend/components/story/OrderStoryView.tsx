"use client";
// One order's whole story on one screen (FE-4): the plan tree (left), the six agents talking about it (right, live),
// the negotiation picked in the tree, and what happened in order: rounds of planning, events, disruptions. A
// disruption can be fired against this order's own resources; the agents then decide how to react, round by round.

import { useMemo, useState } from "react";
import { api, Live, OrderStory, TimelineItem, TriggerResult } from "@/lib/api";
import { agent, describeEvent } from "@/lib/agents";
import { useOrderStory } from "@/lib/useOrderStory";
import { NegotiationThread } from "@/components/NegotiationThread";
import { AgentNetwork } from "./AgentNetwork";
import { PlanTree, qty, tone } from "./PlanTree";
import { useArrivals } from "./useArrivals";

const ROUND: Record<string, string> = { NEW_REQUEST: "First plan", CHANGE: "Customer change", REPAIR: "Repair after disruption" };

export function OrderStoryView({ demandId, live, items, onClose }: {
  demandId: string; live: Live | null; items: TimelineItem[]; onClose: () => void;
}) {
  const story = useOrderStory(demandId, items.length);
  const [pickedCase, setPickedCase] = useState<string | null>(null);  // null: always the newest round
  const [selected, setSelected] = useState<string | null>(null);
  const [focusOwner, setFocusOwner] = useState<string | null>(null);

  const refs = useMemo(() => new Set(story?.refs ?? []), [story]);
  const mine = useMemo(() => items.filter((i) => i.source !== "ai_call"
    && [i.case_id, i.correlation_id, i.session_id].some((id) => id && refs.has(id))), [items, refs]);
  const arrivals = useArrivals(mine);

  if (!story) return <div className="story card"><div className="notice">Loading the order…</div></div>;

  const cases = [...story.cases].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
  const current = pickedCase ?? cases[cases.length - 1]?.case_id ?? null;
  const roundNegotiations = story.negotiations.filter((n) => n.case_id === current);
  const steps = selected ? mine.filter((i) => i.session_id === selected) : [];
  const plan = story.plan;

  return (
    <div className="story card">
      <header className="story-head">
        <div>
          <h3>📖 {plan.order_number ? `Order ${plan.order_number}` : "Customer request"} · {qty(plan.quantity)} {plan.sku}</h3>
          <div className="muted">
            Requested by {plan.requested_day} · promised {plan.committed_day ?? "–"} ·
            customer: <b>{story.sales?.stage?.toLowerCase().replaceAll("_", " ") ?? "–"}</b> ·
            plan: <span className={`badge ${tone(plan.status)}`}>{plan.status.toLowerCase()}</span>
          </div>
        </div>
        <DisruptMenu story={story} live={live} />
        <button className="btn" onClick={onClose} title="Close">✕</button>
      </header>

      <div className="rounds">
        {cases.map((c, i) => (
          <button key={c.case_id} className={`tab ${c.case_id === current ? "on" : ""}`}
                  onClick={() => { setPickedCase(i === cases.length - 1 ? null : c.case_id); setSelected(null); }}>
            Round {i + 1}: {ROUND[c.kind] ?? c.kind.toLowerCase()} <span className={`dot ${tone(c.status)}`} />
            <span className="muted"> {c.created_at?.slice(11, 16)}</span>
          </button>
        ))}
        {cases.length === 0 && <span className="muted">Planning has not opened a round for this order yet.</span>}
      </div>

      <div className="story-grid">
        <section>
          <h4>Plan — who was asked for what</h4>
          <PlanTree story={story} negotiations={roundNegotiations} selected={selected}
                    onSelect={(s) => setSelected(selected === s ? null : s)} focusOwner={focusOwner} />
        </section>
        <section>
          <h4>Agents talking {focusOwner && <a href="#" onClick={(e) => { e.preventDefault(); setFocusOwner(null); }}>
            (only {agent(focusOwner).name} ✕)</a>}</h4>
          <AgentNetwork negotiations={roundNegotiations} arrivals={arrivals} focusOwner={focusOwner}
                        onFocusOwner={setFocusOwner} />
          <div className="legend muted">
            <span><i className="lg open" /> negotiating</span><span><i className="lg done" /> agreed</span>
            <span><i className="lg failed" /> failed</span><span>◎ published</span><span>● subscriber notified</span>
          </div>
          {steps.length > 0 ? <NegotiationThread steps={steps} />
            : <div className="notice">Click a line of the plan to see its negotiation.</div>}
        </section>
        <section>
          <h4>What happened</h4>
          <StoryFeed story={story} items={items} mine={mine} />
        </section>
      </div>
    </div>
  );
}

/** Rounds, this order's events and every disruption since the order arrived, oldest first. */
function StoryFeed({ story, items, mine }: { story: OrderStory; items: TimelineItem[]; mine: TimelineItem[] }) {
  const start = story.cases.map((c) => c.created_at ?? "").sort()[0] ?? story.customer?.created_at ?? "";
  const rows = useMemo(() => {
    const out: { time: string; kind: string; node: React.ReactNode }[] = [];
    story.cases.forEach((c) => out.push({ time: c.created_at ?? "", kind: "round",
      node: <>🧭 Planning opened a round: <b>{ROUND[c.kind] ?? c.kind.toLowerCase()}</b></> }));
    mine.filter((i) => i.source === "event").forEach((i) => out.push({ time: i.time, kind: risky(i) ? "risk" : "event",
      node: <>📣 <b style={{ color: agent(i.publisher).color }}>{agent(i.publisher).name}</b> {describeEvent(i)}
        {i.subscribers?.length ? <span className="muted"> → {i.subscribers.map((s) => agent(s).name).join(", ")}</span> : null}</> }));
    items.filter((i) => i.source === "trigger" && i.time >= start).forEach((i) => out.push({ time: i.time,
      kind: "trigger", node: <>⚡ Disruption: <b>{i.type}</b> {i.status === "FAILED" ? "(refused)" : ""}</> }));
    return out.sort((a, b) => a.time.localeCompare(b.time));
  }, [story, items, mine, start]);
  return (
    <ol className="feed">
      {rows.map((r, i) => <li key={i} className={r.kind}><span className="time">{r.time.slice(11, 19)}</span>{r.node}</li>)}
      {rows.length === 0 && <li className="muted">Nothing yet.</li>}
    </ol>
  );
}

function risky(i: TimelineItem): boolean {
  return ["PlanAtRisk", "PlanCommitFailed", "SupplierDeliveryDelayed", "WorkforceCapacityChanged"].includes(i.type ?? "");
}

/** Disruptions aimed at this order's own resources: a worker whose skill it booked, a bought part it uses, or the
 *  customer cancelling or changing it. Fired through the normal simulator door; the agents decide the reaction. */
function DisruptMenu({ story, live }: { story: OrderStory; live: Live | null }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const day = live?.clock.day;
  const offset = (to: string) => day ? Math.max(0, Math.round((Date.parse(to) - Date.parse(day)) / 86400000)) : 1;
  const skills = new Set(story.negotiations.filter((n) => n.resource_type === "WORKFORCE").map((n) => n.resource_ref));
  const firstBuild = story.plan.production_orders.map((o) => o.start_day).sort()[0];
  const workers = (live?.workers ?? []).filter((w) => skills.has(w.primary_skill) && !w.absent);
  const bought = new Set((live?.stock ?? []).filter((s) => s.type === "RAW_MATERIAL").map((s) => s.item_id));
  const parts = [...new Map(story.negotiations.filter((n) => (n.resource_type === "SUPPLY" || n.resource_type === "STOCK") && bought.has(n.resource_ref))
    .map((n) => [n.resource_ref, n.resource_label ?? n.resource_ref])).values()];
  const number = story.plan.order_number;

  const choices: { label: string; kind: string; params: Record<string, unknown> }[] = [
    ...workers.map((w) => ({ label: `👷 ${w.name} (${w.primary_skill}) absent on build day ${firstBuild ?? ""}`,
      kind: "WORKER_ABSENT", params: { worker: w.code, first_day_offset: offset(firstBuild ?? ""),
        last_day_offset: offset(firstBuild ?? "") + 1 } })),
    ...parts.map((sku) => ({ label: `🚚 Supplier of ${sku} 3 days late`, kind: "SUPPLIER_DELAY",
      params: { item_sku: sku, days: 3 } })),
    ...(number ? [
      { label: `✂ Customer halves the quantity`, kind: "CHANGE_ORDER",
        params: { order_number: number, quantity: Math.max(1, Math.round(Number(story.plan.quantity) / 2)) } },
      { label: `✕ Customer cancels`, kind: "CANCEL_ORDER", params: { order_number: number } },
    ] : []),
  ];

  async function fire(kind: string, params: Record<string, unknown>) {
    setNote("Sending…");
    try {
      const fired = await api.post<TriggerResult>("/simulation/triggers", { kind, params });
      setNote(fired.status === "FAILED" ? `Refused: ${String(fired.result?.message ?? "")}` : "Sent. Watch the agents react.");
    } catch (e) {
      setNote((e as Error).message);
    }
    setOpen(false);
  }

  return (
    <div className="disrupt">
      <button className="btn" onClick={() => setOpen(!open)}>⚡ Disrupt this order</button>
      {note && <span className="muted"> {note}</span>}
      {open && (
        <div className="card menu">
          {choices.length === 0 && <div className="muted">Nothing of this order to disrupt yet.</div>}
          {choices.map((c, i) => <button key={i} className="menu-item" onClick={() => fire(c.kind, c.params)}>{c.label}</button>)}
        </div>
      )}
    </div>
  );
}
