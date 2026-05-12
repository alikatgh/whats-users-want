#!/usr/bin/env bash
# Ask a local Ollama model to write friendly titles for each user-want cluster in the
# latest run. Writes user_wants_human_labels.csv into that run directory.
#
# Usage:
#   ./scripts/label_user_wants.sh                    # latest run, mistral-small3.2:24b
#   ./scripts/label_user_wants.sh outputs/option2_X  # specific run
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_DIR="${1:-}"
if [ -z "$RUN_DIR" ]; then
  RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)
fi

if [ ! -d "$RUN_DIR" ]; then
  echo "Run directory not found: $RUN_DIR"
  exit 1
fi

if ! pgrep -f "ollama" >/dev/null; then
  echo "Ollama is not running. Start it with: ollama serve &"
  exit 1
fi

exec .venv/bin/python scripts/label_user_wants.py "$RUN_DIR" --model mistral-small3.2:24b
