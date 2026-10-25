"use client";
// The Decentra control panel: top bar, the living 3D factory with floating cards, and the agent conversation.

import dynamic from "next/dynamic";
import { useState } from "react";
import { AgentChat } from "@/components/AgentChat";
import { CustomersPanel } from "@/components/CustomersPanel";
import { NewOrderPanel } from "@/components/NewOrderPanel";
import { Disruptions } from "@/components/Disruptions";
import { AlertFeed, DetailCard, DocksPanel, KpiCards, OrderTracker, Selection } from "@/components/Overlays";
import { RunReport } from "@/components/RunReport";
import { TopBar } from "@/components/TopBar";
import { OrderStoryView } from "@/components/story/OrderStoryView";
import { useLive } from "@/lib/useLive";

// WebGL runs in the browser only.
const FactoryScene = dynamic(() => import("@/components/scene/FactoryScene").then((m) => m.FactoryScene), { ssr: false });

export default function Page() {
  const { live, items, error, refresh, reset } = useLive();
  const [selection, setSelection] = useState<Selection>(null);
  const [focusOrder, setFocusOrder] = useState<string | null>(null);
  const [storyOrder, setStoryOrder] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [panel, setPanel] = useState<"disruptions" | "customers" | "order" | null>(null);
  const [report, setReport] = useState<{ runId: number | null } | null>(null);
  const waiting = live ? Object.entries(live.clock.waiting) : [];

  return (
    <div className="app">
      <TopBar live={live} onError={(m) => { setActionError(m); setTimeout(() => setActionError(null), 6000); }}
              onChanged={(fresh) => { if (fresh) { reset(); setFocusOrder(null); setStoryOrder(null); setSelection(null); } refresh(); }}
              onDisruptions={() => setPanel((p) => (p === "disruptions" ? null : "disruptions"))}
              onCustomers={() => setPanel((p) => (p === "customers" ? null : "customers"))}
              onNewOrder={() => setPanel((p) => (p === "order" ? null : "order"))}
              onReport={(runId) => setReport({ runId })} />
      <div className="main">
        <div className="stage">
          <FactoryScene live={live} items={items} onSelect={setSelection} />
          <KpiCards live={live} />
          <DetailCard live={live} selection={selection} onClose={() => setSelection(null)} />
          {panel === "disruptions" && <Disruptions live={live} onClose={() => setPanel(null)} onFired={refresh} />}
          {panel === "customers" && <CustomersPanel onClose={() => setPanel(null)} onSaved={refresh} />}
          {panel === "order" && <NewOrderPanel live={live} onClose={() => setPanel(null)} onAdded={refresh} />}
          <AlertFeed items={items} />
          {waiting.length > 0 && (
            <div className="card waiting">⏳ Agents working: {waiting.map(([q, n]) => `${q.split(".")[1]} ${n}`).join(" · ")}</div>
          )}
          <div className="bottom">
            <OrderTracker live={live} onFocusCase={(id) => { setFocusOrder(id); setStoryOrder(id); }} />
            <DocksPanel live={live} onSelect={setSelection} />
          </div>
          {storyOrder && <OrderStoryView demandId={storyOrder} live={live} items={items} onClose={() => setStoryOrder(null)} />}
          {(error || actionError) && <div className="toast">{actionError ?? error}</div>}
        </div>
        <AgentChat live={live} items={items} focusOrder={focusOrder} onFocusOrder={setFocusOrder} onOpenStory={setStoryOrder}
                   names={Object.fromEntries((live?.stock ?? []).map((s) => [s.item_id, s.sku]))} />
      </div>
      {report && <RunReport runId={report.runId} onClose={() => setReport(null)} />}
    </div>
  );
}
