# 00 — Architecture

## Repository layout

```
2026-what-users/
├── data_2may.csv                 # input: 6,728 support tickets
├── requirements.txt              # Python dependencies
├── .venv/                        # Python virtual environment
├── scripts/                      # six pipeline stages
│   ├── option2_pipeline.py       # Stage 1: clean, embed, cluster, manager scoring
│   ├── bertopic_from_run.py      # Stage 2: BERTopic validation
│   ├── insight_layer.py          # Stage 3: opportunities, personas, stats
│   ├── split_outlier_bucket.py   # Stage 4: split BERTopic noise into 26 sub-themes
│   ├── llm_extract_rich_tickets.py # Stage 5: local Ollama extraction
│   ├── build_user_wants_taxonomy.py # Stage 6: cluster extracted wants into 17 labels
│   └── r_validation.R            # optional R-side validation scaffold (unused in current run)
├── outputs/                      # one folder per run (timestamped)
│   └── option2_20260502_150055/  # latest run
└── docs/                         # this documentation
    ├── README.md                 # high-level docs index
    └── engineering/              # this folder — engineering deep-dives
```

## Data flow

```
data_2may.csv
   │
   │ (Python, pandas dtype=str so nothing gets coerced unexpectedly)
   ▼
read_raw_csv → canonicalize → featurize_tickets
   │
   │ enriched_tickets DataFrame: 6,728 rows × ~60 columns (raw + 10 evidence flags + 10 desire flags + context_depth_score + ...)
   ▼
embed_texts (sentence-transformers, 384-dim local)
   │
   │ embeddings_local.npy: shape (6728, 384), float32, normalized
   ▼
UMAP → 2-dim coords + 10-dim cluster space
   │
   ▼
HDBSCAN (with KMeans fallback) → cluster_id per ticket
   │
   ├──> Stage 2: BERTopic on the same embeddings → 53 topics + topic -1
   │       │
   │       ▼
   │     Stage 3: insight_layer reads enriched_tickets + bertopic_assignments → opportunity_backlog, personas, stats
   │       │
   │       ▼
   │     Stage 4: split_outlier_bucket isolates topic -1 (1,331 rows) and KMeans-splits into 26 sub-themes
   │
   └──> Stage 5: llm_extract_rich_tickets samples 250 candidates by (context_depth_score >= 24) + risk
           │
           │ Local HTTP POST to Ollama (localhost:11434/api/chat)
           │ format=json, temperature=0, num_ctx=8192
           ▼
         ollama_gemma3-4b_extractions.jsonl (one line per ticket, valid JSON)
           │
           ▼
         Stage 6: build_user_wants_taxonomy
           │
           │ embed [actual_user_want | job | product_opportunity | literal_request]
           │ HDBSCAN attempt → fallback to KMeans (k=17 here)
           ▼
         user_wants_taxonomy.csv (17 wants) + user_wants_assignments.csv (250 tickets)
```

## Key architectural decisions

### 1. One self-contained run directory per execution

Every full run creates `outputs/option2_<TIMESTAMP>/`. All artifacts land there. No global state, no overwrites across runs. You can keep multiple runs side-by-side and diff.

### 2. Cache embeddings on disk

Embedding 6,728 tickets through MiniLM takes ~3 minutes. The result is saved as `embeddings_local.npy` (about 10 MB). Stages 2, 4, and 6 all reload this file rather than re-embedding. Stage 6 has its own embedding step but only on 250 short LLM-extracted strings, so it does not reuse the cache.

### 3. Three storage formats per table

Each DataFrame is written to:
- **CSV** for human inspection and Excel.
- **Parquet** under `parquet/` for fast Python/R/Julia/DuckDB joins.
- **DuckDB** in `analysis.duckdb` for SQL queries.

Cost: ~3× disk for tables. Benefit: zero friction for any consumer language.

### 4. Pure-Python, all local, all CPU

No GPU required. No API keys required. The only network calls in the entire pipeline are:

- (Stage 1 first run) HuggingFace download of MiniLM — 480 MB, cached after first run.
- (Stage 5) HTTP POST to `localhost:11434` (Ollama daemon).

### 5. Markdown-first reporting

`executive_findings.md` is appended to by every stage. It is the single human-readable narrative artifact. Excel workbooks and CSVs are for drilling down.

### 6. Soft-fail on optional dependencies

Several heavy libraries are wrapped in try/except:

- `umap-learn` — if missing, clustering happens in raw embedding space.
- `hdbscan` — if missing, falls back to MiniBatchKMeans.
- `statsmodels` — if missing, the adjusted manager model and context-value model are skipped with a note.
- `networkx` — if missing, the desire/category co-occurrence graph is skipped.
- `plotly` — if missing, interactive maps are skipped.
- `matplotlib` / `seaborn` — if missing, charts skipped.

This means a partial install still produces usable CSVs and an executive summary.

## Dependencies

From [requirements.txt](../../requirements.txt):

| Package | Used for |
|---|---|
| `pandas`, `numpy` | core dataframe operations |
| `scikit-learn` | TF-IDF, TruncatedSVD, KMeans, MiniBatchKMeans, silhouette_score |
| `sentence-transformers` | local multilingual embeddings |
| `umap-learn` | dimensionality reduction for clustering and visualization |
| `hdbscan` | density-based clustering |
| `bertopic` | topic modeling with c-TF-IDF |
| `statsmodels` | OLS / logit regressions for manager and context models |
| `plotly` | interactive HTML maps |
| `matplotlib`, `seaborn` | static PNG charts |
| `openpyxl` | writing .xlsx workbooks |
| `duckdb`, `pyarrow` | analytical store and Parquet IO |
| `networkx` | desire/category co-occurrence graph |

External (not pip):
- **Ollama** — local LLM runtime, listening on `localhost:11434`.
- **Local Ollama model** — `mistral-small3.2:24b` is the new default; the original run used `gemma3:4b`.

## Run conventions

- **Working directory:** the project root, e.g. `cd 2026-what-users && .venv/bin/python scripts/...`.
- **Run-dir argument:** every downstream stage takes a positional `run_dir` argument like `outputs/option2_20260502_150055`.
- **`--dry-run` is honored only in Stage 5.** Stages 1-4 and 6 always execute.
- **Resume support is only in Stage 5.** Stage 5 reads `<output_stem>.jsonl` and skips already-processed `source_row` values. To force a clean run, pass `--no-resume`.

## Naming conventions

- `enriched_tickets.csv` — every ticket with all derived features. The single source of truth for downstream stages.
- `semantic_cluster_assignments.csv` — per-ticket cluster_id + 2D coordinates (Stage 1 clustering).
- `bertopic_assignments.csv` — per-ticket BERTopic topic + label.
- `outlier_subtopic_assignments.csv` — per-ticket outlier sub-theme (only the 1,331 tickets in BERTopic topic -1).
- `<backend>_<model>_extractions.jsonl/.csv` — per-extraction per-backend record (Stage 5).
- `llm_extractions.csv` — alias to the latest free/local extraction (so dashboards do not need to know which model).
- `user_wants_assignments.csv` — per-ticket want assignment (Stage 6).
