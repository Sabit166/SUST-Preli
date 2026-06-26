#!/usr/bin/env bash
# Launch the SUST-Preli FastAPI service.
# Usage: ./run.sh [host] [port]   (defaults: 0.0.0.0 8000)

set -euo pipefail

HOST="${1:-0.0.0.0}"
PORT="${2:-8000}"

# Always cd into this script's directory so `main:app` resolves.
cd "$(dirname "$0")"

echo "[run.sh] cwd       = $(pwd)"
echo "[run.sh] launching uvicorn on http://${HOST}:${PORT}"

exec uvicorn main:app --host "$HOST" --port "$PORT"