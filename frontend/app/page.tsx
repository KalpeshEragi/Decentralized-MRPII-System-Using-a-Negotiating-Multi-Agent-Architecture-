"use client";
// The Decentra control panel: top bar, the living 3D factory with floating cards, and the agent conversation.

import dynamic from "next/dynamic";
import { useState } from "react";
import { AgentChat } from "@/components/AgentChat";
import { Disruptions } from "@/components/Disruptions";
import { AlertFeed, DetailCard, DocksPanel, KpiCards, OrderTracker, Selection } from "@/components/Overlays";
import { RunReport } from "@/components/RunReport";
import { TopBar } from "@/components/TopBar";
import { useLive } from "@/lib/useLive";

// WebGL runs in the browser only.
const FactoryScene = dynamic(() => import("@/components/scene/FactoryScene").then((m) => m.FactoryScene), { ssr: false });

export default function Page() {
  const { live, items, error, refresh, reset } = useLive();
  const [selection, setSelection] = useState<Selection>(null);
  const [focusCase, setFocusCase] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [disrupting, setDisrupting] = useState(false);
  const [report, setReport] = useState<{ runId: number | null } | null>(null);
  const waiting = live ? Object.entries(live.clock.waiting) : [];

  return (
    <div className="app">
      <TopBar live={live} onError={(m) => { setActionError(m); setTimeout(() => setActionError(null), 6000); }}
              onChanged={(fresh) => { if (fresh) { reset(); setFocusCase(null); setSelection(null); } refresh(); }}
              onDisruptions={() => setDisrupting((d) => !d)} onReport={(runId) => setReport({ runId })} />
      <div className="main">
        <div className="stage">
          <FactoryScene live={live} items={items} onSelect={setSelection} />
          <KpiCards live={live} />
          <DetailCard live={live} selection={selection} onClose={() => setSelection(null)} />
          {disrupting && <Disruptions live={live} onClose={() => setDisrupting(false)} onFired={refresh} />}
          <AlertFeed items={items} />
          {waiting.length > 0 && (
            <div className="card waiting">⏳ Agents working: {waiting.map(([q, n]) => `${q.split(".")[1]} ${n}`).join(" · ")}</div>
          )}
          <div className="bottom">
            <OrderTracker live={live} onFocusCase={setFocusCase} />
            <DocksPanel live={live} onSelect={setSelection} />
          </div>
          {(error || actionError) && <div className="toast">{actionError ?? error}</div>}
        </div>
        <AgentChat items={items} focusCase={focusCase} onFocusCase={setFocusCase}
                   names={Object.fromEntries((live?.stock ?? []).map((s) => [s.item_id, s.sku]))} />
      </div>
      {report && <RunReport runId={report.runId} onClose={() => setReport(null)} />}
    </div>
  );
}
