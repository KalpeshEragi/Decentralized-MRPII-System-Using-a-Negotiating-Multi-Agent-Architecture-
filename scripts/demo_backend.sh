#!/usr/bin/env bash
# Start the demo backend on the local demo database (DB-1): migrations to head, then the API with background workers
# on http://localhost:8000. The connection string comes from the local PostgreSQL's env file and is never printed.
#   DECENTRA_ENV  env file with DEMO_DATABASE_URL (default: ~/decentra-postgres/local.env)
#   PYTHON        the backend's Python (default: backend/.venv/Scripts/python.exe, else python)
#   DEMO_KEY      door key shared with the frontend (default: local-demo-key; local use only)
#   RELOAD=1      restart the API by itself whenever a file under backend/app changes (for development)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${DECENTRA_ENV:-$HOME/decentra-postgres/local.env}"
[ -f "$ENV_FILE" ] || { echo "no env file at $ENV_FILE (set DECENTRA_ENV)"; exit 1; }
[ -f "$(dirname "$ENV_FILE")/start.sh" ] && bash "$(dirname "$ENV_FILE")/start.sh" > /dev/null
PY="${PYTHON:-$ROOT/backend/.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY=python

export DATABASE_URL="$(grep -m1 '^DEMO_DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)"
KEY="${DEMO_KEY:-local-demo-key}"
export SIMULATION_DOOR_KEY="$KEY" PLANNING_DOOR_KEY="$KEY" SALES_PLANNING_KEY="$KEY"
export PLANNING_CONNECTOR=real A2A_BASE_URL=http://127.0.0.1:8000 BACKGROUND_WORKERS=true PYTHONIOENCODING=utf-8

cd "$ROOT/backend"
"$PY" -c "from alembic.config import Config; from alembic import command; command.upgrade(Config('alembic.ini'), 'head')"
RELOAD_ARGS=()
[ "${RELOAD:-0}" = "1" ] && RELOAD_ARGS=(--reload --reload-dir app)
exec "$PY" -m uvicorn app.main:app --port 8000 "${RELOAD_ARGS[@]}"
