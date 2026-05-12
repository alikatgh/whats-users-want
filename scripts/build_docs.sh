#!/usr/bin/env bash
# Build the full documentation site:
#   1. Generate Python API docs (pdoc) into docs/api/
#   2. Build MkDocs Material site into site/
#   3. Copy scripts/ and, when present, outputs/ into site/ so relative links work locally
# After it finishes:
#   open site/index.html
set -euo pipefail

cd "$(dirname "$0")/.."

PDOC=".venv/bin/pdoc"
MKDOCS=".venv/bin/mkdocs"

if [ ! -x "$PDOC" ]; then
  echo "pdoc not found; run: .venv/bin/pip install pdoc"
  exit 1
fi
if [ ! -x "$MKDOCS" ]; then
  echo "mkdocs not found; run: .venv/bin/pip install mkdocs mkdocs-material pymdown-extensions"
  exit 1
fi

echo "==> Generating API docs (pdoc) -> docs/api/"
mkdir -p docs/api
"$PDOC" \
  scripts/option2_pipeline.py \
  scripts/bertopic_from_run.py \
  scripts/insight_layer.py \
  scripts/split_outlier_bucket.py \
  scripts/llm_extract_rich_tickets.py \
  scripts/build_user_wants_taxonomy.py \
  scripts/label_user_wants.py \
  --output-directory docs/api \
  --docformat google \
  > /dev/null

echo "==> Linking 101 course into docs/"
if [ ! -L docs/101 ] && [ ! -d docs/101 ]; then
  ln -s ../101 docs/101
fi

echo "==> Building MkDocs Material site -> site/"
"$MKDOCS" build --quiet

echo "==> Copying scripts/ and local outputs into site/ for working relative links"
rm -rf site/scripts site/outputs
cp -R scripts site/scripts
if [ -d outputs ]; then
  cp -R outputs site/outputs
else
  echo "outputs/ not found; built docs without local analysis artifacts"
fi

echo
echo "Done. Open: site/index.html"
echo "Live preview: .venv/bin/mkdocs serve"
