# 12 — Exercises

## Prerequisites

Modules [01-11](../README.md). Pick whichever exercises match the techniques
you most want to practice. Each exercise has a clear before/after and a
runnable verification step.

## What you can do after

- Extend the pipeline with a new evidence flag, desire, or LLM job category
  without breaking existing runs.
- Add a new dashboard page following the conventions in module 09.
- Re-cluster the discovered wants with a different algorithm or `k` value.
- Write a small post-processing script that combines outputs across runs.

## Exercises

| # | File | Skill practiced |
|---|---|---|
| 01 | [01-add-a-new-evidence-flag.md](01-add-a-new-evidence-flag.md) | Regex, pandas feature engineering, score weights |
| 02 | [02-add-a-new-desire.md](02-add-a-new-desire.md) | DESIRE_PATTERNS dict, idxmax, downstream impact |
| 03 | [03-add-a-new-llm-job.md](03-add-a-new-llm-job.md) | JOB_VALUES, alias map, prompt updates, validation |
| 04 | [04-add-a-dashboard-page.md](04-add-a-dashboard-page.md) | Streamlit pages convention, lib helpers, layout |
| 05 | [05-cluster-with-different-k.md](05-cluster-with-different-k.md) | KMeans / HDBSCAN parameters, comparing taxonomies |

What's next: [glossary.md](../glossary.md) — every term in the course with a
plain-English definition.
