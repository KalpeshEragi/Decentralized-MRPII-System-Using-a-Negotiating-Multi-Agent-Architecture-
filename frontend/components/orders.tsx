"use client";

import { Fragment, useState } from "react";
import type { Item, NewOrder, OrderOverview, Plan } from "@/lib/api";
import type { PlanChange } from "@/lib/useSimulation";
import { totals } from "@/lib/workflow";
import { Badge } from "./panels";

type Items = Record<string, Item>;
const nameOf = (items: Items, id: string) => items[id]?.name ?? id.slice(0, 8);

// ---- customer orders: list + form ----------------------------------------------------------------------------------

export function CustomerOrders({ orders, items, selected, disabled, onSelect, onCreate }: {
  orders: OrderOverview[]; items: Items; selected: string | null; disabled: boolean;
  onSelect: (id: string) => void; onCreate: (order: NewOrder) => Promise<boolean>;
}) {
  const products = Object.values(items).filter((i) => i.item_type === "FINISHED_PRODUCT");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ customer_name: "", order_number: "", product: "", quantity: "", priority: "1", order_date: "", due_date: "" });
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [key]: e.target.value });
  const product = form.product || products[0]?.id || "";
  const complete = form.customer_name && product && Number(form.quantity) > 0 && form.order_date && form.due_date;

  const save = async () => {
    const ok = await onCreate({
      customer_name: form.customer_name.trim(),
      ...(form.order_number.trim() ? { order_number: form.order_number.trim() } : {}),
      order_date: form.order_date, due_date: form.due_date, priority: Number(form.priority),
      lines: [{ item_id: product, quantity: Number(form.quantity) }],
    });
    if (ok) {
      setOpen(false);
      setForm({ ...form, customer_name: "", order_number: "", quantity: "" });
    }
  };

  return (
    <div className="card">
      <div className="card-head">
        <div><h2>Customer orders</h2><div className="muted small">Planning order: priority 1 first, then due date. Click a row to follow its negotiations.</div></div>
        <button onClick={() => setOpen(!open)} disabled={disabled}>{open ? "Close form" : "+ Add customer order"}</button>
      </div>
      {open && (
        <div className="order-form">
          <label>Customer<input value={form.customer_name} onChange={set("customer_name")} placeholder="e.g. Customer A" /></label>
          <label>Order no. (optional)<input value={form.order_number} onChange={set("order_number")} placeholder="auto: SO-000n" /></label>
          <label>Product<select value={product} onChange={set("product")}>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <label>Quantity<input type="number" min={1} value={form.quantity} onChange={set("quantity")} placeholder="e.g. 1000" /></label>
          <label>Priority<select value={form.priority} onChange={set("priority")}>{[1, 2, 3, 4, 5].map((p) => <option key={p} value={p}>{p}{p === 1 ? " (highest)" : ""}</option>)}</select></label>
          <label>Order date<input type="date" value={form.order_date} onChange={set("order_date")} /></label>
          <label>Due date<input type="date" value={form.due_date} onChange={set("due_date")} /></label>
          <div className="form-actions"><button className="primary" disabled={disabled || !complete} onClick={() => void save()}>Save order</button></div>
        </div>
      )}
      {orders.length === 0 ? (
        <div className="empty">No customer orders yet. Add one to start.</div>
      ) : (
        <table>
          <thead><tr><th>Order</th><th>Customer</th><th>Product</th><th className="num">Qty</th><th className="num">Priority</th><th>Order date</th><th>Due date</th><th>Status</th></tr></thead>
          <tbody>{orders.map((o) => (
            <tr key={o.id} className={`clickable ${o.id === selected ? "selected" : ""}`} onClick={() => !disabled && onSelect(o.id)}>
              <td><b>{o.order_number}</b></td><td>{o.customer_name ?? "—"}</td>
              <td>{o.lines.map((l) => nameOf(items, l.item_id)).join(", ")}</td>
              <td className="num">{o.lines.reduce((n, l) => n + l.quantity, 0).toLocaleString()}</td>
              <td className="num">{o.priority}</td><td>{o.order_date}</td><td>{o.due_date}</td>
              <td><Badge value={o.status === "NEW" ? "NOT PLANNED" : o.status} /></td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

// ---- combined plan across orders -----------------------------------------------------------------------------------

export function CombinedPlan({ orders, plans, items }: { orders: OrderOverview[]; plans: Record<string, Plan>; items: Items }) {
  const planned = orders.filter((o) => plans[o.id]);
  if (planned.length === 0) return null;
  const number = Object.fromEntries(orders.map((o) => [o.id, o.order_number]));
  const rows = planned.flatMap((o) => plans[o.id].requirements.map((r) => ({ ...r, order_id: o.id })));
  const components = [...new Set(rows.map((r) => r.item_id))];
  return (
    <>
      <div className="card">
        <div className="card-head"><h2>Master production schedule: all planned orders</h2><span className="muted small">finished goods netted first, then one MPS entry per order line</span></div>
        <table>
          <thead><tr><th>Order</th><th>Product</th><th className="num">Ordered</th><th className="num">Finished goods used</th><th className="num">To produce</th><th>Production window</th><th>Capacity</th><th>Plan</th></tr></thead>
          <tbody>{planned.flatMap((o) => plans[o.id].finished_goods.map((f) => {
            const entry = plans[o.id].mps.find((m) => m.item_id === f.item_id);
            const cap = entry && plans[o.id].capacity_checks.find((c) => c.mps_entry_id === entry.id);
            return (
              <tr key={`${o.id}-${f.item_id}`}>
                <td><b>{o.order_number}</b> <span className="muted small">P{o.priority}</span></td><td>{nameOf(items, f.item_id)}</td>
                <td className="num">{f.order_quantity}</td><td className="num">{f.order_quantity - f.net_production_requirement}</td>
                <td className="num"><b>{f.net_production_requirement}</b></td>
                <td>{entry ? `${entry.planned_start} → ${entry.planned_end}` : "none needed"}</td>
                <td>{cap ? <><Badge value={cap.feasible ? "COVERED" : "INVALID"} /> <span className="muted small">{cap.required_days} of {cap.working_days} days · max {cap.max_quantity}</span></> : "—"}</td>
                <td><Badge value={plans[o.id].status} /></td>
              </tr>
            );
          }))}</tbody>
        </table>
        <p className="muted small">Capacity is checked per MPS entry against its own production window (capacity per day × lead time).</p>
      </div>

      <div className="card">
        <div className="card-head"><h2>MRP: component requirements, combined demand</h2><span className="muted small">netted in order of required date, then priority: earlier orders consume stock first</span></div>
        <table>
          <thead><tr><th>Component</th><th>Order</th><th className="num">Gross</th><th className="num">Available</th><th className="num">Receipts</th><th className="num">Net</th><th>Required by</th><th>Status</th></tr></thead>
          <tbody>{components.map((c) => {
            const own = rows.filter((r) => r.item_id === c);
            const gross = own.reduce((n, r) => n + r.gross_requirement, 0);
            const net = own.reduce((n, r) => n + r.net_requirement, 0);
            return (
              <Fragment key={c}>
                {own.map((r, i) => (
                  <tr key={`${c}-${r.mps_entry_id}`} className={r.net_requirement > 0 ? "highlight" : ""}>
                    <td>{i === 0 ? <b>{nameOf(items, c)}</b> : ""}</td><td>{number[r.order_id]}</td>
                    <td className="num">{r.gross_requirement}</td><td className="num">{r.available_quantity}</td><td className="num">{r.scheduled_receipts}</td>
                    <td className="num"><b>{r.net_requirement}</b></td><td>{r.required_by}</td><td><Badge value={r.status} /></td>
                  </tr>
                ))}
                {own.length > 1 && (
                  <tr className="subtotal"><td /><td className="muted small">total</td><td className="num">{gross}</td><td /><td /><td className="num"><b>{net}</b></td><td /><td /></tr>
                )}
              </Fragment>
            );
          })}</tbody>
        </table>
        <p className="muted small">Available = on hand − reserved − safety stock, minus what earlier rows consumed. Receipts = committed agreements only.</p>
      </div>
    </>
  );
}

// ---- what changed --------------------------------------------------------------------------------------------------

function Delta({ before, after }: { before: number; after: number }) {
  const d = after - before;
  return <>{before.toLocaleString()} → <b>{after.toLocaleString()}</b> {d !== 0 && <span className={`badge ${d > 0 ? "warn" : "ok"}`}>{d > 0 ? "+" : ""}{d.toLocaleString()}</span>}</>;
}

export function PlanChangeCard({ change, items, onClose }: { change: PlanChange; items: Items; onClose: () => void }) {
  const b = totals(change.before);
  const a = totals(change.after);
  const components = [...new Set([...Object.keys(b.gross), ...Object.keys(a.gross)])];
  const changed = components.filter((c) => (b.gross[c] ?? 0) !== (a.gross[c] ?? 0) || (b.net[c] ?? 0) !== (a.net[c] ?? 0));
  const same = a.orders === b.orders && a.production === b.production && changed.length === 0 && a.shortages === b.shortages;
  return (
    <div className="card change">
      <div className="card-head">
        <h2>{same ? "Replanned: nothing changed" : "Planning changed"}</h2>
        <button onClick={onClose}>Dismiss</button>
      </div>
      <div className="change-grid">
        <div><div className="muted small">Planned orders</div><Delta before={b.orders} after={a.orders} /></div>
        <div><div className="muted small">Customer demand</div><Delta before={b.demand} after={a.demand} /></div>
        <div><div className="muted small">Production (MPS)</div><Delta before={b.production} after={a.production} /></div>
        <div><div className="muted small">MPS entries</div><Delta before={b.mpsEntries} after={a.mpsEntries} /></div>
        <div><div className="muted small">Busiest capacity window</div>{b.maxCapacityUse} → <b>{a.maxCapacityUse}</b>{a.capacityIssues > 0 && <span className="badge bad"> {a.capacityIssues} over capacity</span>}</div>
        <div><div className="muted small">Shortage rows</div><Delta before={b.shortages} after={a.shortages} /></div>
      </div>
      {changed.length > 0 && (
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>Component</th><th>Gross requirement</th><th>Net requirement (to procure)</th></tr></thead>
          <tbody>{changed.map((c) => (
            <tr key={c}><td>{nameOf(items, c)}</td><td><Delta before={b.gross[c] ?? 0} after={a.gross[c] ?? 0} /></td><td><Delta before={b.net[c] ?? 0} after={a.net[c] ?? 0} /></td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
