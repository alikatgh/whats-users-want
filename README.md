# Option 2 User-Needs Analysis

This project analyzes `data_2may.csv` with a serious Python-first data science stack:

- DuckDB/Polars/Pandas style analytical layer
- Evidence/context feature extraction from support notes
- Manager context-quality scoring that rewards detailed tickets
- Human desire taxonomy over raw ticket text
- TF-IDF/SVD or embedding-based NLP
- UMAP/HDBSCAN semantic clustering when available
- Optional R/quanteda validation scaffold

## Setup

```bash
.venv/bin/python -m pip install -r requirements.txt
```

## Local Data

The source CSV and generated run artifacts are intentionally not committed.
Place the private export at `data_2may.csv`, then run the pipeline below. Each
run writes a local `outputs/option2_<timestamp>/` folder.

## Run Fully Local Baseline

```bash
.venv/bin/python scripts/option2_pipeline.py --input data_2may.csv --embedding-backend tfidf
```

## Run Local Embeddings

This downloads a Sentence Transformers model if it is not cached:

```bash
.venv/bin/python scripts/option2_pipeline.py \
  --input data_2may.csv \
  --embedding-backend local \
  --embedding-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

## Run OpenAI Embeddings

```bash
export OPENAI_API_KEY=...
.venv/bin/python scripts/option2_pipeline.py \
  --input data_2may.csv \
  --embedding-backend openai \
  --embedding-model text-embedding-3-small
