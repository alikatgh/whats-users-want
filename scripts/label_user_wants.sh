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
  if [ ! -d outputs ]; then
    echo "No outputs/ directory found. Run the pipeline first:" >&2
    echo "  .venv/bin/python scripts/option2_pipeline.py --input data_2may.csv" >&2
    exit 1
  fi
  RUN_DIR=$(find outputs -maxdepth 1 -type d -name 'option2_*' | sort | tail -n 1)
  if [ -z "$RUN_DIR" ]; then
    echo "No outputs/option2_* run directories found. Run the pipeline first:" >&2
    echo "  .venv/bin/python scripts/option2_pipeline.py --input data_2may.csv" >&2
    exit 1
  fi
fi
MODEL="${OLLAMA_MODEL:-mistral-small3.2:24b}"

if [ ! -d "$RUN_DIR" ]; then
  echo "Run directory not found: $RUN_DIR" >&2
  exit 1
fi

exec .venv/bin/python scripts/label_user_wants.py "$RUN_DIR" --model "$MODEL"
