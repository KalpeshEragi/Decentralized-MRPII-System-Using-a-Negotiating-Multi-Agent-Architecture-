"use client";
// Each order's committed plan (from its PlanCommitted event) next to where it stands now (live snapshot), with every
// later plan event in words. Nothing is recomputed: the baseline is the event Planning published when it committed.

import { Fragment, useState } from "react";
import { OrderComparison, VERDICT } from "@/lib/insight";

export function PlanCompare({ comparisons, onClose, onOpenStory }: {
  comparisons: OrderComparison[]; onClose: () => void; onOpenStory: (demandId: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [onlyChanged, setOnlyChanged] = useState(false);
  const rows = onlyChanged ? comparisons.filter((c) => c.changes.length) : comparisons;
  return (
    <div className="overlay card">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <h3>📋 Committed plan vs now</h3>
      <p className="muted">"Committed" is what Planning published when the order was committed. Planning never moves a customer's
        delivery date by itself: it moves work between days, or reports the order at risk with an estimated new date.</p>
      <label className="check"><input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} /> Only orders that changed</label>
      {rows.length === 0 ? <p className="muted">No orders yet.</p> : (
        <table className="grid compare">
          <thead><tr><th>Order</th><th>Product</th><th>Committed qty → now</th><th>Committed delivery → now</th>
            <th>Production days (committed)</th><th>Status</th><th>Changes</th></tr></thead>
          <tbody>{rows.map((c) => {
            const v = VERDICT[c.verdict];
            const qtyNow = c.current?.quantity, dayNow = c.current?.committed_day;
            const qtyChanged = c.baseline && qtyNow && Number(qtyNow) !== Number(c.baseline.quantity);
            const estimate = [...c.changes].reverse().find((x) => x.item.payload?.estimated_delivery_day)?.item.payload?.estimated_delivery_day;
            return (
              <Fragment key={c.demandId}>
                <tr className="click" onClick={() => setOpen(open === c.demandId ? null : c.demandId)}>
                  <td><b>{c.label}</b></td>
                  <td>{c.sku ?? "–"}</td>
                  <td>{c.baseline ? <>{Number(c.baseline.quantity)}{qtyChanged ? <> → <b className="amber">{Number(qtyNow)}</b></> : ""}</> : "–"}</td>
                  <td>{c.baseline ? <>{c.baseline.deliveryDay}{dayNow && dayNow !== c.baseline.deliveryDay ? <> → <b>{dayNow}</b></> : ""}
                    {estimate && c.verdict === "AT_RISK" ? <> → <b className="red" title="Planning's estimate, not a promise">≈{String(estimate)}</b></> : ""}</> : "–"}</td>
                  <td>{c.baseline?.productionOrders.map((p) => `${p.start_day.slice(5)}…${p.end_day.slice(5)}`).join(", ") || "–"}</td>
                  <td><span className={`badge ${v.tone}`} title={v.help}>{v.label}</span></td>
                  <td>{c.changes.length ? `${c.changes.length} ▾` : "–"}</td>
                </tr>
                {open === c.demandId && (
                  <tr className="expanded"><td colSpan={7}>
                    {c.changes.length === 0 ? <p className="muted">No plan event since it was committed.</p>
                      : <ol className="changes">{c.changes.map((x, i) => (
                        <li key={i} className={`change ${x.tone}`}><span className="time">{x.item.time.slice(11, 19)}</span> {x.text}</li>))}</ol>}
                    <button className="btn" onClick={() => onOpenStory(c.demandId)}>📖 Full story: negotiations and decisions →</button>
                  </td></tr>
                )}
              </Fragment>);
          })}</tbody>
        </table>
      )}
    </div>
  );
}
