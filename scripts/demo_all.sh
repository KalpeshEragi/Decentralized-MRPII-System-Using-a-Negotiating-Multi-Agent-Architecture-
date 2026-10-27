#!/usr/bin/env bash
# Start the whole local demo from one Git Bash terminal: the local PostgreSQL, the backend (port 8000, its output in
# ~/decentra-backend.log) and the frontend (port 3005, in this terminal). Ctrl+C stops the frontend and the backend; the database
# keeps running (stop it with: bash ~/decentra-postgres/stop.sh).
#   DECENTRA_ENV, DEMO_KEY, PORT   passed on to demo_backend.sh / demo_frontend.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PG_DIR="$(dirname "${DECENTRA_ENV:-$HOME/decentra-postgres/local.env}")"
LOG="$HOME/decentra-backend.log"

echo "1/3 database"
READY="$PG_DIR/pgsql/bin/pg_isready.exe"
if [ -x "$READY" ] && "$READY" -h 127.0.0.1 -p 5433 -q; then
  echo "    already running"
else
  bash "$PG_DIR/start.sh" || true
  if [ -x "$READY" ] && ! "$READY" -h 127.0.0.1 -p 5433 -q; then
    echo "the database does not answer on port 5433. If a stuck postgres holds the port, stop it (Task Manager →"
    echo "postgres.exe), delete $PG_DIR/data/postmaster.pid and run this script again."
    exit 1
  fi
fi

if curl -s -o /dev/null --max-time 2 http://localhost:8000/health; then
  echo "a backend is already running on port 8000: stop it first (one backend at a time)"; exit 1
fi

echo "2/3 backend (output in $LOG)"
bash "$ROOT/scripts/demo_backend.sh" > "$LOG" 2>&1 &
BACKEND=$!
stop_backend() {
  echo; echo "stopping backend"
  kill $BACKEND 2>/dev/null || true
  # uvicorn is a Windows process: also stop whatever still listens on port 8000
  for pid in $(netstat -ano | grep -E ':8000 .*LISTENING' | awk '{print $NF}' | sort -u); do taskkill //F //T //PID "$pid" > /dev/null 2>&1 || true; done
}
trap stop_backend EXIT
for _ in $(seq 1 60); do
  curl -s -o /dev/null --max-time 2 http://localhost:8000/health && break
  kill -0 $BACKEND 2>/dev/null || { echo "backend stopped; last lines of $LOG:"; tail -20 "$LOG"; exit 1; }
  sleep 2
done
curl -s -o /dev/null --max-time 2 http://localhost:8000/health || { echo "backend did not start; see $LOG"; exit 1; }
echo "    backend ready on http://localhost:8000"

echo "3/3 frontend → http://localhost:${PORT:-3005}  (Ctrl+C stops frontend and backend)"
bash "$ROOT/scripts/demo_frontend.sh"
