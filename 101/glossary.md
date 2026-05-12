# Glossary

Plain-English definitions of every term used in this course. Alphabetical.

When a term is the central topic of a lesson, the lesson link comes after
the definition.

---

**`@st.cache_data`** — Streamlit decorator that memoizes a function's
return value for given arguments. Used for DataFrames, lists, dicts —
immutable values that should be cheap to call repeatedly. Streamlit
stores a *copy* and hands a fresh copy on every cache hit.
[Module 09 lesson 04](09-streamlit-dashboards/04-caching.md).

**`@st.cache_resource`** — Streamlit decorator that memoizes a
function's return value but stores the *original object*. Used for
database connections, ML models, file handles — things that mustn't be
copied. Every cache hit returns the same instance.
[Module 09 lesson 04](09-streamlit-dashboards/04-caching.md).

**Adjusted manager context** — The OLS regression coefficient for each
manager's "richness of evidence" after controlling for the kind of
tickets they handle. Albert is the baseline at 0; everyone else is
expressed as a delta.
[Module 05 lesson 01](05-statistics/01-ols-with-fixed-effects.md).

**Anchor (regex)** — A regex character that matches a *position*
rather than a character. `\b` is a word boundary (between `\w` and
non-`\w`). `^` is the start of a line, `$` is the end. Used in
`USER_CLAIM_RE` and friends to match whole words.
[Module 01 lesson 02](01-python-foundations/02-regex.md).

**argparse** — Python standard library module for parsing command-line
arguments. Every script in `scripts/` uses it for its `--input`,
`--backend`, `--limit` flags.
[Module 01 lesson 07](01-python-foundations/07-decorators-closures-and-cli.md).

**BERTopic** — Topic-modeling library that combines embeddings + UMAP +
HDBSCAN + c-TF-IDF. Produces named topics like
`1_diamonds_buy_buy diamonds_money`. Used in
`scripts/bertopic_from_run.py`.
[Module 04 lesson 05](04-dimensionality-and-clustering/05-bertopic-and-c-tfidf.md).

**c-TF-IDF** — Class-based TF-IDF. Computes TF-IDF where each cluster
is treated as a single document. Words that are common inside a
cluster but rare across clusters bubble up as the cluster's distinctive
label.
[Module 04 lesson 05](04-dimensionality-and-clustering/05-bertopic-and-c-tfidf.md).

**`call_rules`** — The deterministic regex+lookup baseline backend in
`scripts/llm_extract_rich_tickets.py`. No LLM. Produces the same shape
of structured record as the LLM backends. Used as a sanity comparison
and as the skeleton for `ollama_hybrid`.
[Module 06 lesson 06](06-llms-and-prompts/06-rules-vs-llm-vs-hybrid.md).

**Canonicalize** — The `canonicalize` function in
`scripts/option2_pipeline.py` that resolves Chinese/English column
variants, parses dates, normalizes status strings.
[Module 02 lesson 02](02-data-with-pandas/02-cleaning-and-canonicalize.md).

**Centroid** — The mean point of a cluster in vector space. Used to
find the most representative tickets in a cluster (those closest to
the centroid).
[Module 04 lesson 06](04-dimensionality-and-clustering/06-cluster-quality-and-centroids.md).

**Closure** — A function that captures a variable from its enclosing
scope. `_first_existing(*names)` in `app.py` is a closure over
`run_dir`.
[Module 01 lesson 07](01-python-foundations/07-decorators-closures-and-cli.md).

**Cluster** — A group of items that are close to each other in some
similarity space. The pipeline produces several clusterings:
HDBSCAN/UMAP semantic clusters (Stage 1), BERTopic topics (Stage 2),
forced KMeans sub-themes (Stage 4), user-want clusters (Stage 6).

**Context depth score** — The weighted sum of evidence flags + length
features per ticket. Higher = richer note (more screenshots, IDs, ban
reasons). Range 0-100 in practice.
[Module 02 lesson 03](02-data-with-pandas/03-feature-engineering.md).

**Cosine similarity** — A measure of how similar two vectors are by
their angle (not magnitude). For L2-normalized vectors it equals the
dot product. Used to score how close a ticket is to its cluster
centroid.
[Module 03 lesson 05](03-text-and-nlp/05-cosine-similarity-and-centroids.md).

