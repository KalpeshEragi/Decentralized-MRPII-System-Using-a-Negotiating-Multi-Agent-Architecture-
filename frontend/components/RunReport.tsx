"use client";
// A finished run's report (demo.md §12): the metrics the backend saved when the run was finished. Read only.

import { useEffect, useState } from "react";
import { api, RunReport as Report, RunSummary } from "@/lib/api";

export function RunReport({ runId, onClose }: { runId: number | null; onClose: () => void }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [chosen, setChosen] = useState<number | null>(runId);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<RunSummary[]>("/simulation/runs").then((all) => {
      const finished = all.filter((r) => r.status === "FINISHED");
      setRuns(finished);
      setChosen((c) => c ?? finished[0]?.id ?? null);
    }).catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (chosen == null) return;
    setReport(null);
    api.get<Report>(`/simulation/runs/${chosen}/report`).then(setReport).catch((e) => setError((e as Error).message));
  }, [chosen]);

  const m = report?.metrics;
  const sorted = (counts: Record<string, number> = {}) => Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="card modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        <div className="kind">Run report</div>
        <div className="modal-head">
          <h3>{report ? `Run ${report.run.id} · ${report.run.scenario}` : "Run report"}</h3>
          {runs.length > 1 && (
            <select className="btn" value={chosen ?? ""} onChange={(e) => setChosen(Number(e.target.value))}>
              {runs.map((r) => <option key={r.id} value={r.id}>Run {r.id} · {r.scenario}</option>)}
            </select>
          )}
        </div>
        {error && <div className="badge red">{error}</div>}
        {!error && chosen == null && <p className="help">No finished run yet. Start a scenario, play it, then finish the run.</p>}
        {chosen != null && !report && !error && <p className="help">Loading…</p>}
        {report && m && (<>
          <p className="help">Simulated days {report.run.start_day} → {report.run.end_day ?? "…"} · seed {report.run.seed}</p>
          <div className="report-kpis">
            <div><b>{m.orders}</b><span>orders</span></div>
            <div><b>{m.completed}</b><span>completed</span></div>
            <div><b>{m.completed ? `${Math.round((100 * m.completed_on_time) / m.completed)}%` : "–"}</b><span>on time</span></div>
            <div><b>{m.plan_at_risk_events}</b><span>plans at risk</span></div>
          </div>
          <div className="report-cols">
            <section><h4>Orders by status</h4>
              {sorted(m.orders_by_status).map(([k, v]) => <div className="row" key={k}><span>{k}</span><span>{v}</span></div>)}
              <h4>Triggers</h4>
              {report.triggers.length === 0 && <p className="help">None</p>}
              {report.triggers.map((t, i) => (
                <div className="row" key={i}><span>{t.kind.toLowerCase().replaceAll("_", " ")}</span>
                  <span className={`badge ${t.status === "DONE" ? "green" : t.status === "FAILED" ? "red" : ""}`}>{t.status}</span></div>
              ))}
              <h4>AI calls</h4>
              {sorted(m.ai_calls_by_outcome).length === 0 && <p className="help">None (AI off)</p>}
              {sorted(m.ai_calls_by_outcome).map(([k, v]) => <div className="row" key={k}><span>{k}</span><span>{v}</span></div>)}
            </section>
            <section><h4>Events published</h4>
              {sorted(m.events_by_type).map(([k, v]) => <div className="row" key={k}><span>{k}</span><span>{v}</span></div>)}
            </section>
          </div>
        </>)}
      </div>
    </div>
  );
}
