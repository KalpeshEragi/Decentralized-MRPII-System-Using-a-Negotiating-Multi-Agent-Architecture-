"use client";
// The simulated customers (demo.md §9, DM-7), changed through POST /simulation/settings. Structured mode for many
// orders (no language model); chat mode for one or two orders shown live (Sales reads their messages with the model).

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Values = Record<string, number | string>;
const KEYS = ["customer_orders_per_day", "customer_chat_mode", "customer_quantity_min", "customer_quantity_max",
  "customer_lead_days_min", "customer_lead_days_max"] as const;

export function CustomersPanel({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [values, setValues] = useState<Values | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api.get<{ values: Values }>("/simulation/settings").then((s) => setValues(s.values))
      .catch((e) => setMessage({ ok: false, text: (e as Error).message }));
  }, []);

  const value = (key: (typeof KEYS)[number]) => Number(values?.[key] ?? 0);
  const set = (key: (typeof KEYS)[number], v: number) => setValues((old) => ({ ...old, [key]: v }));

  async function save() {
    if (!values) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.post("/simulation/settings", Object.fromEntries(KEYS.map((k) => [k, value(k)])));
      setMessage({ ok: true, text: value("customer_orders_per_day")
        ? "Saved. New requests arrive every simulated morning." : "Saved. No new customers (Play can pause)." });
      onSaved();
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const number = (key: (typeof KEYS)[number], min = 0) => (
    <input className="btn field small" type="number" min={min} value={value(key)}
           onChange={(e) => set(key, Number(e.target.value))} />
  );
  const chat = value("customer_chat_mode") === 1;

  return (
    <div className="card popover">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <div className="kind">Simulated customers</div>
      <h3>Customers</h3>
      {!values && !message && <p className="help">Loading…</p>}
      {values && (<>
        <label>New requests per day{number("customer_orders_per_day")}</label>
        <label>How they talk
          <span className="tabs">
            <button className={`tab ${!chat ? "on" : ""}`} onClick={() => set("customer_chat_mode", 0)}>Structured</button>
            <button className={`tab ${chat ? "on" : ""}`} onClick={() => set("customer_chat_mode", 1)}>Chat</button>
          </span>
        </label>
        <p className="help">
          {chat ? "Customers write messages; Sales reads them with the language model (start Ollama). Best for one or two orders."
            : "Requests and answers go as data, no language model. Best for many orders."}
        </p>
        <label>Quantity from / to<span className="pair">{number("customer_quantity_min", 1)}{number("customer_quantity_max", 1)}</span></label>
        <label>Wanted in days, from / to<span className="pair">{number("customer_lead_days_min", 1)}{number("customer_lead_days_max", 1)}</span></label>
        <button className="btn primary wide" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
      </>)}
      {message && <div className={`badge ${message.ok ? "green" : "red"} result`}>{message.text}</div>}
    </div>
  );
}
