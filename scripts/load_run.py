"""Run one load scenario on the running demo backend and print its measurements (ROADMAP step 8).

    python scripts/load_run.py LOAD-10 [--url http://localhost:8000] [--out load_runs/LOAD-10.json]

It does what the panel does, through the simulation and observer doors only: finish an open run, start the scenario,
press Play, wait until Play pauses by itself (nothing left to do) or stops (a day did not become quiet), finish the
run, read its measurements. The real background workers do the work, so the numbers include real concurrency.
Door key: DEMO_KEY (default local-demo-key), the same as the backend's SIMULATION_DOOR_KEY. Standard library only.
"""

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path


def call(base: str, method: str, path: str, body: dict | None = None) -> dict | list:
    request = urllib.request.Request(f"{base}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json",
                                              "X-Door-Key": os.environ.get("DEMO_KEY", "local-demo-key")})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read() or b"{}")


def run(base: str, scenario: str, poll_seconds: float, limit_minutes: float) -> dict:
    for open_run in (r for r in call(base, "GET", "/simulation/runs") if r["status"] == "RUNNING"):
        call(base, "POST", "/simulation/clock/pause")
        call(base, "POST", f"/simulation/runs/{open_run['id']}/finish")
    started = call(base, "POST", f"/simulation/scenarios/{scenario}/start", {"seed": 1})
    began = time.monotonic()
    call(base, "POST", "/simulation/clock/play")
    clock = {}
    while time.monotonic() - began < limit_minutes * 60:
        time.sleep(poll_seconds)
        clock = call(base, "GET", "/simulation/clock")
        print(f"  {time.monotonic() - began:7.0f} s  day {clock['current_day']}  {clock['status']}  "
              f"waiting {sum(clock['waiting'].values())}", flush=True)
        if clock["status"] == "PAUSED":
            break
    else:
        call(base, "POST", "/simulation/clock/pause")
        clock["pause_reason"] = f"stopped by the script after {limit_minutes} minutes"
    seconds = round(time.monotonic() - began, 1)
    call(base, "POST", f"/simulation/runs/{started['run_id']}/finish")
    measured = call(base, "GET", f"/simulation/runs/{started['run_id']}/report")["measurements"]
    return {"scenario": scenario, "run_id": started["run_id"], "real_seconds": seconds,
            "simulated_days": measured["days"]["count"], "ended": clock.get("pause_reason"), "measurements": measured}


def summary(result: dict) -> str:
    m = result["measurements"]
    orders, days, ai = m["orders"], m["days"], m["ai_calls"]
    lines = [f"{result['scenario']}: {orders['total']} orders in {result['real_seconds']} s real time, "
             f"{result['simulated_days']} simulated days ({result['ended']})",
             f"  orders by status: {orders['by_status']}",
             f"  completed {orders['completed']}, on time {orders['completed_on_time']} ({orders['on_time_percent']}%)",
             f"  request -> committed (s): {orders['seconds_request_to_committed']}",
             f"  one simulated day (s): p50 {days['p50']}, p95 {days['p95']}, max {days['max']}",
             f"  event delivery lag (s): {m['event_delivery']['seconds_lag']}, failed {m['event_delivery']['failed']}",
             f"  negotiations: {m['negotiations']['by_status']}, open -> closed (s) "
             f"{m['negotiations']['seconds_open_to_closed']}",
             f"  AI calls: {ai['by_outcome'] or 'none (AI off)'}"]
    failed = {q: v["failed"] for q, v in m["queues"].items() if v["failed"]}
    lines.append(f"  failed work items: {failed or 'none'}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--out", help="write the full result as JSON here")
    parser.add_argument("--poll", type=float, default=5)
    parser.add_argument("--limit-minutes", type=float, default=60)
    args = parser.parse_args()
    result = run(args.url, args.scenario, args.poll, args.limit_minutes)
    print(summary(result))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