**Crosstab** — A two-way contingency table built with `pd.crosstab(rows,
cols)`. Each cell is the count of co-occurrences. The dashboard's
heatmaps are crosstabs rendered with `px.imshow`.
[Module 02 lesson 06](02-data-with-pandas/06-pivot-crosstab-and-categorical.md),
[Module 08 lesson 03](08-visualization/03-heatmaps-and-crosstabs.md).

**Curse of dimensionality** — The phenomenon that distances between
points become less meaningful in high-dimensional spaces. Why the
pipeline reduces 384-D embeddings to 8-D before clustering.
[Module 04 lesson 01](04-dimensionality-and-clustering/01-curse-of-dimensionality.md).

**Dataframe** — A pandas DataFrame, a 2-D table with named columns and
typed cells. The central data structure throughout this codebase.

**`df.attrs`** — A pandas dict attached to a DataFrame for metadata.
Used by `load_extractions` to record `source_file` so downstream code
knows which file was loaded without re-deriving the path.
[Module 10 lesson 05](10-pipeline-design/05-metadata-and-provenance.md).

**Diverging color scale** — A color scale that goes from one strong
color through a neutral middle to another strong color. Used when the
zero point is meaningful (e.g. delta vs benchmark). Example: `"RdBu"`
with `color_continuous_midpoint=0`.
[Module 08 lesson 04](08-visualization/04-when-to-hide-axes-and-color-scales.md).

**DESIRE_PATTERNS** — The dict of 10 regex-based human-desire
classifiers in `scripts/option2_pipeline.py`. Each ticket gets a
boolean flag per desire and a `primary_desire` from `idxmax`.
[Module 02 lesson 03](02-data-with-pandas/03-feature-engineering.md).

**Docstring** — A string literal at the start of a module, class, or
function that documents what it does. Read by `pdoc` to generate API
docs.

**DuckDB** — A local in-process SQL engine. The pipeline writes
`analysis.duckdb` per run; the dashboard's SQL Console queries it.
[Module 07 lesson 02](07-databases-and-storage/02-duckdb-basics.md).

