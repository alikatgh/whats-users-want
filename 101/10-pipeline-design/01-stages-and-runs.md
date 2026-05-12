# 01 — Stages and runs

## What problem does this solve

A pipeline that mutates its outputs in place creates two related
problems. **First**, you can't compare runs — once you've overwritten
yesterday's results, you can't reproduce them or diff against today's.
**Second**, a partial failure leaves the output directory in a mixed
state where some files are from yesterday and some from today.

The fix is to write every run into a **fresh, timestamped directory**,
and to never modify it again afterwards. Every `outputs/option2_*` in
this repository is one such snapshot.

## What's actually happening

Each pipeline stage takes a *run directory* as input and writes only
into that same directory. Running stage 1 produces a new directory.
Running stages 2-6 read from that directory and append more files.

The directory's name encodes when it was created: `option2_<timestamp>`.
Multiple runs coexist in `outputs/`, sorted lexicographically by
timestamp. The "latest run" is just the last one in the sort.

This convention has six consequences worth remembering:

1. **Reruns are non-destructive.** Running stage 1 again creates
   `option2_<new_timestamp>/` next to the old one.
2. **Stages are composable.** Each script accepts a `run_dir` argument.
   You can run them in any order as long as their dependencies have
   already populated the directory.
3. **The latest run is easy to find.**
   `sorted(glob("option2_*"))[-1]` does it.
4. **Old runs are full provenance.** Every cluster, every chart,
   every model output that was ever surfaced to the team is sitting
   on disk somewhere.
5. **Disk fills up.** A 6,728-ticket run is ~50 MB. At one run per day
   you fill 1.5 GB per month. Periodic cleanup is needed but not
   automated.
6. **Comparing runs is just a `diff`.** Compare last week's
   `manager_context_quality.csv` to this week's; the column
   structures are stable so a diff makes sense.

## The code in this codebase

[scripts/option2_pipeline.py](../../scripts/option2_pipeline.py) creates
the run directory:

```python
def run(args: argparse.Namespace) -> Path:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir).expanduser().resolve() / f"option2_{stamp}"
    ensure_dir(out_dir)
    ...
```

Three things to notice:

- **`datetime.now().strftime("%Y%m%d_%H%M%S")`** produces a string like
  `20260502_150055`. Zero-padded ISO ordering means lexicographic sort
  matches chronological sort. (See module 01 lesson 01 for the full
  pattern.)
- **`Path(args.output_dir) / f"option2_{stamp}"`** uses pathlib's
  `/` operator, which is equivalent to `os.path.join` but reads
  better.
- **`ensure_dir(out_dir)`** wraps `out_dir.mkdir(parents=True,
  exist_ok=True)`. A new directory every run; never collides because
  the timestamp is unique to seconds.

The downstream stages all start by resolving the run directory rather
than creating one. Stage 2:

```python
def run(run_dir: Path, min_topic_size: int) -> None:
    assignments_path = run_dir / "semantic_cluster_assignments.csv"
    embeddings_path = run_dir / "embeddings_local.npy"
    if not assignments_path.exists():
        raise FileNotFoundError(assignments_path)
    ...
```

Stage 2 fails fast if its inputs aren't there. The error message
includes the path, so the user sees exactly which run-stage they need
to run first.

[scripts/dashboard/lib.py](../../scripts/dashboard/lib.py) `latest_run`:

```python
def latest_run() -> Path | None:
    runs = list_runs()
    return runs[0] if runs else None


def list_runs() -> list[Path]:
    runs = sorted(
        [p for p in OUTPUTS_DIR.glob("option2_*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    return runs
```

`list_runs` returns runs in reverse chronological order; `latest_run`
takes the first one. The dashboard's run-picker uses `list_runs` so
the user can pick any historical run from the dropdown.

## The six stages of this pipeline

The stages are six separate scripts. Each one expects (or, for stage
1, creates) a run directory.

| Stage | Script | Reads | Writes |
|---|---|---|---|
| 1 | `option2_pipeline.py` | `data_2may.csv` | Creates `option2_<ts>/` with enriched, embeddings, clusters, manager scores, charts |
| 2 | `bertopic_from_run.py` | run dir | `bertopic_*` files |
| 3 | `insight_layer.py` | run dir | `opportunity_backlog.csv`, personas, residuals |
| 4 | `split_outlier_bucket.py` | run dir | `outlier_*` files |
| 5 | `llm_extract_rich_tickets.py` | run dir | `*_extractions.{jsonl,csv}` |
| 6 | `build_user_wants_taxonomy.py` | run dir | `user_wants_*` files |

The dependency graph is a DAG, not a chain: stages 2, 3, 4 all read
stage 1's outputs but don't depend on each other. Stage 5 also reads
stage 1's outputs. Stage 6 reads stage 5's. You can run stages 2-4 in
parallel if you want.

The reason for splitting into separate scripts (rather than calling
everything from one mega-script) is that **each stage has different
runtime expectations**:

- Stage 1 takes ~3 minutes.
- Stage 2 takes ~30 seconds.
- Stage 5 with `--limit 250` takes ~15 minutes (LLM is slow).
- Stage 5 with `--limit 1000` takes ~2 hours.

You don't want to repeat the 15 minutes of LLM extraction every time
you tweak the BERTopic min_cluster_size. Splitting into stages lets
you re-run only the stages whose inputs have changed.

## Why we chose this approach

We considered three alternatives:

- **One mega-script with conditionals.** The `--rerun-stage 5` style.
  Awkward and the conditional logic outgrows the data logic.
- **Notebooks per stage.** Works for one analyst, breaks immediately
  for a team or for re-running automatically.
- **A workflow engine like Airflow or Prefect.** Heavy. Worth it for
  scheduled production pipelines; not worth it for a one-shot
  analysis.
- **Separate scripts that share a run directory** — chosen. The
  filesystem is the message bus. Each stage reads what it needs and
  writes its own outputs. There's no orchestration daemon, no DAG
  config file, just a folder.

The trade-off: you have to remember which stage to run when. The
README and `docs/engineering/00-architecture.md` document the order;
the dashboard's home page tells you which stages have produced
outputs in the active run.

## Try it

List your runs:

```bash
ls -1d outputs/option2_*
```

Pick the latest:

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)
echo "$RUN_DIR"
```

See which files it contains:

```bash
ls -la "$RUN_DIR" | head -30
```

You'll see the stage 1 outputs (`enriched_tickets.csv`, `manager_*`,
`semantic_*`, `embeddings_local.npy`, charts), stage 2 (`bertopic_*`),
stage 3 (`opportunity_backlog.csv`, `repeat_user_personas.csv`...),
stage 4 (`outlier_*`), stage 5 (`*_extractions.{jsonl,csv}`), and
stage 6 (`user_wants_*`).

Now run a stage **out of order** to see what happens:

```bash
.venv/bin/python scripts/build_user_wants_taxonomy.py /tmp/nonexistent
```

You get a `FileNotFoundError` with a path that tells you exactly which
input is missing. That's intentional. The error message is the bug
report.

Now do a no-op repeat run:

```bash
.venv/bin/python scripts/insight_layer.py "$RUN_DIR"
```

Stage 3 re-reads stage 1's outputs and re-writes its own. The
opportunity backlog, residuals, and personas are recomputed. Old
files are overwritten in place; the run directory's name doesn't
change. (Section markers in `executive_findings.md` keep the report
idempotent — covered in lesson 04.)
