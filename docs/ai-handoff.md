# AI Handoff

## Current Goal

Continue the 2026 What Users Want analysis/dashboard work while preserving active analysis and static-readout changes.

## Current Status

- Repo has active uncommitted work in pipeline scripts, Streamlit dashboard pages, MkDocs config, course notes, and static-readout output.
- Added `AGENTS.md` with privacy, pipeline, and careful-claims guardrails.
- Source data and outputs should be treated as private.

## Files Touched By Codex Setup

- `AGENTS.md`
- `docs/ai-handoff.md`

## Existing Dirty Areas To Preserve

- `.gitignore`
- `mkdocs.yml`
- `101/01-python-foundations/05-error-handling-and-soft-fail.md`
- `scripts/bertopic_from_run.py`
- `scripts/build_user_wants_taxonomy.py`
- `scripts/dashboard/app.py`
- `scripts/dashboard/pages/*`
- `scripts/label_user_wants.py`
- `scripts/label_user_wants.sh`
- `scripts/option2_pipeline.py`
- `scripts/project_user_wants_full_corpus.py`
- `scripts/split_outlier_bucket.py`
- `scripts/export_static_readout.py`
- `scripts/run_static_readout.sh`
- `static/`

## Tests/Checks Already Run

- None for analysis behavior. This setup only added instruction/handoff files.

## Current Risk

- Do not paste raw ticket text or identifiers into chat unless explicitly needed.
- Do not run paid/API extraction unless explicitly requested.
- Do not overstate findings: the 250-ticket extraction is not representative of all tickets, maps are exploratory, and manager-written notes introduce framing bias.

## Exact Next Step

Run `Review pass` on the current diff or ask for a specific dashboard/pipeline task. Read `docs/09-limitations.md` before editing claims or presentation language.

## Commands To Run Next

- Quick deterministic baseline: `.venv/bin/python scripts/option2_pipeline.py --input data_2may.csv --embedding-backend tfidf`
- Dashboard: `./scripts/run_dashboard.sh`
- Static readout: `./scripts/run_static_readout.sh`
- Docs build: `./scripts/build_docs.sh`

## Things Not To Change

- Do not clean/regenerate `outputs/`, `site/`, `static/`, caches, or `.matplotlib-cache` as a side effect.
- Do not change output schemas unless explicitly asked.
- Do not install/pull large local models unless the task requires it.
