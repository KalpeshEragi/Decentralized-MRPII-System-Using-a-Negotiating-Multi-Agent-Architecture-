"use client";
// Disruptions during a demo (demo.md §7): each button fires one simulator trigger through POST /simulation/triggers.
// A trigger only changes a simulated fact through its owner's input; the agents decide how to react (FE-6).

import { useState } from "react";
import { api, Live, TriggerResult } from "@/lib/api";

type Kind = "WORKER_ABSENT" | "SUPPLIER_DELAY" | "WAREHOUSE_CAPACITY" | "CANCEL_ORDER" | "CHANGE_ORDER" | "NEW_ORDER";

const KINDS: { kind: Kind; label: string; help: string }[] = [
  { kind: "WORKER_ABSENT", label: "Worker absent", help: "HR records the absence; Planning repairs the plan." },
  { kind: "SUPPLIER_DELAY", label: "Supplier delay", help: "The next committed delivery of the item arrives later." },
  { kind: "WAREHOUSE_CAPACITY", label: "Dock / storage capacity",
    help: "Warehouse gets a new capacity; new deliveries and space are planned around it." },
  { kind: "CANCEL_ORDER", label: "Customer cancels", help: "Sales passes it on; Planning frees what the order held." },
  { kind: "CHANGE_ORDER", label: "Customer changes quantity", help: "Planning checks the new quantity." },
  { kind: "NEW_ORDER", label: "New customer request", help: "A simulated customer asks Sales for a product." },
];

export function Disruptions({ live, onClose, onFired }: {
  live: Live | null; onClose: () => void; onFired: () => void;
}) {
  const [kind, setKind] = useState<Kind>("WORKER_ABSENT");
  const [worker, setWorker] = useState("");
  const [fromDay, setFromDay] = useState(1);
  const [days, setDays] = useState(3);
  const [item, setItem] = useState("");
  const [order, setOrder] = useState("latest");
  const [quantity, setQuantity] = useState(100);
  const [product, setProduct] = useState("");
  const [leadDays, setLeadDays] = useState(10);
  const [resource, setResource] = useState("RECEIVING");
  const [units, setUnits] = useState(600);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const workers = live?.workers ?? [];
  const bought = (live?.stock ?? []).filter((s) => s.type === "RAW_MATERIAL");
  const products = (live?.stock ?? []).filter((s) => s.type === "FINISHED_PRODUCT");
  const committed = (live?.orders ?? []).filter((o) => o.status === "COMMITTED" && o.order_number);

  function params(): Record<string, unknown> {
    switch (kind) {
      case "WORKER_ABSENT":
        return { worker: worker || workers[0]?.code, first_day_offset: fromDay, last_day_offset: fromDay + days - 1 };
      case "SUPPLIER_DELAY": return { item_sku: item || bought[0]?.sku, days };
      case "WAREHOUSE_CAPACITY": return { resource, units };
      case "CANCEL_ORDER": return { order_number: order };
      case "CHANGE_ORDER": return { order_number: order, quantity };
      case "NEW_ORDER": return { product_sku: product || products[0]?.sku, quantity, lead_days: leadDays };
    }
  }

  async function fire() {
    setBusy(true);
    setResult(null);
    try {
      const fired = await api.post<TriggerResult>("/simulation/triggers", { kind, params: params() });
      const failed = fired.status === "FAILED";
      setResult({ ok: !failed, text: failed ? String(fired.result?.message ?? "refused") : "Sent. Watch the agents react." });
      onFired();
    } catch (e) {
      setResult({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const number = (value: number, set: (n: number) => void, min = 1) => (
    <input className="btn field" type="number" min={min} value={value} onChange={(e) => set(Number(e.target.value))} />
  );
  const orderSelect = (
    <select className="btn field" value={order} onChange={(e) => setOrder(e.target.value)}>
      <option value="latest">Latest committed order</option>
      {committed.map((o) => <option key={o.demand_id} value={o.order_number!}>{o.order_number} · {o.sku} × {o.quantity}</option>)}
    </select>
  );

  return (
    <div className="card popover">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <div className="kind">Simulator trigger</div>
      <h3>Cause a disruption</h3>
      <div className="chips">
        {KINDS.map((k) => (
          <button key={k.kind} className={`tab ${kind === k.kind ? "on" : ""}`} onClick={() => { setKind(k.kind); setResult(null); }}>
            {k.label}
          </button>
        ))}
      </div>
      <p className="help">{KINDS.find((k) => k.kind === kind)!.help}</p>

      {kind === "WORKER_ABSENT" && (<>
        <label>Worker<select className="btn field" value={worker} onChange={(e) => setWorker(e.target.value)}>
          {workers.map((w) => <option key={w.code} value={w.code}>{w.name} ({w.code}, {w.primary_skill.toLowerCase()})</option>)}
        </select></label>
        <label>Starts in (days){number(fromDay, setFromDay, 0)}</label>
        <label>For (days){number(days, setDays)}</label>
      </>)}
      {kind === "SUPPLIER_DELAY" && (<>
        <label>Item<select className="btn field" value={item} onChange={(e) => setItem(e.target.value)}>
          {bought.map((s) => <option key={s.sku} value={s.sku}>{s.name} ({s.sku})</option>)}
        </select></label>
        <label>Days late{number(days, setDays)}</label>
      </>)}
      {kind === "WAREHOUSE_CAPACITY" && (<>
        <label>Capacity<select className="btn field" value={resource} onChange={(e) => setResource(e.target.value)}>
          <option value="RECEIVING">Receiving dock (pieces a day)</option>
          <option value="SHIPPING">Shipping dock (pieces a day)</option>
          <option value="MATERIALS">Materials zone (space units)</option>
          <option value="FINISHED_GOODS">Finished goods zone (space units)</option>
        </select></label>
        <label>New capacity{number(units, setUnits, 0)}</label>
      </>)}
      {kind === "CANCEL_ORDER" && <label>Order{orderSelect}</label>}
      {kind === "CHANGE_ORDER" && (<><label>Order{orderSelect}</label><label>New quantity{number(quantity, setQuantity)}</label></>)}
      {kind === "NEW_ORDER" && (<>
        <label>Product<select className="btn field" value={product} onChange={(e) => setProduct(e.target.value)}>
          {products.map((s) => <option key={s.sku} value={s.sku}>{s.name}</option>)}
        </select></label>
        <label>Quantity{number(quantity, setQuantity)}</label>
        <label>Wanted in (days){number(leadDays, setLeadDays)}</label>
      </>)}

      <button className="btn primary wide" disabled={busy} onClick={fire}>{busy ? "Sending…" : "⚡ Fire now"}</button>
      {result && <div className={`badge ${result.ok ? "green" : "red"} result`}>{result.text}</div>}
    </div>
  );
}
