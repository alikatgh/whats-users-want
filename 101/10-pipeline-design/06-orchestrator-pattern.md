# 06 — The orchestrator pattern

## What problem does this solve

A pipeline stage has many small functions. You don't want a teammate
to have to call them in the right order — you want a single entry
point that handles parameter parsing, top-level error handling, and
function chaining.

The pattern: each stage's script defines a `run(args)` function that
calls every other function in the right order. A top-level
`if __name__ == "__main__":` block parses CLI args via argparse and
calls `run(parse_args())`. That's it.

## What's actually happening

Three layers, each with one responsibility:

1. **Module-level functions** do the actual work. Each is small,
   testable, takes specific inputs.
2. **`run(args)`** orchestrates: it takes parsed CLI arguments, calls
   the work functions in order, and writes outputs.
3. **`__main__`** parses CLI args and calls `run(args)`.

By keeping these layers separate:

- Other Python code can import a stage and call `run(args)`
  programmatically without spawning a subprocess.
- Tests can call individual work functions directly.
- The CLI is just argparse — no business logic.

## The code in this codebase

Every stage in this repository follows the same shape.

[scripts/option2_pipeline.py](../../scripts/option2_pipeline.py):

```python
def run(args: argparse.Namespace) -> Path:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir).expanduser().resolve() / f"option2_{stamp}"
    ensure_dir(out_dir)

    raw = read_raw_csv(input_path)
    raw_rows = len(raw)
    raw_cols = list(raw.columns)
    if not getattr(args, "keep_pivot_columns", False):
        raw, dropped_cols = drop_noise_columns(raw)
    ...
    cleaned = canonicalize(raw)
    enriched = featurize_tickets(cleaned)

    manager_summary = build_manager_summary(enriched)
    adjusted = adjusted_manager_context(enriched)
    examples = top_examples(enriched)
    desire = desire_summary(enriched)
    network_nodes = build_network(enriched, out_dir)

    cluster_assignments, cluster_summary, backend_info = cluster_texts(
        enriched, out_dir=out_dir,
        backend=args.embedding_backend,
        model_name=args.embedding_model,
    )

    enriched_with_clusters = enriched.merge(...)

    tables = {
        "enriched_tickets": enriched_with_clusters,
        "manager_context_quality": manager_summary,
        ...
    }
    for name, table in tables.items():
        table.to_csv(out_dir / f"{name}.csv", index=False)
    export_excel(out_dir, tables)
    export_analytical_store(out_dir, tables)
    create_charts(enriched_with_clusters, manager_summary, out_dir)
    write_markdown_report(...)

    metadata = { ... }
    (out_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return out_dir
```

`run` reads top to bottom like a recipe. Every line is one of:

- A function call (`read_raw_csv`, `canonicalize`, `featurize_tickets`).
- An attribute access on `args` to get a parameter.
- A small bit of glue (build a dict, write a CSV, write metadata).

There's no business logic in `run` — it doesn't know how a context
score is computed; it just calls `featurize_tickets`. It doesn't know
how clustering works; it just calls `cluster_texts`.

## The CLI layer

`parse_args` builds the argparse parser:

```python
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Option 2 ...")
    parser.add_argument("--input", default="data_2may.csv")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument(
        "--embedding-backend",
        choices=["tfidf", "local", "openai"],
        default="tfidf",
        help="...",
    )
    parser.add_argument("--embedding-model", default="...")
    parser.add_argument("--keep-summary-rows", action="store_true", help="...")
    parser.add_argument("--keep-pivot-columns", action="store_true", help="...")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args(sys.argv[1:]))
```

`parse_args(argv)` takes a list of strings and returns a `Namespace`
with attributes for each flag. Calling `parse_args(sys.argv[1:])` from
`__main__` is the standard pattern (the `[1:]` skips the program name).

The Namespace's attributes become `args.input`, `args.output_dir`, etc.
Hyphens in flag names are converted to underscores
(`--embedding-backend` → `args.embedding_backend`).

`action="store_true"` flags don't take a value — their presence sets
the attribute to `True`, absence to `False`. Useful for opt-in flags
like `--keep-pivot-columns`.

## The shape repeats across every stage

[scripts/insight_layer.py](../../scripts/insight_layer.py):

