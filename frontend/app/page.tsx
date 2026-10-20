"use client";
// The Decentra control panel: top bar, the living 3D factory with floating cards, and the agent conversation.

import dynamic from "next/dynamic";
import { useState } from "react";
import { AgentChat } from "@/components/AgentChat";
import { DetailCard, DocksPanel, KpiCards, OrderTracker, Selection } from "@/components/Overlays";
import { TopBar } from "@/components/TopBar";
import { useLive } from "@/lib/useLive";

// WebGL runs in the browser only.
const FactoryScene = dynamic(() => import("@/components/scene/FactoryScene").then((m) => m.FactoryScene), { ssr: false });

export default function Page() {
  const { live, items, error, refresh, reset } = useLive();
  const [selection, setSelection] = useState<Selection>(null);
  const [focusCase, setFocusCase] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const waiting = live ? Object.entries(live.clock.waiting) : [];

  return (
    <div className="app">
      <TopBar live={live} onError={(m) => { setActionError(m); setTimeout(() => setActionError(null), 6000); }}
              onChanged={(fresh) => { if (fresh) { reset(); setFocusCase(null); setSelection(null); } refresh(); }} />
      <div className="main">
        <div className="stage">
          <FactoryScene live={live} items={items} onSelect={setSelection} />
          <KpiCards live={live} />
          <DetailCard live={live} selection={selection} onClose={() => setSelection(null)} />
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
    </div>
  );
}
