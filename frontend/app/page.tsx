"use client";
// The Decentra control panel: top bar, the living 3D factory with floating cards, and the agent conversation.

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { AgentChat } from "@/components/AgentChat";
import { CustomersPanel } from "@/components/CustomersPanel";
import { NewOrderPanel } from "@/components/NewOrderPanel";
import { Disruptions } from "@/components/Disruptions";
import { AlertFeed, DetailCard, DocksPanel, OrderTracker, Selection } from "@/components/Overlays";
import { AgentBoard } from "@/components/cockpit/AgentBoard";
import { AgentDetail } from "@/components/cockpit/AgentDetail";
import { Cockpit } from "@/components/cockpit/Cockpit";
import { IncidentView } from "@/components/cockpit/IncidentView";
import { PlanCompare } from "@/components/cockpit/PlanCompare";
import { AgentCode, agentViews, incidents as findIncidents, planComparisons } from "@/lib/insight";
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
  const [agentOpen, setAgentOpen] = useState<AgentCode | null>(null);
  const [view, setView] = useState<"incidents" | "plans" | null>(null);
  const views = useMemo(() => agentViews(live, items), [live, items]);
  const incidents = useMemo(() => findIncidents(items, live), [items, live]);
  const comparisons = useMemo(() => planComparisons(items, live), [items, live]);
  const names = useMemo(() => Object.fromEntries((live?.stock ?? []).map((s) => [s.item_id, s.sku])), [live]);
  // The agents of the newest disruption are marked on the board and in the 3D town until it is fully resolved.
  const latest = incidents[incidents.length - 1];
  const involved = useMemo(() => {
    if (!latest) return {};
    return Object.fromEntries(latest.agents.map((c) => [c, c === latest.origin ? "origin" : "involved"])) as
      Partial<Record<AgentCode, "origin" | "involved">>;
  }, [latest]);
  const openStory = (id: string) => { setView(null); setAgentOpen(null); setStoryOrder(id); };

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
          <FactoryScene live={live} items={items} onSelect={setSelection} involved={involved} onAgent={setAgentOpen} />
          <Cockpit live={live} incidents={incidents} comparisons={comparisons}
                   onIncidents={() => setView((v) => (v === "incidents" ? null : "incidents"))}
                   onPlans={() => setView((v) => (v === "plans" ? null : "plans"))} />
          <AgentBoard views={views} involved={involved} onOpen={setAgentOpen} />
          {agentOpen && <AgentDetail view={views.find((v) => v.code === agentOpen)!} live={live} items={items}
                                     onClose={() => setAgentOpen(null)} onOpenStory={openStory} />}
          {view === "incidents" && <IncidentView incidents={incidents} names={names} onClose={() => setView(null)} onOpenStory={openStory} />}
          {view === "plans" && <PlanCompare comparisons={comparisons} onClose={() => setView(null)} onOpenStory={openStory} />}
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
                   names={names} />
      </div>
      {report && <RunReport runId={report.runId} onClose={() => setReport(null)} />}
    </div>
  );
}