```python
def run(run_dir: Path) -> None:
    df, _, _ = load_run(run_dir)
    backlog = build_opportunity_backlog(df)
    emerging = build_emerging_topics(df)
    personas = build_repeat_user_personas(df)
    manager_resid, issue_gaps = build_context_gap(df)
    context_model = build_context_value_model(df)
    evidence_coaching = build_manager_evidence_coaching(df)
    tables = {...}
    write_outputs(run_dir, tables)
    append_report(run_dir, tables)
    metadata = {...}
    (run_dir / "insight_layer_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else latest_run(...)
    run(run_dir)
```

Same shape: `run(args_or_resolved_dir)` calls work functions in order.
The `__main__` block parses CLI, resolves the run dir, calls `run`.

[scripts/build_user_wants_taxonomy.py](../../scripts/build_user_wants_taxonomy.py)
calls its orchestrator `main`:

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--min-cluster-size", type=int, default=5)
    parser.add_argument("--method", choices=["auto", "hdbscan", "kmeans"], default="auto")
    parser.add_argument("--n-clusters", type=int, default=None)
    args = parser.parse_args()
    ...
    extractions = load_extractions(run_dir)
    extractions["_want_text"] = extractions.apply(build_want_text, axis=1)
    embeddings = embed_texts(extractions["_want_text"].tolist())
    labels = cluster_wants(embeddings, ...)
    ...
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Returns an int exit code. `sys.exit(0)` for success, `sys.exit(2)` for
"missing input file" — useful when scripts are chained from a shell
command.

## Why we chose this approach

Three reasons:

1. **Clarity of responsibility.** Glue code and business code don't
   mix. A bug in `featurize_tickets` is found by reading
   `featurize_tickets`, not by tracing through 100 lines of
   orchestration.
2. **Programmatic re-use.** Other scripts can `from option2_pipeline
   import run` and call it with a manually-built Namespace, without
   subprocess overhead.
3. **Testability.** Unit tests call work functions directly with
   small DataFrames; integration tests call `run(args)` end-to-end.
   No CLI parsing in either case.

The trade-off: the `run(args)` function is long. For our pipeline
~50 lines is fine. If it grew past 200, you'd split it into multiple
orchestrators (e.g. `run_clean(args)`, `run_cluster(args)`,
`run_export(args)`) called from a thin top-level `run`.

## Why `run(args)` and not a pipeline class

We considered making each stage a class with methods. Dropped because:

- The `run(args)` function has no state worth carrying between calls.
  A class would just be one method with a constructor.
- Procedural is the right shape when the data flows linearly through
  transformations. Object-oriented is right when many objects
  interact.

Functional Python is the right answer for ETL. Classes show up only
where state is real (the dashboard's `lib.py` defines `OUTPUTS_DIR`
and `PROJECT_ROOT` as module-level constants, not class attributes,
for the same reason).

## Try it

Call `run` programmatically from another Python session:

```bash
.venv/bin/python <<'PY'
import argparse
import sys
sys.path.insert(0, "scripts")
import option2_pipeline

# Build a Namespace by hand instead of from sys.argv
args = argparse.Namespace(
    input="data_2may.csv",
    output_dir="outputs",
    embedding_backend="tfidf",
    embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    keep_summary_rows=False,
    keep_pivot_columns=False,
)
out_dir = option2_pipeline.run(args)
print(f"\nRun finished, output dir: {out_dir}")
PY
```

You're calling the pipeline as a Python function, no subprocess. The
returned `out_dir` is the timestamped folder. You can do this in
notebooks, in tests, or in a parent orchestrator script that chains
multiple stages.

For comparison, the CLI form:

```bash
.venv/bin/python scripts/option2_pipeline.py --input data_2may.csv --embedding-backend tfidf
```

Same effect, different invocation path. Both reach `run(args)`.

If you want to chain stages, the orchestrator pattern lets you write:

```python
import sys
sys.path.insert(0, "scripts")
from argparse import Namespace
import option2_pipeline, insight_layer, bertopic_from_run

stage1_args = Namespace(input="data_2may.csv", output_dir="outputs",
                        embedding_backend="local",
                        embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                        keep_summary_rows=False, keep_pivot_columns=False)
run_dir = option2_pipeline.run(stage1_args)
bertopic_from_run.run(run_dir, min_topic_size=35)
insight_layer.run(run_dir)
```

That's a complete three-stage pipeline as a single Python script.
Without the orchestrator pattern, you'd be subprocess'ing or copying
code around.
