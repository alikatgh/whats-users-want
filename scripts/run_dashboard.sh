#!/usr/bin/env bash
# Launch the Streamlit dashboard.
#
# Once running, open: http://localhost:8501
# The sidebar lets you switch between pages and pick a run directory.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8501}"

if [ ! -x .venv/bin/streamlit ]; then
  echo "streamlit not found. Install with: .venv/bin/pip install streamlit"
  exit 1
fi

exec .venv/bin/streamlit run scripts/dashboard/app.py \
  --server.port "$PORT" \
  --server.address localhost \
  --browser.gatherUsageStats false \
  --server.runOnSave true
