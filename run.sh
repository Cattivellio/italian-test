#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "→ Creating virtual environment…"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ Installing / updating dependencies…"
pip install --quiet --upgrade -r requirements.txt

# 0.0.0.0 so the app is reachable from other devices on the LAN (e.g. the phone).
HOST="${ITALIAN_TEST_HOST:-0.0.0.0}"
PORT="${ITALIAN_TEST_PORT:-8050}"

echo "→ Starting Italian Test on http://${HOST}:${PORT}"
echo "  → On your phone open: http://$(hostname -I | awk '{print $1}'):${PORT}"
exec uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload
