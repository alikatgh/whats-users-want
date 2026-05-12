# 05 — Metadata and provenance

## What problem does this solve

Two months from now you'll be looking at a chart and asking "where did
this number come from?" Without provenance — a record of *which run*
produced *which output* with *which parameters* — you can't answer.
Worse, you can't reproduce.

Provenance is the trail of breadcrumbs that lets you trace an output
back to its inputs and the code path that produced it.

## What's actually happening

Every stage in this pipeline writes a small JSON file recording:

- When the stage ran (timestamp).
- Which input it read.
- Which parameters were used.
- Output sizes (row counts, column counts).
- Backend versions or model names where relevant.

Each stage's metadata file lives in the same run directory as its
outputs. Together they document the run.

A second mechanism — `df.attrs` — records *which file* a DataFrame was
loaded from, so functions that consume DataFrames can answer "what's
the source of truth for this?" without re-deriving the path.

## The code in this codebase

[scripts/option2_pipeline.py](../../scripts/option2_pipeline.py) writes
`run_metadata.json` at the end of stage 1:

```python
metadata = {
    "input": str(input_path),
    "output_dir": str(out_dir),
    "rows_in_csv": int(raw_rows),
    "rows_dropped_as_summary": int(dropped),
    "rows_after_cleaning": int(len(raw)),
    "rows_enriched": int(len(enriched_with_clusters)),
    "columns_in_csv": int(len(raw_cols)),
    "columns_dropped_as_noise": dropped_cols,
    "embedding_backend_requested": args.embedding_backend,
    "nlp_backend_used": backend_info.to_dict(orient="records"),
    "generated_at": datetime.now().isoformat(timespec="seconds"),
}
(out_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
print(json.dumps(metadata, indent=2))
```

Read this two months from now and you can answer:

- "Where did the input come from?" → `input` field.
- "Were any rows dropped at ingest?" → `rows_dropped_as_summary` / `rows_after_cleaning`.
- "Which embedding model was actually used?" → `nlp_backend_used`
  (handles the case where the requested backend failed and we fell back
  to TF-IDF).
- "When did this run?" → `generated_at`.

`json.dumps(..., indent=2)` produces a readable file. `int(...)` casts
are defensive — without them, numpy ints would `repr()` as
`numpy.int64(5)` instead of `5`, which `json.dumps` rejects.

## Per-stage metadata files

Each downstream stage writes its own metadata file:

[scripts/bertopic_from_run.py](../../scripts/bertopic_from_run.py):

```python
metadata = {
    "run_dir": str(run_dir),
    "docs": len(docs),
    "embeddings_shape": list(embeddings.shape),
    "topics": int(pd.Series(topics).nunique()),
    "generated_at": datetime.now().isoformat(timespec="seconds"),
}
(run_dir / "bertopic_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
```

[scripts/insight_layer.py](../../scripts/insight_layer.py):

```python
metadata = {
    "run_dir": str(run_dir),
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "tables": {name: list(table.shape) for name, table in tables.items()},
}
(run_dir / "insight_layer_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
```

[scripts/split_outlier_bucket.py](../../scripts/split_outlier_bucket.py):

```python
metadata = {
    "run_dir": str(run_dir),
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "assignments": list(assignments.shape),
    "summary": list(summary.shape),
    "refined_backlog": list(refined.shape) if refined is not None else None,
}
(run_dir / "outlier_split_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
```

[scripts/llm_extract_rich_tickets.py](../../scripts/llm_extract_rich_tickets.py):

```python
status = {
    "run_dir": str(run_dir),
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "dry_run": False,
    "backend": args.backend,
    "model": args.model,
    "output_stem": output_stem,
    "candidates": int(len(candidates)),
    "extractions_rows": int(len(extracted)),
}
(run_dir / "llm_extraction_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
```

Each stage's file records:

- Which run it belongs to (`run_dir`).
- When it ran (`generated_at`).
- Stage-specific parameters (model, backend, candidate count).
- Stage-specific output sizes.

## `df.attrs` — provenance on DataFrames

[scripts/build_user_wants_taxonomy.py](../../scripts/build_user_wants_taxonomy.py)
`load_extractions`:

