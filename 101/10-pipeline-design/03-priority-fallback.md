# 03 — Priority fallback

## What problem does this solve

Real codebases evolve. The file you wrote yesterday gets renamed today.
The new pipeline emits `ollama_gemma3-4b_extractions.csv`; the old one
emitted `llm_extractions.csv`. A page that hardcodes one filename
breaks every time the spec changes.

The pattern: encode your *priority order* as a list of candidate
filenames, walk it, and use the first one that exists. Old runs keep
working with the old filename; new runs use the new one; nobody has to
update consumers in lockstep.

## What's actually happening

A small helper takes a list of candidate names. It tries each in order
and returns the first one that loads. If none exist it returns `None`
or raises a `FileNotFoundError`, depending on whether the caller wants
to handle absence themselves.

Three variants in this codebase:

- `latest_run` — pick the newest run directory.
- `_first_existing` — pick the first matching CSV in a run.
- `load_extractions` — same idea but raises if none exist (because
  taxonomy building can't proceed without LLM extractions).

## The code in this codebase

[scripts/dashboard/lib.py](../../scripts/dashboard/lib.py) `latest_run`:

```python
def list_runs() -> list[Path]:
    runs = sorted(
        [p for p in OUTPUTS_DIR.glob("option2_*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    return runs


def latest_run() -> Path | None:
    runs = list_runs()
    return runs[0] if runs else None
```

The list is sorted in reverse, so element 0 is the newest. If the
list is empty (fresh clone, no runs yet), the function returns `None`
and the caller is responsible for handling absence.

`scripts/dashboard/app.py` `_first_existing`:

```python
def _first_existing(*names: str):
    for n in names:
        df = maybe_load_csv(run_dir, n)
        if df is not None:
            return df
    return None


extractions = _first_existing("ollama_gemma3-4b_extractions.csv", "llm_extractions.csv")
backlog = _first_existing("refined_opportunity_backlog.csv", "opportunity_backlog.csv")
```

The `*names: str` means "any number of positional string arguments,
arriving as a tuple." The function walks the tuple in order; the first
filename that loads to a real DataFrame wins. `None` if nothing loads.

The choice of priority matters:

- `ollama_gemma3-4b_extractions.csv` is the new naming, more specific.
  Try it first.
- `llm_extractions.csv` is the legacy alias. Try it second so old runs
  still display.

For backlog: the *refined* version (which incorporates Stage 4's
outlier sub-themes) is preferred when present; otherwise fall back to
the original.

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

Four candidates in priority order:

1. `ollama_gemma3-4b_extractions.csv` — the best local model output.
2. `ollama_extractions.csv` — alias for the latest local run (could
   point at a different model if 4B wasn't run).
3. `llm_extractions.csv` — legacy filename.
4. `rules_extractions.csv` — pure deterministic baseline; always works
   even without an LLM.

`path.exists() and path.stat().st_size > 0` — both checks. A 0-byte
file (left over from a crashed run) shouldn't count as "exists."

`df.attrs["source_file"] = path.name` — use pandas's metadata-on-frame
trick (`df.attrs`) to record which file actually loaded. Downstream
code can read this without re-deriving the filename.

This function *raises* on failure rather than returning `None`. That's
intentional: building a taxonomy from no extractions is impossible, so
the caller should crash explicitly rather than silently produce empty
output.

## When to fall back vs raise

Two patterns, two intents.

**`_first_existing(...) -> df | None`** — used for *optional* data.
The home page's KPI tiles say "—" instead of a number when the data
isn't there yet. Missing extraction data isn't a failure mode; it's
"this stage hasn't run yet."

**`load_extractions(...) -> df` (raises)** — used for *required* data.
Stage 6 can't possibly produce a taxonomy without extracted want
strings. Raising forces the user to run stage 5 first.

The rule of thumb: **use a fallback to `None` when downstream code can
gracefully handle absence; raise when absence makes downstream code
nonsensical.**

## The "stable alias" technique

Look at the priority list again:

```
ollama_gemma3-4b_extractions.csv   <- model-specific filename
ollama_extractions.csv             <- alias, points to latest local run
llm_extractions.csv                <- alias, points to latest free/local run
rules_extractions.csv              <- baseline
```

The middle two are *aliases* maintained by the extraction script.
Whenever a new extraction runs, it copies its output to those generic
names. Why? So the dashboard can hardcode `llm_extractions.csv` and
the alias resolves to whatever model was last run.

[scripts/llm_extract_rich_tickets.py](../../scripts/llm_extract_rich_tickets.py)
maintains both:

```python
extracted = pd.json_normalize(all_rows)
extracted.to_csv(run_dir / f"{output_stem}.csv", index=False)
if output_stem != f"{backend}_extractions":
    # Keep stable aliases for dashboards/manual review while preserving per-model files.
    (run_dir / f"{backend}_extractions.jsonl").write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")
    extracted.to_csv(run_dir / f"{backend}_extractions.csv", index=False)
if backend in {"rules", "ollama", "ollama_hybrid"}:
    # Keep the historical generic filenames pointed at the current free/local result.
    extracted.to_csv(run_dir / "llm_extractions.csv", index=False)
```

Three writes:

- `<backend>_<model>_extractions.csv` — the model-specific output.
- `<backend>_extractions.csv` — alias for "latest output of this
  backend."
- `llm_extractions.csv` — alias for "latest free/local extraction."

This matters for the priority-fallback pattern because the same
function call (`pd.read_csv("llm_extractions.csv")`) returns the most
recent local extraction, regardless of which model was used. The
fallback list could in theory just be `["llm_extractions.csv"]`, but
keeping the model-specific names in the priority list lets the
dashboard prefer the *most recent specific* output if it's there.

## Why we chose this approach

Two alternatives we considered:

- **Symlink the latest output to a stable name.** Works on Unix,
  breaks on Windows, breaks on shared filesystems, breaks when copied.
  Plain filenames travel.
- **A central "manifest" JSON that lists all outputs.** Useful for
  large pipelines but adds a meta-file to maintain. For 50 outputs
  per run the priority list inline in the consumer is simpler.

The priority list pattern is two lines of code per consumer. The
trade-off is that consumers each maintain their own list — but those
lists are short and they're the right place for this knowledge:
*"I prefer X, but I'll take Y if X isn't there."*

## Try it

Manually delete one of the alias files and watch the fallback work:

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)
ls "$RUN_DIR" | grep extractions

# Hide the new-style filename
mv "$RUN_DIR/ollama_gemma3-4b_extractions.csv" "$RUN_DIR/_temp_hidden.csv"

# Open the dashboard home page; the "Tickets read by local AI" KPI should still show
# the right number because the alias llm_extractions.csv is still there
./scripts/run_dashboard.sh &
sleep 5
curl -s http://localhost:8501 | grep -o "Tickets read by local AI" | head -1
pkill -f "streamlit run"

# Restore
mv "$RUN_DIR/_temp_hidden.csv" "$RUN_DIR/ollama_gemma3-4b_extractions.csv"
```

The dashboard didn't break — the fallback list reached
`llm_extractions.csv` and got a usable DataFrame.

Now hide *all* the extraction files:

```bash
mkdir "$RUN_DIR/_hidden_extractions"
mv "$RUN_DIR"/*extractions.csv "$RUN_DIR/_hidden_extractions/"

./scripts/run_dashboard.sh &
sleep 5
# The dashboard home shows "Tickets read by local AI: 0" — graceful
pkill -f "streamlit run"

# But stage 6 raises:
.venv/bin/python scripts/build_user_wants_taxonomy.py "$RUN_DIR" 2>&1 | head -2
# FileNotFoundError: No extraction CSV found in outputs/option2_...

# Restore
mv "$RUN_DIR/_hidden_extractions"/*.csv "$RUN_DIR/"
rmdir "$RUN_DIR/_hidden_extractions"
```

Both behaviors are correct: the dashboard degrades, the taxonomy
builder fails fast. Same priority-list mechanism, different consumer
intents.
