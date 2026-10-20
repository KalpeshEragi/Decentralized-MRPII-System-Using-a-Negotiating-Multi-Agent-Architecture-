"use client";
// Brand, simulated day, the clock (Next day / Play / Pause), the AI switch, disruptions, scenarios and runs. Every button
// calls a simulation door; the panel itself decides nothing.

import { useEffect, useState } from "react";
import { api, Live, Scenario } from "@/lib/api";

export function TopBar({ live, onChanged, onError, onDisruptions, onReport }: {
  live: Live | null; onChanged: (reset?: boolean) => void; onError: (message: string) => void;
  onDisruptions: () => void; onReport: (runId: number | null) => void;
}) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [chosen, setChosen] = useState("S1");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<Scenario[]>("/simulation/scenarios").then(setScenarios).catch(() => setScenarios([]));
  }, []);

  async function act(path: string, body: unknown = {}, reset = false) {
    setBusy(true);
    try {
      await api.post(path, body);
      onChanged(reset);
      return true;
    } catch (e) {
      onError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const playing = live?.clock.status === "RUNNING";
  const waiting = live ? Object.values(live.clock.waiting).reduce((a, b) => a + b, 0) : 0;
  const reason = !playing && live?.clock.pause_reason;
  async function finishRun(runId: number) {
    if (await act(`/simulation/runs/${runId}/finish`)) onReport(runId);
  }
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark">◆</div>
        <div>Decentra<small>six agents run the factory</small></div>
      </div>
      <div className="spacer" />
      <span className="pill" title="Simulated day">📅 {live?.clock.day ?? "…"}</span>
      <span className="pill" title={waiting ? `${waiting} work items in progress` : "All agents finished their work"}>
        <span className={`dot ${playing || waiting ? "live" : ""}`} /> {playing ? "Playing" : waiting ? "Working" : "Quiet"}
      </span>
      {reason && <span className="pill paused" title={reason}>⏸ {reason.split(":")[0]}</span>}
      <button className={`switch ${live?.ai_enabled ? "on" : ""}`} disabled={busy || !live}
              title="The shared language model helps agents word messages and rank repair options. Business numbers stay deterministic."
              onClick={() => act("/simulation/settings", { ai_enabled: live?.ai_enabled ? 0 : 1 })}>
        <span className="knob" /> AI {live?.ai_enabled ? "on" : "off"}
      </button>
      <button className="btn" disabled={busy || playing} onClick={() => act("/simulation/clock/next-day")}>Next day ›</button>
      {playing
        ? <button className="btn" disabled={busy} onClick={() => act("/simulation/clock/pause")}>❚❚ Pause</button>
        : <button className="btn primary" disabled={busy} onClick={() => act("/simulation/clock/play")}>▶ Play</button>}
      <select className="btn" value={chosen} onChange={(e) => setChosen(e.target.value)}
              title={scenarios.find((s) => s.name === chosen)?.description}>
        {scenarios.map((s) => <option key={s.name} value={s.name}>{s.name} — {s.description.split(":")[0]}</option>)}
      </select>
      <button className="btn" disabled={busy || playing}
              onClick={() => act(`/simulation/scenarios/${chosen}/start`, { seed: 1 }, true)}>Start scenario</button>
      <button className="btn" onClick={onDisruptions} title="Fire a simulator trigger">⚡ Disruption</button>
      {live?.run
        ? <button className="btn" disabled={busy} onClick={() => finishRun(live.run!.id)}>Finish run {live.run.scenario}</button>
        : <button className="btn" onClick={() => onReport(null)}>📊 Reports</button>}
    </header>
  );
}