```python
def load_extractions(run_dir: Path) -> pd.DataFrame:
    candidates = [
        run_dir / "ollama_gemma3-4b_extractions.csv",
        run_dir / "ollama_extractions.csv",
        run_dir / "llm_extractions.csv",
        run_dir / "rules_extractions.csv",
    ]
    for path in candidates:
        if path.exists() and path.stat().st_size > 0:
            df = pd.read_csv(path)
            df.attrs["source_file"] = path.name
            return df
    raise FileNotFoundError(f"No extraction CSV found in {run_dir}")
```

`df.attrs` is a little-known pandas dict that travels with the
DataFrame. It's not a column, doesn't appear in `df.head()`, doesn't
get serialised to CSV — but it's there in memory for downstream code
to inspect.

The taxonomy builder later:

```python
extractions = load_extractions(run_dir)
source_file = extractions.attrs.get("source_file", "extractions.csv")
print(f"loaded {len(extractions)} extractions from {source_file}")
```

The `print` line tells the user *which file* was used. If you ran the
pipeline with stages 5 and 6 separately and forgot which model was
last used, the log line answers that for you.

`df.attrs` is the right place for "metadata about this DataFrame" —
filename, query, refresh time, version. It's the wrong place for
"data" (use a column).

## Why timestamping the run directory itself is provenance

The run directory's name (`option2_20260502_150055`) is itself
provenance:

- The timestamp tells you when the run happened to the second.
- The prefix `option2_` distinguishes pipelines if you ever fork.
- Lexicographic sort agrees with chronological sort.

Combined with the `run_metadata.json` inside the directory, you can
answer every "what happened" question without external systems.

## Why we chose this approach

Three patterns of provenance were possible:

- **Write to a central provenance database** (e.g. MLflow, Weights &
  Biases). Powerful for tracking many runs across many people. Heavy
  for a single-team analysis. Buys "I can compare 1,000 runs in a
  dashboard"; we have ~10.
- **Embed metadata as comments at the top of each output file.** Works
  for CSV (header comment lines), breaks for binary formats (parquet,
  npy). Inconsistent.
- **Sidecar JSON files** — chosen. Every stage writes its own
  `*_metadata.json` next to its outputs. Plain text. JSON parses
  trivially. The sidecar pattern survives renames and movements
  (the metadata moves with the directory).

The trade-off: nobody is *forced* to read the metadata. You have to
remember to look. That's why the dashboard surfaces some of it
implicitly (run picker shows the timestamp; KPIs show row counts).

## Recovery patterns

When something goes wrong with a run, the metadata files are the first
thing to read:

```bash
cat outputs/option2_<TS>/run_metadata.json
cat outputs/option2_<TS>/llm_extraction_status.json
```

These files answer:

- "Did stage 5 actually run?" (presence of the file).
- "Which model was used?" (`model` field).
- "How many candidates were processed?" (`candidates`).
- "Were there any errors?" (the extracted CSV's `_status` column,
  surfaced by the dashboard's Extraction Progress page).

A pipeline rerun with all the same parameters can use the metadata as
the source of truth: read `run_metadata.json["embedding_backend_requested"]`
to know which `--embedding-backend` to pass.

## Try it

Inspect a run's full provenance:

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)

echo "=== Stage 1 ==="
cat "$RUN_DIR/run_metadata.json"

echo
echo "=== Stage 2 ==="
cat "$RUN_DIR/bertopic_metadata.json" 2>/dev/null || echo "stage 2 didn't run"

echo
echo "=== Stage 3 ==="
cat "$RUN_DIR/insight_layer_metadata.json" 2>/dev/null || echo "stage 3 didn't run"

echo
echo "=== Stage 4 ==="
cat "$RUN_DIR/outlier_split_metadata.json" 2>/dev/null || echo "stage 4 didn't run"

echo
echo "=== Stage 5 ==="
cat "$RUN_DIR/llm_extraction_status.json" 2>/dev/null || echo "stage 5 didn't run"

echo
echo "=== Stage 6 ==="
cat "$RUN_DIR/user_wants_metadata.json" 2>/dev/null || echo "stage 6 didn't run"
```

You get a complete record of which stages ran, when, with which
parameters, and how many rows each produced.

Now read the `df.attrs` provenance from a Python session:

```bash
.venv/bin/python <<PY
import sys
sys.path.insert(0, "scripts")
from build_user_wants_taxonomy import load_extractions
from pathlib import Path

df = load_extractions(Path("$RUN_DIR"))
print(f"Loaded {len(df)} rows")
print(f"Source file: {df.attrs.get('source_file')}")
PY
```

The log line tells you which extraction file was used — automatically
falling back through the priority list and recording the result.
