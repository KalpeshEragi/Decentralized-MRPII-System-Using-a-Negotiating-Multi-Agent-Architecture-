"use client";

import { Fragment, useEffect, useState } from "react";
import type { Attempt, Decision, Item, Message, Negotiation, Order, Plan, Procurement, ShortageWithSuppliers, Terms } from "@/lib/api";
import type { Operation } from "@/lib/useSimulation";
import { AGENT_NAMES, PARTY_NAMES, describe, type Stage } from "@/lib/workflow";

type Items = Record<string, Item>;
const nameOf = (items: Items, id: string) => items[id]?.name ?? id.slice(0, 8);

const TONES: Record<string, string> = {
  AGREEMENT_PROPOSED: "info", COMMITTED: "ok", APPROVED: "ok", VALIDATED: "ok", COVERED: "ok", AGREEMENT: "ok",
  NEGOTIATING: "warn", PENDING_NEGOTIATION: "warn", AWAITING_APPROVAL: "info", SHORTAGE: "warn", INITIATED: "warn",
  REJECTED: "bad", FAILED: "bad", ABORTED: "bad", HUMAN_INTERVENTION_REQUIRED: "bad", INVALID: "bad",
};
export function Badge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="badge">—</span>;
  return <span className={`badge ${TONES[value] ?? ""}`}>{value.replaceAll("_", " ")}</span>;
}

// ---- workflow stages ----------------------------------------------------------------------------------------------