**Embedding** — A vector representation of text where similar texts
land near each other. The pipeline uses
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` to embed
into 384 dimensions.
[Module 03 lesson 03](03-text-and-nlp/03-embeddings-intro.md).

**EVIDENCE_LABELS** — The list of 10 boolean evidence flags
contributing to `evidence_element_count` and the context depth score.
[Module 02 lesson 03](02-data-with-pandas/03-feature-engineering.md).

**f-string** — Python's formatted string literals: `f"{x:,}"` produces
`"1,000"` for `x=1000`. Used everywhere for formatting numbers and
percentages.
[Module 01 lesson 03](01-python-foundations/03-strings-and-formatting.md).

**Featurize** — The `featurize_tickets` function that adds ~25 derived
columns to each ticket: counts, flags, desire matches, urgency,
context score.
[Module 02 lesson 03](02-data-with-pandas/03-feature-engineering.md).

**Fixed effects** — Categorical dummy variables in a regression that
let the model account for differences between categories without
estimating their full distribution. Patsy's `C(...)` notation in
statsmodels.
[Module 05 lesson 01](05-statistics/01-ols-with-fixed-effects.md).

**Forensic ticket** — A ticket with `context_depth_score >= 60`.
Contains screenshots, timestamps, IDs, ban reasons, user quotes — all
the structured evidence the rest of the pipeline depends on.

**Gemma** — Google's open-weights small language model. The pipeline
uses `gemma3:4b` via Ollama for LLM extraction. ~3.3 GB on disk.
Free, no API key, no network calls.
[Module 06 lesson 07](06-llms-and-prompts/07-local-models-with-ollama.md).

**HC3 robust standard errors** — Heteroskedasticity-consistent
standard errors variant 3. Statsmodels' `cov_type="HC3"`. Used in
`adjusted_manager_context` because manager-residual variance varies
across categories.
[Module 05 lesson 02](05-statistics/02-robust-standard-errors.md).

**HDBSCAN** — Hierarchical density-based clustering. Finds dense
neighborhoods of points and labels low-density points as noise (`-1`).
Used in Stage 1 main clustering, BERTopic, and Stage 6 first attempt.
[Module 04 lesson 03](04-dimensionality-and-clustering/03-density-clustering-hdbscan.md).

**Heatmap** — A 2-D color-coded table. The dashboard uses
`pd.crosstab` → `px.imshow` heatmaps for want × emotion, want × money
risk, want × manager.
[Module 08 lesson 03](08-visualization/03-heatmaps-and-crosstabs.md).

**Hybrid backend** — The `ollama_hybrid` extraction backend that
runs the rules-based extractor first, then asks Gemma only for the
narrative interpretation fields. Robust on small models because the
rules layer catches the structured fields even when the LLM outputs
junk for the free-text ones.
[Module 06 lesson 06](06-llms-and-prompts/06-rules-vs-llm-vs-hybrid.md).

**Idempotency** — The property that re-running a stage with the same
inputs produces the same outputs and doesn't accumulate duplicates.
The marker-based section replacement in `executive_findings.md` is
the explicit case.
[Module 10 lesson 04](10-pipeline-design/04-marker-based-idempotency.md).

**`idxmax`** — Pandas method that returns the column name (or row
index) with the largest value. Used in `featurize_tickets` to pick
`primary_desire` from the first True boolean in the desire flags.
[Module 12 exercise 02](12-exercises/02-add-a-new-desire.md).

**Information schema** — Standard SQL system tables that describe the
database itself. `information_schema.tables` lists all tables;
`information_schema.columns` lists all columns. Used by the
dashboard's schema browser.
[Module 07 lesson 03](07-databases-and-storage/03-information-schema-and-introspection.md).

**JOB_ALIASES** — Dict mapping known LLM-output synonyms (e.g.
`investigate_fraud`) to canonical values (`avoid_scam`). The audit
field `_normalized_job_from` records the original.
[Module 06 lesson 05](06-llms-and-prompts/05-enum-aliases-and-normalization.md).

**JOB_VALUES** — The closed list of allowed `job_to_be_done` values
(13 entries). LLM outputs not in this list — and not in `JOB_ALIASES`
— get the quality flag `invalid_job`.
[Module 06 lesson 05](06-llms-and-prompts/05-enum-aliases-and-normalization.md).

**JSONL** — JSON Lines: one JSON object per line in a text file. The
extraction pipeline writes one JSONL line per ticket so a crashed run
can resume from the last completed line.
[Module 06 lesson 02](06-llms-and-prompts/02-json-mode-and-schemas.md).

**JSON mode** — A model API option that forces the response to be
valid JSON. OpenAI's `response_format={"type": "json_object"}` and
Ollama's `format: "json"`. Reduces parsing failures dramatically.
[Module 06 lesson 02](06-llms-and-prompts/02-json-mode-and-schemas.md).

**KMeans** — Clustering algorithm that partitions points into exactly
`k` clusters by minimizing within-cluster variance. Used as a fallback
when HDBSCAN refuses to label most points.
[Module 04 lesson 04](04-dimensionality-and-clustering/04-kmeans-fallback.md).

**`latest_run`** — Helper in `scripts/dashboard/lib.py` and
`scripts/insight_layer.py` that returns the newest `option2_*`
directory. Sorted-glob-with-timestamped-names idiom.
[Module 10 lesson 03](10-pipeline-design/03-priority-fallback.md).

**Lazy import** — Importing a module *inside* the function that needs
it instead of at the top of the file. Used for heavy/optional
libraries (UMAP, HDBSCAN, statsmodels, networkx) so the module loads
even with a partial environment.
[Module 10 lesson 02](10-pipeline-design/02-soft-fail-imports.md).

**LIB / `lib.py`** — `scripts/dashboard/lib.py`. Shared helpers used
by every dashboard page: `run_picker`, `maybe_load_csv`, `counts_df`,
`humanize_desire`, `friendly_want_title`, etc.
[Module 09 lesson 02](09-streamlit-dashboards/02-multipage-apps.md).

**Linear probability model (LPM)** — OLS regression on a 0/1 outcome.
We use it in `build_context_value_model` because logit hits separation
issues with sparse categorical dummies. Coefficients are interpretable
as probability points (multiply by 100).
[Module 05 lesson 03](05-statistics/03-linear-probability-model.md).

**MiniBatchKMeans** — KMeans variant that processes batches of points
at a time. Faster for large datasets. Used in `split_outlier_bucket.py`
with `n_init=30`.
[Module 04 lesson 04](04-dimensionality-and-clustering/04-kmeans-fallback.md).

**MiniLM-L12-v2** — The 384-dimensional sentence-transformer model
used throughout. Specifically `paraphrase-multilingual-MiniLM-L12-v2`
— multilingual, paraphrase-trained, ~480 MB on disk.
[Module 03 lesson 04](03-text-and-nlp/04-multilingual-embeddings.md).

**Module-level constant** — A constant defined at the top of a Python
file, like `URL_RE = re.compile(...)`. Computed once at import time
and reused everywhere.
[Module 01 lesson 02](01-python-foundations/02-regex.md).

**Multi-page app** — A Streamlit app with one entry-point script and a
`pages/` folder. Each `.py` in `pages/` becomes a page in the sidebar.
[Module 09 lesson 02](09-streamlit-dashboards/02-multipage-apps.md).

**Ngram** — A sequence of `n` adjacent tokens. `ngram_range=(1, 2)` in
TfidfVectorizer means "include unigrams (single words) and bigrams
(pairs of adjacent words)."
[Module 03 lesson 02](03-text-and-nlp/02-stopwords-and-ngrams.md).

**Noise bucket** — In HDBSCAN, the cluster labelled `-1` containing
points the algorithm couldn't confidently assign. Stage 4 splits
the noise bucket from BERTopic with KMeans.
[Module 04 lesson 03](04-dimensionality-and-clustering/03-density-clustering-hdbscan.md).

**OLS** — Ordinary Least Squares. The most basic regression. Fits a
straight line / hyperplane to minimize squared residuals. Used in
`adjusted_manager_context` and `build_context_value_model`.
[Module 05 lesson 01](05-statistics/01-ols-with-fixed-effects.md).

**Ollama** — Local LLM runtime that exposes a small HTTP API at
`localhost:11434`. The pipeline POSTs to `/api/chat` for extraction.
[Module 06 lesson 07](06-llms-and-prompts/07-local-models-with-ollama.md).

**Opportunity score** — The composite metric in `opportunity_backlog.csv`
that ranks topics for action. Combines volume, unresolved share,
recent lift, and trust/money risk.
[Module 03 / module 05 lesson 04](05-statistics/04-two-proportion-z-test.md).

**Orchestrator** — The `run(args)` function in each stage's script
that calls the work functions in order. Separates business logic
(work functions) from glue (orchestrator) from CLI (`__main__`).
[Module 10 lesson 06](10-pipeline-design/06-orchestrator-pattern.md).

**Parameterized SQL** — SQL with `?` placeholders that the database
driver fills in safely from a separate params list. Prevents SQL
injection. Used in the dashboard's Find a Ticket and SQL Console
pages.
[Module 07 lesson 04](07-databases-and-storage/04-parameterized-queries-and-injection.md).

**Parquet** — Columnar binary storage format. Compressed, typed,
fast to read. The pipeline writes `parquet/` versions of every CSV
for fast Python/R/DuckDB access.
[Module 07 lesson 01](07-databases-and-storage/01-csv-vs-parquet.md).

**`pd.cut`** — Pandas function that bins a numeric column into
named ranges. Used to map `context_depth_score` to
`thin/basic/rich/forensic` bands.
[Module 02 lesson 03](02-data-with-pandas/03-feature-engineering.md).

**`pd.crosstab`** — Pandas function that builds a two-way contingency
table. The right primitive for "how many of A vs B?" Co-occurrence
counts.
[Module 02 lesson 06](02-data-with-pandas/06-pivot-crosstab-and-categorical.md).

**Plotly Express** — High-level plotting API on top of Plotly.
`px.scatter`, `px.bar`, `px.histogram`, `px.box`, `px.imshow`. Every
dashboard chart uses Plotly Express.
[Module 08 lesson 02](08-visualization/02-interactive-charts-with-plotly.md).

**Primary desire** — The first matching desire from `DESIRE_PATTERNS`
per ticket, picked by `idxmax`. Falls back to `unclear_or_needs_llm`
if no rule matches.
[Module 02 lesson 03](02-data-with-pandas/03-feature-engineering.md).

**Priority fallback** — The pattern of trying a list of candidate
filenames in order and using the first one that exists.
`_first_existing`, `latest_run`, `load_extractions`.
[Module 10 lesson 03](10-pipeline-design/03-priority-fallback.md).

**Provenance** — The trail of metadata that lets you trace an output
back to its inputs and parameters. Each stage writes a
`*_metadata.json` file recording its inputs and outputs.
[Module 10 lesson 05](10-pipeline-design/05-metadata-and-provenance.md).

**Quality flag** — A short string indicating *why* an LLM output
failed validation (`schema_echo`, `invalid_job`, `too_vague`, etc.).
Stored in the `_quality_flag` column of extraction outputs alongside
`_status = "bad_output"`.
[Module 06 lesson 04](06-llms-and-prompts/04-validation-and-quality-flags.md).

**Recent lift** — `(p_recent + 0.0005) / (p_baseline + 0.0005)`, the
ratio of last-30-days share to baseline share for a topic. Used in
the opportunity score and emerging-topic detection.
[Module 05 lesson 04](05-statistics/04-two-proportion-z-test.md).

**Regex** — Regular expression. Compact pattern for matching strings.
The pipeline uses ~20 regex patterns to extract evidence elements,
detect desires, and clean colleague-pivot rows.
[Module 01 lesson 02](01-python-foundations/02-regex.md).

**Residual** — The difference between an observed value and the
value the model predicted. Manager context residuals subtract the
expected (category, question_kind) cell mean from each ticket's
score; the per-manager average residual is the non-parametric
analogue of the OLS-adjusted delta.
[Module 05 lesson 05](05-statistics/05-percentile-capping-and-residuals.md).

**Risk levels** — The four 1-5 scores per ticket from the LLM:
urgency, trust, money, safety/policy. Used to rank clusters by combined
risk.
[Module 06 lesson 04](06-llms-and-prompts/04-validation-and-quality-flags.md),
[Module 11 lesson 04](11-the-findings/04-money-trust-urgency.md).

**Run directory** — A timestamped folder under `outputs/option2_*`
holding all artifacts from one pipeline run. Stages read from and
write to this directory; the directory itself is the message bus.
[Module 10 lesson 01](10-pipeline-design/01-stages-and-runs.md).

**`run_picker`** — The sidebar selectbox helper in
`scripts/dashboard/lib.py` that lets users pick a run directory.
Every dashboard page calls it.
[Module 09 lesson 03](09-streamlit-dashboards/03-widgets-and-state.md).

**Sample silhouette** — Silhouette score computed on a random subset
to avoid the O(n²) cost. The Stage 4 outlier split uses a 1,200-row
cosine sample.
[Module 04 lesson 06](04-dimensionality-and-clustering/06-cluster-quality-and-centroids.md).

**Schema** — The JSON shape we ask the LLM to fill in. Defined as a
dict in `llm_extract_rich_tickets.py` with description strings as
values.
[Module 06 lesson 02](06-llms-and-prompts/02-json-mode-and-schemas.md).

**Sentence-transformers** — The Python library that loads
sentence-embedding models. Heavy on first run (downloads ~480 MB);
fast thereafter.
[Module 03 lesson 03](03-text-and-nlp/03-embeddings-intro.md).

**Sequential color scale** — A color scale that goes from light to
dark in one direction. Used when zero is the meaningful baseline.
Examples: `"Blues"`, `"Reds"`, `"Greens"`.
[Module 08 lesson 04](08-visualization/04-when-to-hide-axes-and-color-scales.md).

**`session_state`** — Streamlit's per-browser-session dict that
survives reruns. Used to share the chosen run directory across pages.
[Module 09 lesson 01](09-streamlit-dashboards/01-streamlit-mental-model.md).

**Silhouette score** — A clustering quality metric. For each point,
compares its mean intra-cluster distance to its mean nearest-cluster
distance. Range -1 to 1; higher is better.
[Module 04 lesson 06](04-dimensionality-and-clustering/06-cluster-quality-and-centroids.md).

**Soft-fail** — The pattern of catching `ImportError` (or any
exception) and continuing with a degraded but still-useful result.
The pipeline soft-fails when UMAP, HDBSCAN, statsmodels, networkx, or
Plotly is missing.
[Module 10 lesson 02](10-pipeline-design/02-soft-fail-imports.md).

**Stage** — One pipeline script. Six stages: pipeline, BERTopic,
insight layer, outlier split, LLM extraction, taxonomy.
[Module 10 lesson 01](10-pipeline-design/01-stages-and-runs.md).

**`status_cn`** — The Chinese-language status column. Mostly contains
`已解决` ("resolved"); pipeline maps it to `is_resolved` along with
the English `Status`.
[Module 02 lesson 02](02-data-with-pandas/02-cleaning-and-canonicalize.md).

**Stopword** — A common word that's filtered out before text analysis.
TfidfVectorizer's `stop_words="english"` removes "the", "and", "is",
etc. The taxonomy builder has its own project-specific stopwords
(`STOPWORDS` in `build_user_wants_taxonomy.py`).
[Module 03 lesson 02](03-text-and-nlp/02-stopwords-and-ngrams.md).

**Streamlit** — Python framework for building data dashboards.
Top-to-bottom rerun model: your script runs in full on every
interaction. The dashboard is built on it.
[Module 09 lesson 01](09-streamlit-dashboards/01-streamlit-mental-model.md).

**Summary row** — A row in the original CSV with no Question text
and no UID — usually a colleague's pivot/aggregation entry. The
pipeline drops these at ingest.
[Module 02 lesson 01](02-data-with-pandas/01-reading-messy-csv.md).

**Taxonomy** — A discovered or hand-coded set of categories. The
pipeline produces three: hand-coded desires (10), BERTopic topics (53
+ noise), LLM-extracted user wants (17).

**TF-IDF** — Term frequency × inverse document frequency. Weights
each token in a document by how rare it is across the corpus.
Cheaper than embeddings; surfaces distinctive vocabulary.
[Module 03 lesson 01](03-text-and-nlp/01-tokens-and-tf-idf.md).

**Token** — A single word (or word-piece). TfidfVectorizer's
`token_pattern` controls what counts. The default
`r"(?u)\b[\w][\w'-]{2,}\b"` matches word-character runs ≥3 chars.

**TruncatedSVD** — Dimensionality reduction for sparse matrices.
Reduces a TF-IDF matrix from thousands of columns to ~80 for clustering.
[Module 03 lesson 02](03-text-and-nlp/02-stopwords-and-ngrams.md).

**Two-proportion z-test** — Statistical test for whether two
proportions differ beyond chance.
`z = (p_a - p_b) / sqrt(p_pool * (1-p_pool) * (1/n_a + 1/n_b))`. Used
in `build_opportunity_backlog` as `trend_z`.
[Module 05 lesson 04](05-statistics/04-two-proportion-z-test.md).

**UMAP** — Uniform Manifold Approximation and Projection. Reduces
high-dim vectors to 2-D (visualization) or 8-D (clustering) while
preserving local neighborhood structure.
[Module 04 lesson 02](04-dimensionality-and-clustering/02-umap.md).

**Unresolved share** — Fraction of tickets where `is_unresolved` is
True. Used as a topic quality signal in the opportunity score.

**`urllib.request`** — Python standard library HTTP client. The
pipeline uses it to POST JSON to `localhost:11434/api/chat` for Ollama.
No `requests` dependency needed.
[Module 06 lesson 07](06-llms-and-prompts/07-local-models-with-ollama.md).

**Want cluster** — One of the 17 (or whatever-k-was-chosen) clusters
discovered by Stage 6. Each cluster has a Gemma-generated friendly
title, a list of representative tickets, average risk scores, and a
suggested next step.
[Module 11 lesson 02](11-the-findings/02-the-want-taxonomy-emerged.md).

**WebGL** — Hardware-accelerated rendering mode for Plotly scatters.
`render_mode="webgl"` lets the Ticket Map page draw 6,728 dots smoothly.
[Module 08 lesson 02](08-visualization/02-interactive-charts-with-plotly.md).

**Word boundary** — `\b` in regex. Matches the position between a
word character (`\w`) and a non-word character. Used to prevent
"ban" from matching inside "banner".
[Module 01 lesson 02](01-python-foundations/02-regex.md).

---

If a term shows up in the course but isn't here, it's an oversight.
Open an issue or add the entry yourself — the file is alphabetical and
each entry is one paragraph plus a lesson link.