```

## Outputs

Each run creates `outputs/option2_<timestamp>/` with:

- `enriched_tickets.csv`
- `manager_context_quality.csv`
- `adjusted_manager_context_model.csv`
- `desire_summary.csv`
- `semantic_clusters.csv`
- `semantic_cluster_assignments.csv`
- `high_context_examples.csv`
- `semantic_ticket_map.html`
- `option2_analysis_workbook.xlsx`
- `executive_findings.md`
- `parquet/*.parquet`
- `analysis.duckdb`

## Add BERTopic Topics

After a local embedding run, add c-TF-IDF topic modeling with BERTopic:

```bash
.venv/bin/python scripts/bertopic_from_run.py outputs/option2_YYYYMMDD_HHMMSS
```

This writes:

- `bertopic_topics.csv`
- `bertopic_assignments.csv`
- `bertopic_barchart.html`

## Add Decision Insight Layer

After the semantic run and optional BERTopic step:

```bash
.venv/bin/python scripts/insight_layer.py outputs/option2_YYYYMMDD_HHMMSS
```

This appends a decision section to `executive_findings.md` and writes:

- `opportunity_backlog.csv`
- `emerging_topics.csv`
- `repeat_user_personas.csv`
- `manager_context_residuals.csv`
- `issue_evidence_gaps.csv`
- `context_value_model.csv`
- `manager_evidence_coaching.csv`
- `insight_layer_workbook.xlsx`

## Split BERTopic Outlier Bucket

BERTopic topic `-1` is usually a large mixed bucket. Split it into forced semantic subthemes using cached local embeddings:

```bash
.venv/bin/python scripts/split_outlier_bucket.py outputs/option2_YYYYMMDD_HHMMSS
```

This writes:

- `outlier_subtopics.csv`
- `outlier_subtopic_assignments.csv`
- `refined_opportunity_backlog.csv`
- `outlier_subtopic_map.html`
- `outlier_split_workbook.xlsx`

## Queue Or Run Local Extraction

Free rule-based preview, no model/API required:

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_YYYYMMDD_HHMMSS \
  --backend rules \
  --limit 250 \
  --strategy risk_balanced
```

This writes:

- `rules_extractions.jsonl`
- `rules_extractions.csv`
- `llm_extractions.csv`

## Queue Or Run Local Model Extraction

Recommended free LLM path: Ollama + Mistral Small 3.2. Install Ollama separately, then pull the model:

```bash
ollama pull mistral-small3.2:24b
ollama serve
```

In another terminal:

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_YYYYMMDD_HHMMSS \
  --backend ollama \
  --model mistral-small3.2:24b \
  --limit 1400 \
  --strategy risk_balanced
```

The current published run used `--limit 1400` on a rented RunPod GPU and confirmed
**1,348 tickets** (1,348 ok / 0 bad / 0 error). On a laptop, drop `--limit` to ~250
for a quick smoke test. See `docs/11-runpod-mistral-runbook.md`.

Safer small-model path:

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_YYYYMMDD_HHMMSS \
  --backend ollama_hybrid \
  --model mistral-small3.2:24b \
  --limit 250 \
  --strategy risk_balanced
```

`ollama_hybrid` uses deterministic evidence/job extraction first, then asks the local model only for human interpretation fields. This avoids small models over-collapsing everything into one job label.

This writes:

- `ollama_<model>_extractions.jsonl`
- `ollama_<model>_extractions.csv`
- `ollama_hybrid_<model>_extractions.jsonl` / `ollama_hybrid_<model>_extractions.csv` for hybrid runs
- `ollama_extractions.jsonl` / `ollama_extractions.csv` as latest local aliases
- `llm_extractions.csv`
- `llm_extraction_response_schema.json` as the formal JSON Schema sent to Ollama structured-output mode

Local model notes:

- `mistral-small3.2:24b`: **the current production model.** The May-2026 RunPod GPU run read 1,348 tickets with it (1,348 ok / 0 bad / 0 error) and produced the current 20-want taxonomy and longitudinal layer (`outputs/option2_20260513_030517/`). Best instruction-following and structured output; fits a rented RTX 4090-class GPU.
- `gemma3:4b`: the original free laptop baseline (250-ticket smoke test → 17 wants). Still owns the BERTopic / outlier / opportunity-backlog layers in `outputs/option2_20260502_150055/`, which were not re-run on Mistral.
- `gemma3:1b`: valid local JSON but over-collapses jobs; only usable via the hybrid path.
- `gemma3:270m`: proves the pipeline works but too weak for ticket-intent extraction.

Model comparison artifacts:

- `local_llm_model_comparison.csv`
- `local_llm_model_comparison.md`

## Build "What Users Want" Taxonomy

After local LLM extraction (mistral-small3.2:24b, the current run's model), cluster the extracted want/job/opportunity fields into a real user-want taxonomy:

```bash
.venv/bin/python scripts/build_user_wants_taxonomy.py outputs/option2_YYYYMMDD_HHMMSS
```

Defaults: HDBSCAN with auto-fallback to KMeans when too sparse. Override with `--method kmeans --n-clusters 15`.

This writes:

- `user_wants_taxonomy.csv` — one row per discovered want with size, share, top jobs, emotions, money/trust/urgency averages, examples, next-step examples
- `user_wants_assignments.csv` — per-ticket want assignments with centroid similarity, joined back to manager/category/date when available
- `user_wants_workbook.xlsx` — taxonomy + cross-tabs (want × emotion, want × money_risk, want × manager)
- `user_wants_findings.md` — human-readable summary
- `user_wants_metadata.json`

## Project User Wants To The Full Corpus

After the taxonomy is built, map every cleaned ticket to the discovered wants without sending every short row through the local LLM:

```bash
.venv/bin/python scripts/project_user_wants_full_corpus.py outputs/option2_YYYYMMDD_HHMMSS
```

This writes:

- `user_wants_all_assignments.csv` — every cleaned ticket mapped to a discovered want with a confidence band
- `user_wants_full_corpus_summary.csv` — estimated full-corpus size/share per want
- `user_wants_review_queue.csv` — ambiguous or high-risk rows worth a targeted follow-up LLM pass
- `user_wants_full_corpus_workbook.xlsx`
- `user_wants_projection_metadata.json`

## Queue Or Run Paid/API Extraction

Dry-run first. This creates the candidate queue, schema, and prompt without API calls:

```bash
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_YYYYMMDD_HHMMSS --dry-run
```

To run extraction after reviewing the queue:

```bash
export OPENAI_API_KEY=...
.venv/bin/python scripts/llm_extract_rich_tickets.py outputs/option2_YYYYMMDD_HHMMSS --limit 250 --strategy risk_balanced
```

This writes:

- `llm_extraction_candidates.csv`
- `llm_extraction_schema.json`
- `llm_extraction_prompt.md`
- `llm_extractions.jsonl`
- `llm_extractions.csv`

## Core Idea

Albert-style detailed notes are not treated as messy long text. They are treated as analytical evidence: screenshots, URLs, timestamps, ban reasons, room/group IDs, user claims, and escalation context.
