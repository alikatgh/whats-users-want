# 00 — How to use this course

## What you'll need

1. **The repository.** You're already in it. The course lives in `101/`, the
   real code lives in `scripts/`, and the analysis outputs live in `outputs/`.

2. **A Python environment.** The repository ships with `.venv/`. From the
   project root, run `.venv/bin/python --version` — if it prints something
   like `Python 3.12`, you're set.

3. **A code editor.** VS Code, PyCharm, even a plain text editor with two
   panes works. You will be reading the course on one side and the code on
   the other, switching frequently.

## How to read a lesson

Every lesson in this course follows the same shape:

1. **What problem does this solve?** — what would go wrong without this technique.
2. **What's actually happening** — plain-English description of the mechanism.
3. **The code in this codebase** — pointers to specific files and line numbers,
   then a short excerpt copied inline so you don't have to switch back and
   forth for the basic case.
4. **Why we chose this approach** — the trade-offs vs alternatives.
5. **Try it** — small experiments you can run right now to feel the concept.

When a lesson says "open `scripts/X.py:120-145`", **actually open it**. Read
the surrounding code too. The lesson tells you what the code is doing; only
the code itself tells you the texture of how it does it.

## How to run the code

The course's lessons frequently say things like *"open the dashboard and
filter by Albert"* or *"re-run the pipeline with `--keep-pivot-columns`."*
Here's how to do those.

### Run the full pipeline

```bash
.venv/bin/python scripts/option2_pipeline.py \
  --input data_2may.csv \
  --embedding-backend local
```

This produces a new `outputs/option2_<timestamp>/` directory with about 50
files. First run takes 3-5 minutes (it downloads a 480 MB embedding model);
subsequent runs are about 90 seconds.

### Add the BERTopic and insight layers

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)
.venv/bin/python scripts/bertopic_from_run.py "$RUN_DIR"
.venv/bin/python scripts/insight_layer.py "$RUN_DIR"
.venv/bin/python scripts/split_outlier_bucket.py "$RUN_DIR"
```

### Run local LLM extraction (requires Ollama)

```bash
ollama serve &                             # one-time, in a terminal
ollama pull gemma3:4b                      # one-time, ~3.3 GB
.venv/bin/python scripts/llm_extract_rich_tickets.py "$RUN_DIR" \
  --backend ollama --model gemma3:4b --limit 250 --strategy risk_balanced
```

### Build the human-readable cluster names

```bash
.venv/bin/python scripts/build_user_wants_taxonomy.py "$RUN_DIR"
./scripts/label_user_wants.sh
```

### Open the dashboard

```bash
./scripts/run_dashboard.sh
# then open http://localhost:8501
```

### Stop the dashboard

```bash
pkill -f "streamlit run"
```

### Open the API reference (auto-generated from docstrings)

```bash
open docs/api/index.html
```

### Open the documentation site

```bash
./scripts/build_docs.sh
open site/index.html
```

## How to experiment safely

The pipeline is **idempotent** — re-running it produces a new timestamped
directory under `outputs/`, never modifying old runs. You can change a
parameter, re-run, and compare. Old runs are not deleted automatically; once
you've finished a learning session, feel free to remove old `outputs/option2_*`
folders to save disk.

The dashboard never modifies data. The DuckDB connection is opened
**read-only**. You can write any SQL in the SQL Console page without fear.

The LLM extraction step also writes to a separate JSONL file per backend, so
you can run rules → ollama_hybrid → ollama → openai in sequence and compare
their outputs without overwriting.

## How to verify your environment

Before module 01, run these and confirm each one works:

```bash
.venv/bin/python -c "import pandas, numpy, sklearn; print('core ok')"
.venv/bin/python -c "import sentence_transformers, umap, hdbscan; print('nlp ok')"
.venv/bin/python -c "import statsmodels, duckdb, plotly, streamlit; print('rest ok')"
```

If any of those fail, run `.venv/bin/pip install -r requirements.txt`.

For the LLM lessons (module 06), confirm Ollama is running:

```bash
curl -s http://localhost:11434/api/tags && echo "ollama ok"
```

If it doesn't respond, start it with `ollama serve &`.

## How to skip ahead

You can read modules out of order if you want — each lesson references the
prerequisites it depends on at the top. Common skip paths:

- **"I want to learn the dashboard side"** → start at module 09, refer back
  to 02 (pandas) when you hit a `groupby` you don't recognise.
- **"I want to learn just the NLP"** → modules 03 and 04, then 06.
- **"I want to learn just the statistics"** → module 05.
- **"I want to write better Python first"** → module 01, then optionally
  jump to module 10 (pipeline design) for higher-level patterns.

## How to use the glossary

When you see a term you don't recognise — *embedding*, *c-TF-IDF*,
*MiniBatchKMeans*, *fixed effects*, *quality flag* — open
[glossary.md](glossary.md). Every term in the course has a one-paragraph
plain-English definition there. The glossary is alphabetical and links back
to the lesson that introduces each term.

## Ready

Open [01-python-foundations/README.md](01-python-foundations/README.md).
