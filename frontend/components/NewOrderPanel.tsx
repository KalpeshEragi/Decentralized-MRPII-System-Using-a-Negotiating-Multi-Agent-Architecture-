"use client";
// Add one customer order by hand (the manual demo): product, quantity and deadline. It goes through the simulator's
// NEW_ORDER trigger, so a simulated customer asks Sales like any other; the agents plan it at once, even while the
// clock is paused. The panel decides nothing about the order.

import { useState } from "react";
import { api, Live, TriggerResult } from "@/lib/api";

const DAY_MS = 86_400_000;

export function NewOrderPanel({ live, onClose, onAdded }: { live: Live | null; onClose: () => void; onAdded: () => void }) {
  const products = (live?.stock ?? []).filter((s) => s.type === "FINISHED_PRODUCT");
  const today = live?.clock.day ?? "";
  const [product, setProduct] = useState("");
  const [quantity, setQuantity] = useState(100);
  const [deadline, setDeadline] = useState(() => (today ? addDays(today, 7) : ""));
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<{ ok: boolean; text: string }[]>([]);

  const sku = product || products[0]?.sku || "";
  const leadDays = today && deadline ? Math.round((Date.parse(deadline) - Date.parse(today)) / DAY_MS) : 0;

  async function add() {
    setBusy(true);
    try {
      const fired = await api.post<TriggerResult>("/simulation/triggers",
        { kind: "NEW_ORDER", params: { product_sku: sku, quantity, lead_days: leadDays } });
      const ok = fired.status !== "FAILED";
      setAdded((old) => [...old, { ok, text: ok ? `${quantity} ${sku} by ${deadline}: sent to Sales`
        : `Refused: ${String(fired.result?.message ?? "")}` }]);
      onAdded();
    } catch (e) {
      setAdded((old) => [...old, { ok: false, text: (e as Error).message }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card popover">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <div className="kind">Manual demo</div>
      <h3>New customer order</h3>
      <label>Product
        <select className="btn field" value={sku} onChange={(e) => setProduct(e.target.value)}>
          {products.map((p) => <option key={p.sku} value={p.sku}>{p.sku} · {p.name} (in stock {Number(p.on_hand)})</option>)}
        </select>
      </label>
      <label>Quantity
        <input className="btn field small" type="number" min={1} value={quantity}
               onChange={(e) => setQuantity(Math.max(1, Number(e.target.value)))} />
      </label>
      <label>Deadline
        <input className="btn field" type="date" min={today ? addDays(today, 1) : undefined} value={deadline}
               onChange={(e) => setDeadline(e.target.value)} />
      </label>
      <p className="help">Today is {today || "…"} · {leadDays > 0 ? `${leadDays} days to deliver` : "pick a later day"}.
        The agents start planning at once, even while the clock is paused. Press Play when you are ready.</p>
      <button className="btn primary wide" disabled={busy || !sku || leadDays < 1} onClick={add}>
        {busy ? "Adding…" : "＋ Add order"}
      </button>
      {added.map((a, i) => <div key={i} className={`badge ${a.ok ? "green" : "red"} result`}>{a.text}</div>)}
    </div>
  );
}

function addDays(day: string, days: number): string {
  return new Date(Date.parse(day) + days * DAY_MS).toISOString().slice(0, 10);
}
