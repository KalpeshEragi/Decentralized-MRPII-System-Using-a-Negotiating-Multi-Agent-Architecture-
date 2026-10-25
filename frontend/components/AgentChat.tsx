"use client";
// The agent conversation (FE-4), one window per order: the "All" tab is the whole factory feed; each order tab has
// its own customer chat (customer ↔ Sales) and its own negotiation channel (the agents' private messages and the
// events published for that order). Read from the observer only.

import { useEffect, useMemo, useRef, useState } from "react";
import type { Live, OrderStory, TimelineItem } from "@/lib/api";
import { useOrderStory } from "@/lib/useOrderStory";
import { agent, describeEvent } from "@/lib/agents";
import { NegotiationThread, toEntries } from "@/components/NegotiationThread";

type Filter = "all" | "negotiations" | "events";
type Channel = "customer" | "negotiation";
const QUIET_EVENTS = new Set(["SimulatedDayStarted"]);

export function AgentChat({ live, items, focusOrder, onFocusOrder, onOpenStory, names }: {
  live: Live | null; items: TimelineItem[]; focusOrder: string | null; onFocusOrder: (demandId: string | null) => void;
  onOpenStory: (demandId: string) => void;
  names: Record<string, string>;  // item id -> SKU, to show names instead of ids
}) {
  const [open, setOpen] = useState(true);
  const [wide, setWide] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [channel, setChannel] = useState<Channel>("negotiation");
  const story = useOrderStory(focusOrder, items.length);
  const orders = live?.orders ?? [];

  const refs = useMemo(() => new Set(story?.refs ?? []), [story]);
  const shown = useMemo(() => items.filter((item) => {
    if (item.source === "ai_call") return false;
    if (focusOrder) {
      const mine = [item.case_id, item.correlation_id, item.session_id].some((id) => id && refs.has(id));
      if (!mine || (item.source === "event" && QUIET_EVENTS.has(item.type ?? ""))) return false;
    }
    if (filter === "negotiations") return item.source === "negotiation";
    if (filter === "events") return item.source !== "negotiation";
    return true;
  }).slice(-400), [items, filter, focusOrder, refs]);

  const entries = useMemo(() => toEntries(shown), [shown]);
  const showCustomer = focusOrder && channel === "customer";
  const count = showCustomer ? (story?.customer?.messages.length ?? 0) + (story?.customer?.options.length ?? 0) : shown.length;
  const body = useStickyScroll(count);

  return (
    <aside className={`chat ${open ? "" : "closed"} ${wide ? "wide" : ""}`}>
      <div className="chat-head">
        <button className="btn" title={open ? "Minimise" : "Open the agent conversation"} onClick={() => setOpen(!open)}>
          {open ? "›" : "💬"}
        </button>
        <h4>{focusOrder ? `Order ${orderLabel(orders.find((o) => o.demand_id === focusOrder), focusOrder)}` : "Agent conversation"}</h4>
        {focusOrder && <button className="btn" title="The whole story of this order" onClick={() => onOpenStory(focusOrder)}>📖 Story</button>}
        <button className="btn" title={wide ? "Narrow" : "Widen"} onClick={() => setWide(!wide)}>{wide ? "⇥" : "⇤"}</button>
      </div>
      <div className="chat-orders">
        <button className={`tab ${focusOrder ? "" : "on"}`} onClick={() => onFocusOrder(null)}>All</button>
        {orders.map((o) => (
          <button key={o.demand_id} className={`tab ${focusOrder === o.demand_id ? "on" : ""}`}
                  title={`${o.sku ?? ""} × ${o.quantity} · ${o.status}`} onClick={() => onFocusOrder(o.demand_id)}>
            <span className={`dot ${statusTone(o.status)}`} />{orderLabel(o, o.demand_id)}
          </button>
        ))}
      </div>
      <div className="chat-filter">
        {focusOrder && (["customer", "negotiation"] as Channel[]).map((c) => (
          <button key={c} className={`tab ${channel === c ? "on" : ""}`} onClick={() => setChannel(c)}>
            {c === "customer" ? "👤 Customer ↔ Sales" : "🤝 Agent negotiation"}
          </button>
        ))}
        {!showCustomer && (["all", "negotiations", "events"] as Filter[]).map((f) => (
          <button key={f} className={`tab small ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>{f}</button>
        ))}
      </div>
      <div className="chat-body" ref={body.ref} onScroll={body.onScroll}>
        {showCustomer ? <CustomerChannel story={story} /> : <>
          {shown.length === 0 && <div className="notice">
            {focusOrder ? "No negotiation for this order yet." : "Nothing yet. Start a scenario and press Play."}
          </div>}
          {entries.map((e, i) => e.kind === "thread"
            ? <NegotiationThread key={e.session} steps={e.steps} />
            : <Line key={`${e.item.time}-${i}`} item={e.item} />)}
        </>}
      </div>
    </aside>
  );
}

/** Keep the newest line in view unless the reader scrolled up. */
function useStickyScroll(count: number) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => { if (stick.current && ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [count]);
  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };
  return { ref, onScroll };
}

function orderLabel(order: Live["orders"][number] | undefined, demandId: string): string {
  return order?.order_number ?? `#${demandId.slice(0, 6)}`;
}

function statusTone(status: string): string {
  if (["SHIPPED", "COMPLETED", "COMMITTED"].includes(status)) return "green";
  if (["NOT_FEASIBLE", "CANCELLED", "AT_RISK"].includes(status)) return "red";
  return "amber";
}

/** The customer side of one order: the chat messages if it was a chat customer, otherwise the structured steps
 *  (request → options offered → accepted) told as chat lines. */
function CustomerChannel({ story }: { story: OrderStory | null }) {
  if (!story) return <div className="notice">Loading the order…</div>;
  const c = story.customer;
  if (!c) return <div className="notice">No customer conversation for this order.</div>;
  const sales = agent("SALES");
  const customer = { name: "Customer", color: "#5b6472", initial: "C" };
  return <>
    {c.messages.length > 0 ? c.messages.map((m, i) => {
      const who = m.direction === "IN" ? customer : sales;
      return <Bubble key={i} who={who} right={m.direction === "OUT"} time={m.time}>{m.text}</Bubble>;
    }) : <>
      <Bubble who={customer} time={c.created_at}>
        I need {c.quantity ?? "?"} units{c.requested_date ? ` by ${c.requested_date}` : ""}.
      </Bubble>
      {c.options.length > 0 && (
        <Bubble who={sales} right time={c.options[0].created_at}>
          Planning checked it. Options:
          <ul className="options">{c.options.map((o, i) => (
            <li key={i} className={o.status === "SELECTED" ? "chosen" : ""}>
              {o.kind.toLowerCase().replaceAll("_", " ")}: {o.quantity} by {o.delivery_date}
              {o.status !== "OFFERED" && <span className="badge">{o.status.toLowerCase()}</span>}
            </li>
          ))}</ul>
        </Bubble>
      )}
      {c.confirmed_at && <Bubble who={customer} time={c.confirmed_at}>Yes, I accept.</Bubble>}
    </>}
    <div className="notice">Inquiry stage: <b>{c.stage}</b>{c.closed_reason ? ` (${c.closed_reason})` : ""}
      {story.sales?.order_number && <> · order <b>{story.sales.order_number}</b></>}
      {" "}· plan <b>{story.plan.status}</b></div>
  </>;
}

function Bubble({ who, right, time, children }: {
  who: { name: string; color: string; initial: string }; right?: boolean; time: string; children: React.ReactNode;
}) {
  return (
    <div className={`msg ${right ? "right" : ""}`}>
      <div className="avatar" style={{ background: who.color }}>{who.initial}</div>
      <div className="bubble">
        <div className="who"><b>{who.name}</b> · <span className="time">{time.slice(11, 19)}</span></div>
        <div>{children}</div>
      </div>
    </div>
  );
}

function Line({ item }: { item: TimelineItem }) {
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
