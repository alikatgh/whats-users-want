# 08 — Running It

How to reproduce the analysis or extend it. Every command is one line.

## Prerequisites

- Python virtualenv at `.venv/`. Already set up; if missing: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- Private source export at `data_2may.csv`. It is intentionally ignored by Git because it can contain support-ticket text and identifiers.
- Ollama installed and running. Check with `pgrep -f ollama` (should print a PID).
- Mistral Small 3.2 pulled for new local extraction runs. Check with `ollama list` (should show `mistral-small3.2:24b`).

If Ollama is missing:

```bash
brew install ollama
ollama serve &
ollama pull mistral-small3.2:24b
```

## Full reproduction (one stage at a time)

```bash
# Stage 1 — clean, embed, cluster, score managers
.venv/bin/python scripts/option2_pipeline.py \
  --input data_2may.csv \
  --embedding-backend local \
  --embedding-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

# Stage 2 — BERTopic validation (uses the run dir from Stage 1)
.venv/bin/python scripts/bertopic_from_run.py outputs/option2_<TIMESTAMP>

# Stage 3 — opportunity backlog, personas, evidence gaps
.venv/bin/python scripts/insight_layer.py outputs/option2_<TIMESTAMP>

# Stage 4 — split BERTopic noise bucket into 26 sub-themes
.venv/bin/python scripts/split_outlier_bucket.py outputs/option2_<TIMESTAMP>

# Stage 5 — local LLM extraction (250 rich tickets, Mistral Small 3.2)
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_<TIMESTAMP> \
  --backend ollama \
  --model mistral-small3.2:24b \
  --limit 250 \
  --strategy risk_balanced

# Stage 6 — cluster extracted wants into a taxonomy
.venv/bin/python scripts/build_user_wants_taxonomy.py outputs/option2_<TIMESTAMP>
```

## Common variations

**Skip the local model, just preview the LLM step:**

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_<TIMESTAMP> --dry-run
```

**Free deterministic baseline (no model at all):**

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_<TIMESTAMP> \
  --backend rules --limit 250 --strategy risk_balanced
```

**Force KMeans for the want taxonomy (k=20):**

```bash
.venv/bin/python scripts/build_user_wants_taxonomy.py outputs/option2_<TIMESTAMP> \
  --method kmeans --n-clusters 20
```

**Scale extraction beyond 250 tickets:**

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_<TIMESTAMP> \
  --backend ollama --model mistral-small3.2:24b --limit 1000 --strategy risk_balanced
```

Then rerun Stage 6 — the taxonomy will reflect the larger sample.

**Switch to OpenAI later (if a budget appears):**

```bash
export OPENAI_API_KEY=...
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_<TIMESTAMP> \
  --backend openai --limit 250 --strategy risk_balanced
```

The prompt and schema do not change.

## Useful inspection commands

**Check the latest extraction file row count:**

```bash
wc -l outputs/option2_*/ollama_mistral-small3.2-24b_extractions.jsonl
```

**Open the executive findings:**

```bash
open outputs/option2_*/executive_findings.md
```

**Open the interactive ticket map:**

```bash
open outputs/option2_*/semantic_ticket_map.html
```

**Query the analytical database directly:**

```bash
.venv/bin/python -c "
import duckdb
con = duckdb.connect('outputs/option2_20260502_150055/analysis.duckdb', read_only=True)
print(con.execute(\"SELECT table_name FROM information_schema.tables ORDER BY 1\").fetchall())
"
```

## Run-time expectations on a laptop

| Stage | Time | Notes |
|---|---|---|
| 1 | 3-5 min | First run downloads the embedding model (~480 MB) |
| 2 | 1-2 min | Reuses Stage 1 embeddings |
| 3 | 30-60 s | Statistical only |
| 4 | 1-2 min | Reuses Stage 1 embeddings |
| 5 (250 tickets, mistral-small3.2:24b) | 20-60 min | Bottleneck is local model inference and GPU speed |
| 6 | 30 s | 250 short texts |

## Where things land

Every full run creates a self-contained directory:

```
outputs/option2_<TIMESTAMP>/
├── enriched_tickets.csv
├── semantic_clusters.csv
├── ...
├── ollama_mistral-small3.2-24b_extractions.csv
├── user_wants_taxonomy.csv
├── analysis.duckdb
└── executive_findings.md
```

You can compare runs by diffing two folders. Old runs are not deleted automatically.

## Troubleshooting

**"ollama: command not found"** → Install via `brew install ollama` and `ollama serve`.

**"Connection refused on localhost:11434"** → Ollama daemon is not running. `ollama serve &`.

**"model 'mistral-small3.2:24b' not found"** → `ollama pull mistral-small3.2:24b`.

**HDBSCAN gives mostly -1 outliers in Stage 6** → The script auto-falls-back to KMeans. If you forced HDBSCAN, lower `--min-cluster-size` or switch to `--method kmeans`.

**"NaN" in the manager regression p-values** → The baseline manager has p=NaN by definition (it is the reference). Look at the other rows.

**Pipeline hangs on embedding** → First run downloads the model from HuggingFace (~480 MB). Subsequent runs are cached.
