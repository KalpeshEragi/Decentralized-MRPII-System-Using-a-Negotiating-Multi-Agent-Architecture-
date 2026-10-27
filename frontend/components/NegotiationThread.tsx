"use client";
// One private negotiation as one card (FE-4): who talks to whom, about what, for which order, and where it stands.
// Every step line is written here from the message type and its terms (code facts); the AI's sentence for a step is
// only shown on request, under "AI wording".

import { useState } from "react";
import type { TimelineItem } from "@/lib/api";
import { agent } from "@/lib/agents";

const RESOURCE: Record<string, string> = {
  STOCK: "stock", SUPPLY: "supply", WORKFORCE: "worker-hours", STORAGE_SPACE: "storage space",
  RECEIVING_SLOT: "receiving slot", PRODUCTION_CAPACITY: "machine-hours",
};

/** Group a timeline into feed entries: each negotiation session becomes one thread, placed where it started. */
export type Entry = { kind: "item"; item: TimelineItem } | { kind: "thread"; session: string; steps: TimelineItem[] };

export function toEntries(items: TimelineItem[]): Entry[] {
  const entries: Entry[] = [];
  const threads = new Map<string, TimelineItem[]>();
  for (const item of items) {
    if (item.source !== "negotiation" || !item.session_id) { entries.push({ kind: "item", item }); continue; }
    const steps = threads.get(item.session_id);
    if (steps) { steps.push(item); continue; }
    const fresh = [item];
    threads.set(item.session_id, fresh);
    entries.push({ kind: "thread", session: item.session_id, steps: fresh });
  }
  return entries;
}

export function NegotiationThread({ steps }: { steps: TimelineItem[] }) {
  const first = steps[0];
  const asker = agent(first.from), owner = agent(first.to);
  const terms = (first.terms ?? {}) as Record<string, unknown>;
  const status = threadStatus(steps);
  return (
    <div className="thread">
      <div className="thread-head">
        <span className="pair">
          <b style={{ color: asker.color }}>{asker.name}</b> ⇄ <b style={{ color: owner.color }}>{owner.name}</b>
        </span>
        <span className={`badge ${status.tone}`}>{status.label}</span>
      </div>
      <div className="thread-what">
        {amount(terms)} {first.resource_label ?? ""} {RESOURCE[String(terms.resource_type)] ?? ""}
        {first.order_label && <> · for <b>{first.order_label}</b></>}
      </div>
      <ol className="thread-steps">
        {steps.map((step, i) => <Step key={i} step={step} />)}
      </ol>
    </div>
  );
}

function Step({ step }: { step: TimelineItem }) {
  const [showAi, setShowAi] = useState(false);
  const from = agent(step.from);
  const aiText = step.text && !/^(request|offer|accept|commit|reject|counter)[:\s]/i.test(step.text) ? step.text : null;
  return (
    <li>
      <span className="step-dot" style={{ background: from.color }} />
      <span><b>{from.name}</b> {stepLine(step)}</span>
      <span className="time">{step.time.slice(11, 19)}</span>
      {aiText && <button className="ai-toggle" onClick={() => setShowAi(!showAi)}>{showAi ? "hide" : "AI wording"}</button>}
      {showAi && aiText && <div className="ai-text">“{aiText}”</div>}
    </li>
  );
}

function amount(terms: Record<string, unknown>): string {
  if (terms.quantity === undefined) return "";
  const n = Number(terms.quantity);
  return `${Number.isFinite(n) ? n.toLocaleString() : terms.quantity}${terms.unit === "h" ? " h" : ""}`;
}

function when(terms: Record<string, unknown>, key: "needed_by" | "available_from"): string {
  const day = terms[key] ?? terms.date_from;
  return day ? ` ${key === "needed_by" ? "by" : "from"} ${day}` : "";
}

/** The step in plain words, from the message type and its terms only. */
function stepLine(step: TimelineItem): string {
  const t = (step.terms ?? {}) as Record<string, unknown>;
  const reason = step.reason_code ? ` (${step.reason_code.toLowerCase().replaceAll("_", " ")})` : "";
  switch (step.type) {
    case "REQUEST": return `asks for ${amount(t)}${when(t, "needed_by")}`;
    case "OFFER": return `offers ${amount(t)}${when(t, "available_from")}`;
    case "COUNTER_OFFER": return `counter-offers ${amount(t)}${when(t, "available_from")}${reason}`;
    case "ACCEPT": return "accepts the offer";
    case "AGREEMENT_PROPOSED": return `proposes the agreement: ${amount(t)}`;
    case "COMMIT": return "commits it ✓";
    case "REJECT": return `rejects${reason}`;
    case "ABORT": return `withdraws${reason}`;
    case "QUOTE_REQUEST": return "asks what it could offer (a quote, nothing held)";
    case "QUOTE": return `quotes: ${quoteSummary(step.options ?? [])}`;
    default: return step.type ?? "";
  }
}

function quoteSummary(options: Record<string, unknown>[]): string {
  if (!options.length) return "nothing to offer";
  const shown = options.slice(0, 3).map((o) => {
    const extra = (o.extra ?? {}) as Record<string, unknown>;
    const qty = Number(o.quantity).toLocaleString();
    return extra.supplier ? `${extra.supplier}: ${qty} in ${extra.lead_time_days} d`
      : `${qty}${o.unit === "h" ? " h" : ""} from ${String(o.available_from ?? "").slice(5)}`;
  });
  return shown.join(", ") + (options.length > 3 ? ` … (${options.length} steps)` : "");
}

function threadStatus(steps: TimelineItem[]): { label: string; tone: string } {
  const types = steps.map((s) => s.type);
  if (types.includes("QUOTE")) return { label: "quoted", tone: "green" };
  if (types[0] === "QUOTE_REQUEST") return { label: "waiting for quote", tone: "amber" };
  if (types.includes("COMMIT")) return { label: "agreed ✓", tone: "green" };
  if (types.includes("ABORT")) return { label: "withdrawn", tone: "red" };
  const last = types[types.length - 1];
  if (last === "REJECT") return { label: "rejected", tone: "red" };
  if (last === "REQUEST") return { label: "waiting for offer", tone: "amber" };
  if (last === "OFFER" || last === "COUNTER_OFFER") return { label: "offer on the table", tone: "blue" };
  return { label: "agreeing…", tone: "blue" };
}
