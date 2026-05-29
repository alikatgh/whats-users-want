# Engineering Documentation

Meticulous, function-by-function explanation of every script. Read this when someone asks **"how exactly did you do X?"** during the presentation.

## Layout

| File | Covers |
|---|---|
| [00-architecture.md](00-architecture.md) | Repository layout, data flow, dependencies, run conventions |
| [01-stage1-pipeline.md](01-stage1-pipeline.md) | `option2_pipeline.py` — every function and why it exists |
| [02-stage2-bertopic.md](02-stage2-bertopic.md) | `bertopic_from_run.py` — exact BERTopic configuration |
| [03-stage3-insight.md](03-stage3-insight.md) | `insight_layer.py` — opportunity scoring, personas, statistical tests |
| [04-stage4-outlier-split.md](04-stage4-outlier-split.md) | `split_outlier_bucket.py` — KMeans on outliers, silhouette |
| [05-stage5-llm.md](05-stage5-llm.md) | `llm_extract_rich_tickets.py` — backends, prompts, validation |
| [06-stage6-taxonomy.md](06-stage6-taxonomy.md) | `build_user_wants_taxonomy.py` — clustering of LLM outputs |
| [06b-stage7-projection.md](06b-stage7-projection.md) | `project_user_wants_full_corpus.py` — project the 17 wants onto all 6,728 tickets with confidence bands |
| [07-data-schemas.md](07-data-schemas.md) | Every column in every output CSV |
| [08-prompts-and-extraction.md](08-prompts-and-extraction.md) | The exact prompts, the JSON schema, validation rules, alias normalization |
| [09-formulas-cheatsheet.md](09-formulas-cheatsheet.md) | All numeric scores in one place: context_depth_score, opportunity_score, emergence_score, etc. |
| [10-api-docs.md](10-api-docs.md) | How to generate browsable HTML API docs from the source via `pdoc` |

## Utility & extension scripts (not yet deep-dived)

These ship in `scripts/` but do not have a function-by-function doc yet:

| Script | What it does |
|---|---|
| `build_longitudinal_insights.py` | Month-by-month rising/fading wants, next-month growth, repeat-user sequences and archetypes |
| `label_user_wants.py` | Asks a local Ollama model for a 3–7 word human title + one-sentence summary per want cluster → `user_wants_human_labels.csv` |
| `export_static_readout.py` | Packages the static management readout (HTML/CSS/JS + CSVs) into a CDN-ready folder; runs no ML |

## How to use this folder during the presentation

- If someone asks **"what is the context_depth_score?"** → [09-formulas-cheatsheet.md](09-formulas-cheatsheet.md)
- If someone asks **"how does Albert's score get computed?"** → [03-stage3-insight.md](03-stage3-insight.md) and [09-formulas-cheatsheet.md](09-formulas-cheatsheet.md)
- If someone asks **"what model did you use for embeddings?"** → [01-stage1-pipeline.md](01-stage1-pipeline.md), section "embed_texts"
- If someone asks **"what does the LLM see in the prompt?"** → [08-prompts-and-extraction.md](08-prompts-and-extraction.md)
- If someone asks **"how do you handle Russian/Chinese?"** → [01-stage1-pipeline.md](01-stage1-pipeline.md) and [02-stage2-bertopic.md](02-stage2-bertopic.md), embedding model section
- If someone asks **"what if the model gives garbage?"** → [05-stage5-llm.md](05-stage5-llm.md), validation section
- If someone asks **"is this reproducible / can I run it?"** → [00-architecture.md](00-architecture.md)
