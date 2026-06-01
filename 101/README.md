# 101 — Learn data science by reverse-engineering this codebase

This is a course built backwards from a real problem: **6,728 messy customer-support tickets, in three languages, that needed to become a structured picture of what users actually want.**

Every lesson here uses code from this repository as its teaching example. There is **no toy code, no pet project**. When you read about regular expressions, you read regex from [scripts/option2_pipeline.py](../scripts/option2_pipeline.py) that actually extracts evidence from real tickets. When you read about clustering, you trace the exact line where 6,728 tickets get grouped into 53 topics.

## Why "backwards"

Most Python and data-science textbooks start with `print("Hello, world!")` and work up to small toy datasets. This course starts with a finished, working pipeline and takes it apart one technique at a time. You already know what the data is, what the goal is, and what the result looks like. The lessons fill in *how each step gets you there*.

That sequence is harder at first — you'll hit unfamiliar names early — but it has one huge advantage: every concept arrives with a justification. You won't ask "when would I use this?" because the answer is in the next file over.

## Prerequisites

You should be comfortable with:

- Reading Python code at the level of: variables, functions, `if/else`, `for` loops, lists, dicts.
- Running a command in a terminal.
- Opening a file in an editor.

You do **not** need prior experience with:

- Machine learning, NLP, embeddings, or clustering.
- Statistics beyond means and percentages.
- SQL, Plotly, Streamlit, or any specific library.

Each module introduces what it needs.

## Course outline

| Module | What you learn | Pages |
|---|---|---|
| [00 — How to use this course](00-how-to-use-this-course.md) | Reading order, how to run the code, how to experiment | 1 |
| [01 — Python foundations](01-python-foundations/README.md) | The Python idioms that show up everywhere in the codebase | 8 |
| [02 — Data with pandas](02-data-with-pandas/README.md) | Reading messy CSVs, cleaning, feature engineering, joining | 7 |
| [03 — Text and NLP](03-text-and-nlp/README.md) | TF-IDF, embeddings, multilingual models, cosine similarity | 6 |
| [04 — Dimensionality and clustering](04-dimensionality-and-clustering/README.md) | UMAP, HDBSCAN, KMeans, BERTopic, silhouette | 7 |
| [05 — Statistics](05-statistics/README.md) | OLS with fixed effects, robust SEs, two-proportion z-test | 6 |
| [06 — LLMs and prompts](06-llms-and-prompts/README.md) | Schemas, defensive prompting, validation, local Gemma via Ollama | 8 |
| [07 — Databases and storage](07-databases-and-storage/README.md) | DuckDB, Parquet, parameterised SQL, multiple-format strategy | 5 |
| [08 — Visualization](08-visualization/README.md) | Matplotlib, Plotly, heatmaps, when to hide axes | 5 |
| [09 — Streamlit dashboards](09-streamlit-dashboards/README.md) | The mental model, widgets, caching, layouts, multipage apps | 6 |
| [10 — Pipeline design](10-pipeline-design/README.md) | Stages, soft-fail, fallbacks, idempotency, provenance | 6 |
| [11 — The headline findings](11-the-findings/README.md) | How the analysis arrived at "users want explanations, not just unbans" | 4 |
| [12 — Exercises](12-exercises/README.md) | Concrete extensions you can implement to deepen understanding | 5 |
| [13 — The static frontend](13-the-static-frontend/README.md) | The self-contained CDN readout: no server, embedded data, the calm design system | 6 |
| [glossary.md](glossary.md) | Every term, with a one-paragraph plain-English definition | 1 |

## How long this takes

Reading every lesson once: about 15–20 hours.
Reading every lesson + running every code example + doing the exercises: about 40–60 hours.

You don't need to read modules in order, but the suggested path is **01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12**. Modules 03 and 04 are the conceptual hard core; the rest of the course makes more sense once you've absorbed those two.

## What you'll be able to do at the end

- Read a 1,000-line data-science Python file without fear.
- Recognise when to use TF-IDF vs embeddings, KMeans vs HDBSCAN, OLS vs logit.
- Use local LLMs (Gemma via Ollama) to extract structured data from messy text without paying for an API.
- Build a multi-page Streamlit dashboard that reads its data dynamically.
- Write defensive code that doesn't crash on real-world messy input.
- Reverse-engineer any other data-science codebase you encounter.

## How this course was built

Each lesson points at specific files and line numbers in this repository, e.g.:

> Open [scripts/option2_pipeline.py:152-212](../scripts/option2_pipeline.py) and read `featurize_tickets`. Notice the `pd.cut` call on line 199…

When you run into a code reference you don't immediately follow, **stop and read the function in your editor**. Reading explanations without reading the actual code teaches you nothing. Open both side by side.

## Author note

This course was generated *by* the codebase, *for* a person who has the data and the problem already in their head. If you don't have those, the lessons will read as confusing — they're optimized for a learner who is reverse-engineering a codebase they care about, not for a beginner reading a generic textbook.

Start with [00-how-to-use-this-course.md](00-how-to-use-this-course.md).
