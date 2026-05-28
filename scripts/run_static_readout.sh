#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="${STATIC_READOUT_DIR:-$ROOT/outputs/static_what_users_want}"
PORT="${1:-38484}"

if [[ ! -f "$SITE_DIR/index.html" ]]; then
  echo "Missing generated static readout index: $SITE_DIR/index.html" >&2
  echo "Build the package first with:" >&2
  echo "  python3 scripts/export_static_readout.py outputs/option2_20260513_030517 --force" >&2
  exit 1
fi

if [[ ! -f "$SITE_DIR/data/user_wants_all_assignments.csv" ]]; then
  echo "Missing generated static readout data folder: $SITE_DIR/data/" >&2
  echo "Build the package first with:" >&2
  echo "  python3 scripts/export_static_readout.py outputs/option2_20260513_030517 --force" >&2
  exit 1
fi

echo "Serving What Users Want static readout"
echo "Folder: $SITE_DIR"
echo "URL:    http://127.0.0.1:$PORT/"
echo
python3 -m http.server --bind 127.0.0.1 --directory "$SITE_DIR" "$PORT"
