"use client";

import { useMemo } from "react";
import { CombinedPlan, CustomerOrders, PlanChangeCard } from "@/components/orders";
import { Activity, ApprovalPanel, AttemptHistory, DecisionLog, NegotiationCard, StageTracker, SupplierOptions } from "@/components/panels";
import { api, type NewOrder } from "@/lib/api";
import { useSimulation } from "@/lib/useSimulation";
import { headline, stages } from "@/lib/workflow";

export default function SimulationPage() {
  const sim = useSimulation();
  const { snapshot: s, orderId, operation, error } = sim;
  const busy = operation !== null;
  const order = s.orders.find((o) => o.id === orderId) ?? null;
  const attempt = s.attempts.at(-1) ?? null;
  const flow = useMemo(() => stages(s, busy), [s, busy]);
  const banner = headline(s);
  const currentNegotiations = (attempt?.negotiations ?? []).map((n) => s.negotiations[n.negotiation_id]).filter(Boolean);
  const earlier = s.attempts.slice(0, -1);
  const anyPlanned = Object.keys(s.plans).length > 0;
  const unplanned = s.orders.filter((o) => o.status !== "PLANNED").length;

  const reset = () => {
    if (window.confirm("Reset the database to the X1 baseline with no customer orders? All orders, plans, negotiations and decisions are deleted.")) {
      void sim.run("Resetting the database to the X1 baseline…", api.reset,
        { success: "Simulation reset: stock, BOM and suppliers loaded. Add a customer order to begin.", agents: false });
    }
  };
  const runPlanning = () => sim.run(
    anyPlanned ? "Replanning all orders: combined MPS / MRP, then negotiations for new orders…" : "Planning: Planning → Inventory → Purchasing (A2A)…",
    api.runPlanning,
    { success: "Planning finished. See what changed.", trackChange: true },
  );
  const createOrder = (data: NewOrder) => sim.run("Saving the customer order…", () => api.createOrder(data), {
    success: `Order saved. Press ${anyPlanned ? "Replan" : "Run planning"} to include it in the plan.`,
    agents: false, select: (created) => (created as { id: string }).id,
  });

  return (
    <>
      <header className="topbar">
        <div className="title">
          <h1>Decentralized MRPII: SmartPhone X1 simulation</h1>
          <span>Autonomous Planning, Inventory and Purchasing agents · deterministic MPS / MRP · human approval</span>
        </div>
        <div className="controls">
          <button className="ghost-dark" onClick={() => void sim.refresh()} disabled={busy}>Refresh</button>
          <button className="ghost-dark" onClick={reset} disabled={busy}>Reset simulation</button>
          <button className="primary" onClick={() => void runPlanning()} disabled={busy || s.orders.length === 0}>
            {anyPlanned ? `⟳ Replan${unplanned ? ` (+${unplanned} new order${unplanned > 1 ? "s" : ""})` : ""}` : "▶ Run planning"}
          </button>
        </div>
      </header>

      <main>
        {error && (
          <div className="error-box">
            <span><b>{error.code === "UNREACHABLE" ? "Backend unavailable." : error.code === "TIMEOUT" ? "Still working or timed out." : "Request refused."}</b> {error.message}
              {error.details.length > 0 && <> ({error.details.map((d) => d.issue).join("; ")})</>}</span>
            <button onClick={() => void sim.refresh()}>Retry</button>
          </div>
        )}
        {sim.notice && !busy && <div className="banner info small">{sim.notice}</div>}

        <StageTracker stages={flow} />
        <Activity operation={operation} decisions={s.decisions} procurement={sim.liveProcurement} items={s.items} />

        {sim.loading && <div className="card empty"><div className="spinner" style={{ margin: "0 auto 8px" }} />Loading from the backend…</div>}

        <CustomerOrders orders={s.orders} items={s.items} selected={orderId} disabled={busy}
          onSelect={sim.selectOrder} onCreate={createOrder} />

        {sim.change && <PlanChangeCard change={sim.change} items={s.items} onClose={() => sim.setChange(null)} />}

        <CombinedPlan orders={s.orders} plans={s.plans} items={s.items} />

        {order && (
          <section style={{ display: "grid", gap: 16 }}>
            <div className="section-title">
              <h2>Order {order.order_number}{order.customer_name ? ` · ${order.customer_name}` : ""}: procurement, negotiation and approval</h2>
              {s.orders.length > 1 && <span className="muted small">Select another order in the table above to follow it.</span>}
            </div>
            {banner && (
              <div className={`banner ${banner.tone}`}>
                <div><div className="big">{banner.title}</div><div>{banner.text}</div></div>
              </div>
            )}
            {!attempt && <div className="card empty">This order is not planned yet. Press <b>{anyPlanned ? "Replan" : "Run planning"}</b>.</div>}
            <SupplierOptions shortages={s.shortages} items={s.items} />
            {attempt && currentNegotiations.length === 0 && <div className="card empty">No shortage for this order: nothing to negotiate.</div>}
            <div className="grid-2">
              {currentNegotiations.map((n) => (
                <NegotiationCard key={n.id} negotiation={n} items={s.items} />
              ))}
            </div>
            {attempt && (
              <ApprovalPanel
                attempt={attempt} disabled={busy}
                onApprove={() => void sim.run("Applying approval: COMMIT, re-plan with receipts, reserve stock…",
                  () => api.approve(attempt.order_id, attempt.attempt_number), { success: "Approved: agreements committed.", trackChange: true })}
                onReject={(reason) => void sim.run("Rejected: aborting agreements and replanning…",
                  () => api.reject(attempt.order_id, attempt.attempt_number, reason), { success: "Rejection recorded." })}
              />
            )}
            <AttemptHistory attempts={s.attempts} />
            {earlier.length > 0 && (
              <details className="card">
                <summary>Earlier attempts' negotiations ({earlier.length})</summary>
                <div className="grid-2" style={{ marginTop: 12 }}>
                  {earlier.flatMap((a) => a.negotiations).map((ref) => s.negotiations[ref.negotiation_id]).filter(Boolean).map((n) => (
                    <NegotiationCard key={n.id} negotiation={n} items={s.items} />
                  ))}
                </div>
              </details>
            )}
          </section>
        )}

        <DecisionLog decisions={s.decisions} />

        <details className="card">
          <summary>Technical details (raw backend state)</summary>
          <pre>{JSON.stringify({ selectedOrder: orderId, orders: s.orders.map((o) => [o.order_number, o.status]), attempts: s.attempts, plans: Object.fromEntries(Object.entries(s.plans).map(([k, p]) => [k, { status: p.status, validation: p.validation }])) }, null, 2)}</pre>
        </details>
      </main>
    </>
  );
}