export function StageTracker({ stages }: { stages: Stage[] }) {
  return (
    <div className="card">
      <div className="stages">
        {stages.map((stage, i) => (
          <div key={stage.key} className={`stage ${stage.state}`}>
            <div className="dot">{stage.state === "done" ? "✓" : stage.state === "failed" ? "!" : i + 1}</div>
            <div className="label">{stage.label.toUpperCase()}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- live activity: the real decision log while an action runs -----------------------------------------------------

export function Activity({ operation, decisions, procurement, items }: {
  operation: Operation | null; decisions: Decision[]; procurement: Procurement[]; items: Items;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!operation) return;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [operation]);

  const fresh = operation ? decisions.slice(operation.decisionsBefore) : [];
  const latest = fresh.at(-1);
  const recent = operation ? fresh : decisions.slice(-6);
  return (
    <div className={`card activity ${operation ? "" : "idle"}`}>
      <div className="card-head">
        <div className="row">
          {operation && <div className="spinner" />}
          <h2>{operation ? operation.label : "System activity"}</h2>
        </div>
        {operation && <span className="muted small">{Math.floor((now - operation.startedAt) / 1000)} s elapsed</span>}
      </div>
      {operation?.agents && (
        <div className="muted">
          {latest ? <>Latest step: <b>{describe(latest)}</b> ({AGENT_NAMES[latest.agent] ?? latest.agent})</> : "Waiting for the first step to be recorded by the agents…"}
        </div>
      )}
      {operation && procurement.length > 0 && (
        <div className="row small" style={{ marginTop: 8 }}>
          {procurement.map((p) => (
            <span key={p.negotiation_id} className="badge info">
              {nameOf(items, p.item_id)}: {p.session_status.toLowerCase()}{p.round_number ? `, round ${p.round_number} of 3` : ""}
            </span>
          ))}
        </div>
      )}
      <ul className="feed">
        {recent.length === 0 && <li className="muted">No activity yet. Start planning to see the agents at work.</li>}
        {recent.map((d) => (
          <li key={d.id}>
            <span className="badge">{AGENT_NAMES[d.agent] ?? d.agent}</span>
            <span>{describe(d)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---- order and plan -----------------------------------------------------------------------------------------------

export function OrderCard({ order, items }: { order: Order; items: Items }) {
  return (
    <div className="card">
      <div className="card-head"><h2>Customer order {order.order_number}</h2><Badge value={order.status} /></div>
      <dl className="kv">
        {order.lines.map((l) => (
          <Fragment key={l.item_id}><dt>Product</dt><dd>{l.quantity.toLocaleString()} × {nameOf(items, l.item_id)}</dd></Fragment>
        ))}
        <dt>Order date</dt><dd>{order.order_date}</dd>
        <dt>Due date</dt><dd>{order.due_date}</dd>
        <dt>Priority</dt><dd>{order.priority} (1 = highest)</dd>
      </dl>
    </div>
  );
}

export function PlanSummary({ plan, items }: { plan: Plan; items: Items }) {
  return (
    <div className="card">
      <div className="card-head"><h2>Production plan</h2><Badge value={plan.status} /></div>
      <h3>Finished goods → net production requirement</h3>
      <table>
        <thead><tr><th>Product</th><th className="num">Ordered</th><th className="num">Finished goods available</th><th className="num">To produce</th></tr></thead>
        <tbody>{plan.finished_goods.map((f) => (
          <tr key={f.item_id}><td>{nameOf(items, f.item_id)}</td><td className="num">{f.order_quantity}</td><td className="num">{f.available_finished_goods}</td><td className="num"><b>{f.net_production_requirement}</b></td></tr>
        ))}</tbody>
      </table>
      <h3 style={{ marginTop: 14 }}>MPS and capacity</h3>
      <table>
        <thead><tr><th>Product</th><th className="num">Planned</th><th>Start → end</th><th>Capacity</th></tr></thead>
        <tbody>{plan.mps.map((m) => {
          const cap = plan.capacity_checks.find((c) => c.item_id === m.item_id);
          return (
            <tr key={m.id}>
              <td>{nameOf(items, m.item_id)}</td><td className="num">{m.planned_quantity}</td>
              <td>{m.planned_start} → {m.planned_end}</td>
              <td>{cap ? <><Badge value={cap.feasible ? "COVERED" : "INVALID"} /> <span className="muted small">{cap.required_days} of {cap.working_days} days at {cap.capacity_per_day}/day</span></> : "—"}</td>
            </tr>
          );
        })}</tbody>
      </table>
      {plan.mps.length === 0 && <div className="empty">No production needed: finished goods cover the order.</div>}
    </div>
  );
}

export function MrpTable({ plan, items }: { plan: Plan; items: Items }) {
  return (
    <div className="card">
      <div className="card-head"><h2>MRP: material requirements</h2><span className="muted small">planning date {plan.planning_date}</span></div>
      <table>
        <thead><tr><th>Component</th><th className="num">Gross</th><th className="num">Available</th><th className="num">Receipts</th><th className="num">Net</th><th>Required by</th><th>Status</th></tr></thead>
        <tbody>{plan.requirements.map((r) => (
          <tr key={`${r.mps_entry_id}-${r.item_id}`} className={r.net_requirement > 0 ? "highlight" : ""}>
            <td>{nameOf(items, r.item_id)}</td><td className="num">{r.gross_requirement}</td><td className="num">{r.available_quantity}</td>
            <td className="num">{r.scheduled_receipts}</td><td className="num"><b>{r.net_requirement}</b></td><td>{r.required_by}</td><td><Badge value={r.status} /></td>
          </tr>
        ))}</tbody>
      </table>
      <p className="muted small">Available = on hand − reserved − safety stock. Receipts = committed agreements only.</p>
    </div>
  );
}

export function SupplierOptions({ shortages, items }: { shortages: ShortageWithSuppliers[]; items: Items }) {
  if (shortages.length === 0) return null;
  return (
    <div className="card">
      <div className="card-head"><h2>Shortages and supplier options</h2><span className="muted small">supplier data (not agents); the Purchasing Agent chooses</span></div>
      {shortages.map(({ shortage, suppliers }) => (
        <div key={shortage.item_id} style={{ marginBottom: 12 }}>
          <div className="row"><b>{nameOf(items, shortage.item_id)}</b><span className="badge warn">short {shortage.shortage_quantity}</span><span className="muted small">required by {shortage.required_by}, priority {shortage.priority}</span></div>
          <table>
            <thead><tr><th>Supplier</th><th className="num">Lead time</th><th className="num">MOQ</th><th className="num">Available</th><th>Arrival</th><th>Feasibility</th></tr></thead>
            <tbody>{suppliers.map((s) => (
              <tr key={s.supplier}>
                <td>{s.supplier}</td><td className="num">{s.lead_time_days} d</td><td className="num">{s.min_order_qty}</td><td className="num">{s.available_qty}</td><td>{s.arrival_date}</td>
                <td>{s.covers_alone ? <span className="badge ok">covers alone</span> : s.usable ? <span className="badge warn">partial only</span> : <span className="badge bad">too late</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

// ---- negotiation --------------------------------------------------------------------------------------------------

function TermsView({ terms }: { terms: Terms | null }) {
  if (!terms) return null;
  return (
    <div className="terms">
      <span>Quantity <b>{terms.quantity}</b></span>
      {terms.required_date && <span>Required <b>{terms.required_date}</b></span>}
      {terms.delivery_date && <span>Delivery <b>{terms.delivery_date}</b></span>}
      {terms.priority && <span>Priority <b>{terms.priority}</b></span>}
    </div>
  );
}

function supplierName(messages: Message[]) {
  const note = messages.find((m) => m.sender === "PURCHASING" && m.message_type === "OFFER")?.payload.message ?? "";
  return /- (.+?):/.exec(note)?.[1] ?? null;
}

export function NegotiationCard({ negotiation, items, disabled, onRespond }: {
  negotiation: Negotiation; items: Items; disabled: boolean;
  onRespond: (body: { round_number: number; response_type: string; quantity?: number; delivery_date?: string }) => void;
}) {
  const n = negotiation;
  const [quantity, setQuantity] = useState<number>(n.objective.shortage_quantity);
  const [delivery, setDelivery] = useState<string>(n.objective.required_by);
  const supplier = supplierName(n.messages);
  const acting = n.awaiting_supplier ? "Supplier Interface (you)" : n.status === "NEGOTIATING" ? "Purchasing Agent" : "—";
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>{nameOf(items, n.objective.item_id)}: {n.objective.shortage_quantity} short</h2>
          <div className="muted small">Inventory Agent ⇄ Purchasing Agent ⇄ Supplier Interface{supplier ? ` (${supplier})` : ""}</div>
        </div>
        <Badge value={n.status} />
      </div>
      <div className="row">
        <span className="small muted">Round {n.round_number} of {n.max_rounds}</span>
        <div className="rounds">
          {Array.from({ length: n.max_rounds }, (_, i) => (
            <div key={i} className={`round ${i + 1 < n.round_number || (i + 1 === n.round_number && !n.awaiting_supplier) ? "used" : i + 1 === n.round_number ? "current" : ""}`} />
          ))}
        </div>
        <span className="small muted">Acting: <b>{acting}</b></span>
        <span className="small muted">Required by <b>{n.objective.required_by}</b>, priority <b>{n.objective.priority}</b></span>
      </div>
      <ul className="timeline">
        {n.messages.map((m) => (
          <li key={m.message_id} className={m.sender === "SUPPLIER_INTERFACE" ? "from-supplier" : m.sender === "APPROVAL_WORKFLOW" ? "from-approval" : ""}>
            <div>
              <div className="who">{PARTY_NAMES[m.sender] ?? m.sender}</div>
              <div className="small muted">→ {PARTY_NAMES[m.receiver] ?? m.receiver}</div>
            </div>
            <div>
              <Badge value={m.message_type} /> <TermsView terms={m.payload.terms} />
              {m.payload.message && <div className="small muted" style={{ marginTop: 3 }}>{m.payload.message}</div>}
            </div>
          </li>
        ))}
      </ul>
      {n.agreement && (
        <div className="row" style={{ marginTop: 10 }}>
          <b>Agreement:</b> <TermsView terms={n.agreement.agreed_terms} />
          <Badge value={n.agreement.validated ? "VALIDATED" : "INVALID"} />
          {n.agreement.committed ? <Badge value="COMMITTED" /> : <span className="badge warn">NOT COMMITTED</span>}
        </div>
      )}
      {n.awaiting_supplier && (
        <div className="supplier-form">
          <div className="row"><b>Supplier response: round {n.round_number} of {n.max_rounds}</b><span className="muted small">You play the supplier. The Purchasing Agent decides what happens next.</span></div>
          <div className="row">
            <button className="ok" disabled={disabled} onClick={() => onRespond({ round_number: n.round_number, response_type: "ACCEPT" })}>Accept offer</button>
            <button className="bad" disabled={disabled} onClick={() => onRespond({ round_number: n.round_number, response_type: "REJECT" })}>Reject</button>
          </div>
          <div className="row">
            <span className="small">Counter:</span>
            <input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} style={{ width: 90 }} aria-label="quantity" />
            <input type="date" value={delivery} onChange={(e) => setDelivery(e.target.value)} aria-label="delivery date" />
            <button disabled={disabled || !quantity || !delivery} onClick={() => onRespond({ round_number: n.round_number, response_type: "COUNTER_OFFER", quantity, delivery_date: delivery })}>Send counter-offer</button>
          </div>
        </div>
      )}
      {n.reaction_error && <div className="error-box" style={{ marginTop: 10 }}>{n.reaction_error}</div>}
    </div>
  );
}

// ---- approval -----------------------------------------------------------------------------------------------------

export function ApprovalPanel({ attempt, disabled, onApprove, onReject }: {
  attempt: Attempt; disabled: boolean; onApprove: () => void; onReject: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const awaiting = attempt.approval_status === "AWAITING_APPROVAL";
  return (
    <div className="card">
      <div className="card-head">
        <h2>Human approval: attempt {attempt.attempt_number} of 2</h2>
        <Badge value={attempt.approval_status} />
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        <b>AGREEMENT_PROPOSED ≠ COMMITTED.</b> Only your approval triggers COMMIT (agreements become scheduled receipts, stock is reserved).
        Rejecting aborts uncommitted agreements and makes the Planning Agent replan ({attempt.attempts_remaining} replanning attempt{attempt.attempts_remaining === 1 ? "" : "s"} left).
      </p>
      {attempt.approval_status === "PENDING_NEGOTIATION" && <div className="muted">Waiting until every negotiation of this attempt has ended.</div>}
      {awaiting && attempt.blockers.length > 0 && (
        <ul className="small" style={{ color: "var(--bad)" }}>{attempt.blockers.map((b) => <li key={b}>{b}</li>)}</ul>
      )}
      {awaiting && (
        <div className="row">
          <button className="ok" disabled={disabled || !attempt.approvable} onClick={onApprove} title={attempt.approvable ? "" : "Not approvable: a shortage has no agreement"}>Approve → COMMIT</button>
          <input placeholder="Reason for rejection (optional)" value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          <button className="bad" disabled={disabled} onClick={() => onReject(reason)}>{attempt.attempts_remaining > 0 ? "Reject → REPLAN" : "Reject (final)"}</button>
        </div>
      )}
    </div>
  );
}

export function AttemptHistory({ attempts }: { attempts: Attempt[] }) {
  if (attempts.length === 0) return null;
  return (
    <div className="card">
      <div className="card-head"><h2>Planning attempts</h2><span className="muted small">maximum 2</span></div>
      <table>
        <thead><tr><th>Attempt</th><th>Plan</th><th>Negotiations</th><th>Decision</th><th>Reason</th></tr></thead>
        <tbody>{attempts.map((a) => (
          <tr key={a.attempt_number}>
            <td>#{a.attempt_number}</td><td><Badge value={a.plan_status} /></td>
            <td className="small">{a.negotiations.map((n) => n.session_status.toLowerCase()).join(", ") || "none needed"}</td>
            <td><Badge value={a.approval_status} /></td><td className="small muted">{a.decision_reason ?? ""}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function DecisionLog({ decisions }: { decisions: Decision[] }) {
  return (
    <details className="card">
      <summary>Decision log ({decisions.length} records): every agent decision with its rationale</summary>
      <table style={{ marginTop: 10 }}>
        <thead><tr><th>Agent</th><th>Decision</th><th>Rationale</th></tr></thead>
        <tbody>{decisions.map((d) => (
          <tr key={d.id}><td className="small">{AGENT_NAMES[d.agent] ?? d.agent}</td><td className="small"><code>{d.decision_type}</code></td><td className="small">{d.reasoning_summary}</td></tr>
        ))}</tbody>
      </table>
    </details>
  );
}
