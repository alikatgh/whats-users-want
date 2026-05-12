# Module 03 — Text and NLP

By the end of Module 02 you have a clean pandas DataFrame with a `model_text`
column: the user's question, URL-stripped, whitespace-collapsed, ready to be
fed to a model. This module is what happens to that column. It turns 6,728
free-form support tickets into numbers a clustering algorithm can chew on.

You will learn the two techniques the pipeline uses, in order of cost:
TF-IDF (cheap, sparse, language-blind) and sentence-transformers embeddings
(384 dense floats per ticket, multilingual, semantic). You will see why the
pipeline picks the second by default but still keeps the first around — both
as a fallback embedding backend and as a labelling tool that names every
cluster the embeddings produce.

## Prerequisites

- [Module 01 — Python Foundations](../01-python-foundations/README.md). You
  need `pathlib.Path`, raw-string regex, comprehensions, type hints, and the
  `try/except` import-fallback idiom without slowing down.
- [Module 02 — Data with pandas](../02-data-with-pandas/README.md). You need
  to know what `model_text` is, where it comes from, what
  `context_depth_score` measures, and how to load
  `enriched_tickets.csv`. This module starts from the column produced at the
  end of [Lesson 02-03](../02-data-with-pandas/03-feature-engineering.md).
- A working Python 3.10+ environment with the project's `requirements.txt`
  installed. The "Try it" exercises load `embeddings_local.npy` and the CSV
  outputs from `outputs/option2_20260502_150055/`. If that run is on disk
  you do not need a GPU or a model download to follow along.
- A rough memory of vector arithmetic — what a dot product is, what L2
  normalisation does. Module 04 will go deeper. Here we use only the cosine
  formula and `np.dot`.

## What you'll be able to do after this module

- Read [`make_text_matrix`](../../scripts/option2_pipeline.py) and explain
  every argument to `TfidfVectorizer`: `min_df=3`, `max_df=0.82`,
  `ngram_range=(1, 2)`, `strip_accents="unicode"`, `token_pattern=r"(?u)\b[\w][\w'-]{2,}\b"`,
  and `stop_words="english"`. You will know which of these protect you from
  domain noise and which from non-English content (and which fail to do so).
- Compare TF-IDF to the `CountVectorizer` used in
  [`bertopic_from_run.py`](../../scripts/bertopic_from_run.py) and explain
  why BERTopic uses raw counts at the labelling stage rather than IDF-weighted
  values.
- Explain what an embedding actually is — vectors in 384-dimensional space —
  and why the same model maps "I cannot login" and the Russian
  "разблокируйте мне аккаунт" to nearby points. You will be able to read
  [`embed_texts`](../../scripts/option2_pipeline.py) end to end, including
  the `.npy` cache and the `normalize_embeddings=True` flag.
- Justify the choice of `paraphrase-multilingual-MiniLM-L12-v2`: why
  multilingual, why MiniLM (small, fast), why 384 dimensions, what the
  HuggingFace cache looks like, and the cost trade-offs versus OpenAI
  embeddings.
- Compute a cluster centroid and a per-row centroid similarity by hand the
  way [`summarize`](../../scripts/build_user_wants_taxonomy.py) does:
  `embeddings[mask].mean(axis=0)` and
  `np.dot(embedding, centroid) / (||e|| * ||c||)`. You will use the resulting
  `centroid_similarity` to surface the most representative ticket in any
  cluster.
- Read the regex evidence flags in
  [`featurize_tickets`](../../scripts/option2_pipeline.py) the same way you
  read TF-IDF — as another text-feature engineering pass — and explain why
  the project keeps both representations side by side. You will know what
  the `context_depth_score` formula encodes that pure embeddings throw away.

## Lessons

| # | Lesson | What it covers |
|---|---|---|
| 01 | [Tokens and TF-IDF](01-tokens-and-tf-idf.md) | Tokens, term frequency, document frequency, IDF; every argument to `TfidfVectorizer`; real `top_terms` from `semantic_clusters.csv`; why TF-IDF stays as a labelling tool. |
| 02 | [Stopwords and ngrams](02-stopwords-and-ngrams.md) | What `stop_words="english"` drops, the hand-curated project `STOPWORDS`, bigrams via `ngram_range=(1, 2)`, and the `TruncatedSVD(n_components=80)` step. |
| 03 | [Embeddings intro](03-embeddings-intro.md) | A 384-dim vector. Cosine similarity. `SentenceTransformer.encode(...)`. Why `normalize_embeddings=True`. The `embeddings_local.npy` cache. |
| 04 | [Multilingual embeddings](04-multilingual-embeddings.md) | The specific model `paraphrase-multilingual-MiniLM-L12-v2`: why MiniLM, why paraphrase, why 384 dims; the HuggingFace cache layout; brief OpenAI comparison. |
| 05 | [Cosine similarity and centroids](05-cosine-similarity-and-centroids.md) | Dot product as similarity. Computing centroids with `embeddings[mask].mean(axis=0)`. Per-row similarity to surface representative tickets. |
| 06 | [Evidence and text features](06-evidence-and-text-features.md) | The other text-feature track: regex evidence flags, the `context_depth_score` formula, and why we keep both representations side by side. |

Each lesson ends with a runnable "Try it" against
`outputs/option2_20260502_150055/`. You will be loading
`semantic_cluster_assignments.csv`, `semantic_clusters.csv`,
`embeddings_local.npy`, `user_wants_taxonomy.csv`, and
`user_wants_assignments.csv` repeatedly.

## What's next

- [Module 04 — Dimensionality and Clustering](../04-dimensionality-and-clustering/README.md)
  takes the embeddings produced here, runs UMAP twice (once for plotting,
  once for clustering), then HDBSCAN, then formalises the per-cluster
  TF-IDF labelling step as **c-TF-IDF**.
- [Module 06 — LLMs and Prompts](../06-llms-and-prompts/README.md) shows
  how the same `model_text` column is sent to a local Ollama model
  (`gemma3:4b` in our run) to extract structured `(want, job, emotion,
  next_step)` tuples, which then feed back into a second clustering pass
  in [`build_user_wants_taxonomy.py`](../../scripts/build_user_wants_taxonomy.py).
