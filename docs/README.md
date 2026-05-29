# Documentation Index

This folder explains the **2026-what-users** project end-to-end. It is written so you can present the work without being a data scientist.

Read in this order before the presentation:

1. [01-overview.md](01-overview.md) — what this project is, why it exists, and the headline finding in plain language.
2. [02-pipeline.md](02-pipeline.md) — the full data-science pipeline, stage by stage, with what each step does and why.
3. [03-features-and-models.md](03-features-and-models.md) — the features we extract from raw text and the ML techniques used (embeddings, BERTopic, HDBSCAN, KMeans, regression). Plain-language descriptions, no math jargon.
4. [04-outputs.md](04-outputs.md) — every output file in the run directory, what it contains, and when to look at it.
5. [05-findings.md](05-findings.md) — the four findings worth showing, with the supporting numbers.
6. [06-glossary.md](06-glossary.md) — jargon-free definitions for terms the audience will hear.
7. [07-presenter-script.md](07-presenter-script.md) — a slide-by-slide script. What to say, what to show.
8. [08-running-it.md](08-running-it.md) — exact commands to reproduce or extend the analysis.
9. [09-limitations.md](09-limitations.md) — what this analysis cannot tell you. Read this before someone asks during Q&A.
10. [10-runpod-gpu-101.md](10-runpod-gpu-101.md) — what happens after renting a GPU: terminal access, downloads, costs, uploads, and when to stop the pod.
11. [11-runpod-mistral-runbook.md](11-runpod-mistral-runbook.md) — exact RunPod/Mistral operating runbook, including smoke tests, failure recovery, output packaging, and volume cleanup.
12. [12-management-slide-brief.md](12-management-slide-brief.md) — NotebookLM-ready slide text and positioning for management: simple, careful, and not framed as a chatbot.

For deep "how does it work" engineering questions, the next folder over has it:

13. [engineering/](engineering/) — meticulous, function-by-function deep dives, exact formulas, all prompts, all output schemas.
14. [api/](api/) — auto-generated browsable HTML API docs from script docstrings. Open [api/index.html](api/index.html) in a browser.

## Building the full styled site

To render everything (high-level docs + engineering docs + Python API docs) as a single themed site with sidebar nav, search, and dark mode:

```bash
./scripts/build_docs.sh        # builds site/
open site/index.html
```

For live preview while editing:

```bash
.venv/bin/mkdocs serve
# then open http://localhost:8000
```

Stack: [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) for Markdown rendering + [pdoc](https://pdoc.dev/) for Python API docs. Built in under 2 seconds.

## Quick map

```
data_2may.csv (6,728 tickets, mixed RU/EN/CN, messy support notes)
        │
        ▼
[option2_pipeline.py]   clean + extract evidence + score managers + embed + cluster
        │
        ├──> [bertopic_from_run.py]      validate clusters with topic modeling
        ├──> [insight_layer.py]          rank opportunities, find personas, score evidence
        ├──> [split_outlier_bucket.py]   split messy "topic -1" into 26 sub-themes
        ├──> [llm_extract_rich_tickets.py] extract structured fields with a local Ollama model
        ├──> [build_user_wants_taxonomy.py] cluster extracted wants into 17 user-want labels
        └──> [project_user_wants_full_corpus.py] map all cleaned tickets to those wants
```

All outputs land under `outputs/option2_<timestamp>/`. Two runs matter when presenting:
- **`outputs/option2_20260513_030517/`** — the current **RunPod/Mistral** run: the 1,348-ticket want taxonomy (20 wants), full-corpus projection, and longitudinal layer.
- **`outputs/option2_20260502_150055/`** — the original free **Gemma** run: the only run with the BERTopic (53 topics), outlier-split (26 sub-themes), and opportunity-backlog layers (Stages 2–4 were not run on RunPod).

## Latest run quick numbers

- 6,728 tickets analyzed → 6,702 analysis-ready (date range 2025-06-09 to 2026-05-02)
- 2,422 unique users
- **Current (RunPod/Mistral, May-13):** 20-want taxonomy from **1,348** Mistral Small 3.2 24B-read tickets (1,348 ok / 0 bad / 0 error), plus full-corpus projection and a longitudinal trend + journey-archetype layer
- **Original free baseline (Gemma, May-2):** 17-want taxonomy from 250 tickets; 53 BERTopic topics + 26 outlier sub-topics
- 0 paid API calls — both runs used local Ollama (Gemma 3:4B locally, then Mistral Small 3.2 24B on a rented GPU)
