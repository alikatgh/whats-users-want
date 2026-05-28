# 2026 What Users Want Agent Notes

## Project Map

- Python-first user-needs analysis over a private support-ticket export.
- Source data is expected locally as `data_2may.csv` and is intentionally not
  committed.
- `scripts/option2_pipeline.py` is Stage 1: clean, enrich, embed, cluster, and
  score manager context quality.
- `scripts/bertopic_from_run.py`, `insight_layer.py`,
  `split_outlier_bucket.py`, `llm_extract_rich_tickets.py`,
  `build_user_wants_taxonomy.py`, and `project_user_wants_full_corpus.py` are
  later analysis stages.
- `scripts/dashboard/` contains the Streamlit dashboard.
- `docs/` contains presentation-ready documentation and engineering deep dives.
- `101/` contains teaching/course material.
- `outputs/option2_<timestamp>/` contains generated run artifacts.
- `static/` and `outputs/static_what_users_want/` contain static readout output.
- `site/` contains generated MkDocs output.

## Data And Privacy

- Treat `data_2may.csv`, `outputs/`, dashboard exports, and ticket examples as
  private unless the user explicitly says otherwise.
- Do not paste raw ticket text, identifiers, names, URLs, or sensitive examples
  into chat unless asked and necessary.
- Prefer summaries, aggregates, and file paths over raw row dumps.
- Do not run OpenAI/API extraction paths unless the user explicitly asks and an
  API key/budget is available.

## Commands

Setup:

- `.venv/bin/python -m pip install -r requirements.txt`

Baseline pipeline:

- `.venv/bin/python scripts/option2_pipeline.py --input data_2may.csv --embedding-backend tfidf`

Local embedding run:

- `.venv/bin/python scripts/option2_pipeline.py --input data_2may.csv --embedding-backend local --embedding-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

Later stages:

- `.venv/bin/python scripts/bertopic_from_run.py outputs/option2_<TIMESTAMP>`
- `.venv/bin/python scripts/insight_layer.py outputs/option2_<TIMESTAMP>`
- `.venv/bin/python scripts/split_outlier_bucket.py outputs/option2_<TIMESTAMP>`
- `.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_<TIMESTAMP> --backend rules --limit 250 --strategy risk_balanced`
- `.venv/bin/python scripts/build_user_wants_taxonomy.py outputs/option2_<TIMESTAMP>`
- `.venv/bin/python scripts/project_user_wants_full_corpus.py outputs/option2_<TIMESTAMP>`

Docs and dashboard:

- Build docs: `./scripts/build_docs.sh`
- Preview docs: `.venv/bin/mkdocs serve`
- Dashboard: `./scripts/run_dashboard.sh`
- Static readout: `./scripts/run_static_readout.sh`

Prefer the deterministic `tfidf` or `rules` paths for quick checks. Local model
or embedding runs can download models or take a long time.

## Current-State Caution

This repo may have active uncommitted work in scripts, Streamlit dashboard pages,
MkDocs config, course notes, and generated static output. Always check
`git status` before editing and preserve existing user changes.

Do not clean or regenerate `outputs/`, `site/`, `static/`, caches, or
`.matplotlib-cache` as a side effect of unrelated work.

## Analysis Guardrails

- Read `docs/09-limitations.md` before changing findings, claims, or
  presentation language.
- Read `docs/08-running-it.md` before changing pipeline/run commands.
- Read `docs/engineering/README.md` and the relevant engineering deep dive
  before modifying a pipeline stage.
- Keep claims careful: the 250-ticket extraction is not representative of all
  tickets; maps are exploratory; manager-written notes introduce framing bias.
- Do not overstate model quality. Preserve quality flags, schema validation, and
  uncertainty language.

## Working Style

- For vague requests, choose one bounded dashboard, docs, or pipeline issue and
  verify it narrowly.
- Prefer reading the latest run metadata and docs before recomputing expensive
  stages.
- When editing analysis code, preserve output schemas unless the user asks for a
  schema change.
- Report which run directory and commands were used.
