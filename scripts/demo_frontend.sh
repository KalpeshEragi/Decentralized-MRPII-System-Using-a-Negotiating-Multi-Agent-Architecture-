#!/usr/bin/env bash
# Start the Decentra panel on http://localhost:${PORT:-3005}, talking to the backend on BACKEND_URL
# (default http://localhost:8000). DEMO_KEY must match the backend's (default: local-demo-key).
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)/frontend"
[ -d node_modules ] || npm install
export NEXT_PUBLIC_SIMULATION_DOOR_KEY="${DEMO_KEY:-local-demo-key}"
exec npx next dev -p "${PORT:-3005}"
