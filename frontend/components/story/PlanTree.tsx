"use client";
// One order's plan as a tree (the BOM explosion Planning made): the order, what comes from stock, what is built, and
// under each production order the stock, worker-hours and space it asked the owners for. Every line names the owner
// agent and shows where its negotiation stands; clicking a line opens that negotiation.

import type { OrderStory, ProductionOrderRow, StoryNegotiation } from "@/lib/api";
import { agent } from "@/lib/agents";

const RESOURCE: Record<string, string> = {
  STOCK: "from stock", SUPPLY: "to buy", WORKFORCE: "worker-hours", STORAGE_SPACE: "storage space",
  RECEIVING_SLOT: "receiving slot", PRODUCTION_CAPACITY: "machine-hours",
};

export function PlanTree({ story, negotiations, selected, onSelect, focusOwner }: {
  story: OrderStory; negotiations: StoryNegotiation[]; selected: string | null; onSelect: (session: string) => void;
  focusOwner: string | null;
}) {
  const plan = story.plan;
  const orders = story.plan.production_orders;
  const known = new Set([plan.demand_id, ...orders.map((o) => o.id)]);
  const earlier = negotiations.filter((n) => !n.order_id || !known.has(n.order_id));

  const leaves = (target: string) => negotiations.filter((n) => n.order_id === target);
  const builds = (target: string) => orders.filter((o) => parentOf(o, plan.demand_id) === target);
  const row = (n: StoryNegotiation) => (
    <Leaf key={n.session_id} n={n} on={selected === n.session_id}
          dim={!!focusOwner && n.owner !== focusOwner} onSelect={onSelect} />
  );

  function Build({ o }: { o: ProductionOrderRow }) {
    return (
      <li className="build">
        <div className="node-line">🏭 <b>Build {qty(o.quantity)} {o.sku}</b>
          <span className="muted"> · {o.start_day} → {o.end_day} · {o.work_centers.join(", ")}</span>
          <span className={`badge ${tone(o.status)}`}>{o.status.toLowerCase()}</span>
        </div>
        <ul>{leaves(o.id).map(row)}{builds(o.id).map((c) => <Build key={c.id} o={c} />)}</ul>
      </li>
    );
  }

  return (
    <div className="plan-tree">
      <div className="summary">{summary(story, negotiations)}</div>
      <ul className="tree">
        <li>
          <div className="node-line root">📦 <b>{qty(plan.quantity)} {plan.sku}</b>
            <span className="muted"> · {plan.label} · due {plan.requested_day}
              {plan.committed_day ? ` · promised ${plan.committed_day}` : ""}</span>
          </div>
          <ul>
            {leaves(plan.demand_id).map(row)}
            {builds(plan.demand_id).map((o) => <Build key={o.id} o={o} />)}
          </ul>
        </li>
        {earlier.length > 0 && (
          <li>
            <div className="node-line muted">🗂 Earlier plan (replaced production orders)</div>
            <ul>{earlier.map(row)}</ul>
          </li>
        )}
      </ul>
      {negotiations.length === 0 && <div className="notice">Planning has not asked anyone yet in this round.</div>}
    </div>
  );
}

function Leaf({ n, on, dim, onSelect }: {
  n: StoryNegotiation; on: boolean; dim: boolean; onSelect: (session: string) => void;
}) {
  const owner = agent(n.owner);
  const asked = n.asked;
  const agreed = n.agreed_terms?.quantity;
  const unit = asked.unit === "h" ? " h" : "";
  const when = asked.needed_by ? ` by ${asked.needed_by}` : "";
  return (
    <li className={`leaf ${on ? "on" : ""} ${dim ? "dim" : ""}`} onClick={() => onSelect(n.session_id)}>
      <span className={`status-dot ${tone(n.status)}`} title={n.status} />
      <span className="chip" style={{ background: owner.color }}>{owner.name}</span>
      <span>{qty(String(asked.quantity ?? ""))}{unit} {n.resource_type === "WORKFORCE" ? `${n.resource_label} ` : ""}
        {n.resource_type !== "WORKFORCE" && n.resource_type !== "STORAGE_SPACE" ? `${n.resource_label} ` : ""}
        {RESOURCE[n.resource_type] ?? n.resource_type.toLowerCase()}{when}</span>
      {agreed !== undefined && String(agreed) !== String(asked.quantity) &&
        <span className="badge amber">agreed {qty(String(agreed))}</span>}
      {n.last_reason_code && <span className="badge red">{n.last_reason_code.toLowerCase().replaceAll("_", " ")}</span>}
    </li>
  );
}

/** "160 PHONE-P = 50 from stock + build 110" for the root. */
function summary(story: OrderStory, negotiations: StoryNegotiation[]): string {
  const plan = story.plan;
  const fromStock = negotiations.filter((n) => n.order_id === plan.demand_id && n.resource_type === "STOCK"
    && n.resource_ref === plan.item_id).reduce((sum, n) => sum + Number(n.asked.quantity ?? 0), 0);
  const built = plan.production_orders.filter((o) => parentOf(o, plan.demand_id) === plan.demand_id)
    .reduce((sum, o) => sum + Number(o.quantity), 0);
  const parts = [fromStock ? `${fromStock} from stock` : "", built ? `build ${built}` : ""].filter(Boolean);
  return `${qty(plan.quantity)} ${plan.sku ?? ""}${parts.length ? ` = ${parts.join(" + ")}` : ""}`;
}

function parentOf(o: ProductionOrderRow, demandId: string): string {
  return o.for_kind === "PRODUCTION_ORDER" ? o.for_ref : demandId;
}

export function qty(text: string): string {
  const n = Number(text);
  return Number.isFinite(n) && text !== "" ? n.toLocaleString() : text;
}

export function tone(status: string): string {
  if (["COMMITTED", "COMPLETED", "SHIPPED", "AGREED", "FIRM", "RELEASED", "STARTED"].includes(status)) return "green";
  if (["REJECTED", "ABORTED", "EXPIRED", "FAILED", "CANCELLED", "NOT_FEASIBLE", "AT_RISK"].includes(status)) return "red";
  return "amber";
}
