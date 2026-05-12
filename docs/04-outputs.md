# 04 — Output Files Reference

Everything is in [outputs/option2_20260502_150055/](../outputs/option2_20260502_150055/). Open the file types you know first (Excel, CSV, Markdown, HTML), then dig into the rest if asked.

## For presenting

These four files are enough for a 20-minute presentation:

| File | What it is | When to show it |
|---|---|---|
| [executive_findings.md](../outputs/option2_20260502_150055/executive_findings.md) | Master narrative, all stages summarized | Outline / talking points |
| [user_wants_findings.md](../outputs/option2_20260502_150055/user_wants_findings.md) | The 17-want taxonomy in plain English | Headline finding section |
| [insight_layer_workbook.xlsx](../outputs/option2_20260502_150055/insight_layer_workbook.xlsx) | Opportunity backlog, personas, evidence gaps | "What we should do next" section |
| [semantic_ticket_map.html](../outputs/option2_20260502_150055/semantic_ticket_map.html) | Interactive 2D map of all 6,728 tickets | Optional visual cherry on top |

## Stage 1 — pipeline outputs

| File | Rows | What it has |
|---|---|---|
| [enriched_tickets.csv](../outputs/option2_20260502_150055/enriched_tickets.csv) | 6,728 | Every ticket + all evidence flags + context score + desire tags |
| [semantic_clusters.csv](../outputs/option2_20260502_150055/semantic_clusters.csv) | ~30 | One row per cluster with size, terms, dominant desires |
| [semantic_cluster_assignments.csv](../outputs/option2_20260502_150055/semantic_cluster_assignments.csv) | 6,728 | Which cluster each ticket landed in + 2D coordinates |
| [manager_context_quality.csv](../outputs/option2_20260502_150055/manager_context_quality.csv) | ~10 | Per-manager evidence stats |
| [adjusted_manager_context_model.csv](../outputs/option2_20260502_150055/adjusted_manager_context_model.csv) | ~10 | Per-manager delta vs. Albert with p-values |
| [desire_summary.csv](../outputs/option2_20260502_150055/desire_summary.csv) | 10 | Per-desire volume, unresolved share, avg context |
| [high_context_examples.csv](../outputs/option2_20260502_150055/high_context_examples.csv) | ~50 | Hand-pickable examples of rich tickets |
| [option2_analysis_workbook.xlsx](../outputs/option2_20260502_150055/option2_analysis_workbook.xlsx) | — | All Stage 1 tables in one Excel file |
| [semantic_ticket_map.html](../outputs/option2_20260502_150055/semantic_ticket_map.html) | — | Interactive UMAP map; hover a dot to read the ticket |
| [embeddings_local.npy](../outputs/option2_20260502_150055/embeddings_local.npy) | — | The 6728×384 embedding matrix; needed if you re-run downstream stages |
| [analysis.duckdb](../outputs/option2_20260502_150055/analysis.duckdb) | — | DuckDB database; query with `duckdb` CLI or Python |
| [parquet/](../outputs/option2_20260502_150055/parquet/) | — | Parquet copies of every table for fast loading |
| [executive_findings.md](../outputs/option2_20260502_150055/executive_findings.md) | — | The big Markdown narrative |
| [run_metadata.json](../outputs/option2_20260502_150055/run_metadata.json) | — | Run config snapshot |

Charts (PNG):
- [manager_context_depth.png](../outputs/option2_20260502_150055/manager_context_depth.png)
- [context_depth_vs_outcome.png](../outputs/option2_20260502_150055/context_depth_vs_outcome.png)
- [desire_trends.png](../outputs/option2_20260502_150055/desire_trends.png)

## Stage 2 — BERTopic outputs

| File | What it has |
|---|---|
| [bertopic_topics.csv](../outputs/option2_20260502_150055/bertopic_topics.csv) | 53 topics with top words and counts |
| [bertopic_assignments.csv](../outputs/option2_20260502_150055/bertopic_assignments.csv) | 6,669 ticket → topic assignments |
| [bertopic_barchart.html](../outputs/option2_20260502_150055/bertopic_barchart.html) | Interactive top-words-per-topic chart |
| [bertopic_metadata.json](../outputs/option2_20260502_150055/bertopic_metadata.json) | Run config |

## Stage 3 — Insight layer

| File | What it has |
|---|---|
| [opportunity_backlog.csv](../outputs/option2_20260502_150055/opportunity_backlog.csv) | Ranked product/support actions per topic |
| [emerging_topics.csv](../outputs/option2_20260502_150055/emerging_topics.csv) | Topics growing in the last 30 days |
| [repeat_user_personas.csv](../outputs/option2_20260502_150055/repeat_user_personas.csv) | 7-persona breakdown of 1,233 repeat users |
| [manager_context_residuals.csv](../outputs/option2_20260502_150055/manager_context_residuals.csv) | Per-manager context residual after controlling for ticket mix |
| [issue_evidence_gaps.csv](../outputs/option2_20260502_150055/issue_evidence_gaps.csv) | Per-topic evidence gap profile |
| [manager_evidence_coaching.csv](../outputs/option2_20260502_150055/manager_evidence_coaching.csv) | Per-manager improvement checklist |
| [context_value_model.csv](../outputs/option2_20260502_150055/context_value_model.csv) | Logistic regression coefficients on resolution |
| [insight_layer_workbook.xlsx](../outputs/option2_20260502_150055/insight_layer_workbook.xlsx) | All Stage 3 tables in Excel |

## Stage 4 — Outlier split

| File | What it has |
|---|---|
| [outlier_subtopics.csv](../outputs/option2_20260502_150055/outlier_subtopics.csv) | 26 sub-themes from the BERTopic noise bucket |
| [outlier_subtopic_assignments.csv](../outputs/option2_20260502_150055/outlier_subtopic_assignments.csv) | 1,331 ticket → sub-theme assignments |
| [outlier_subtopic_map.html](../outputs/option2_20260502_150055/outlier_subtopic_map.html) | Interactive map of the sub-themes |
| [refined_opportunity_backlog.csv](../outputs/option2_20260502_150055/refined_opportunity_backlog.csv) | 79-row backlog re-ranked with sub-themes |
| [outlier_split_workbook.xlsx](../outputs/option2_20260502_150055/outlier_split_workbook.xlsx) | All Stage 4 tables in Excel |
| [outlier_split_metadata.json](../outputs/option2_20260502_150055/outlier_split_metadata.json) | Run config |
| [outlier_split_metrics.csv](../outputs/option2_20260502_150055/outlier_split_metrics.csv) | Cluster-quality metrics |

## Stage 5 — LLM extraction

| File | What it has |
|---|---|
| [llm_extraction_candidates.csv](../outputs/option2_20260502_150055/llm_extraction_candidates.csv) | The 250 selected rich tickets |
| [llm_extraction_schema.json](../outputs/option2_20260502_150055/llm_extraction_schema.json) | JSON schema the model is asked to follow |
| [llm_extraction_prompt.md](../outputs/option2_20260502_150055/llm_extraction_prompt.md) | Exact prompt sent to the model |
| [llm_extraction_status.json](../outputs/option2_20260502_150055/llm_extraction_status.json) | Backend, model, completion stats |
| [ollama_gemma3-4b_extractions.csv](../outputs/option2_20260502_150055/ollama_gemma3-4b_extractions.csv) | 250 structured records (the main output) |
| [ollama_gemma3-4b_extractions.jsonl](../outputs/option2_20260502_150055/ollama_gemma3-4b_extractions.jsonl) | Same data, line-delimited JSON |
| [ollama_gemma3-1b_extractions.csv](../outputs/option2_20260502_150055/ollama_gemma3-1b_extractions.csv) | 1B-model smoke test results (for comparison) |
| [ollama_gemma3-270m_extractions.csv](../outputs/option2_20260502_150055/ollama_gemma3-270m_extractions.csv) | 270M-model smoke test results |
| [ollama_hybrid_extractions.csv](../outputs/option2_20260502_150055/ollama_hybrid_extractions.csv) | Rules+1B hybrid extraction (smoke test) |
| [rules_extractions.csv](../outputs/option2_20260502_150055/rules_extractions.csv) | Pure rule-based extraction baseline |
| [llm_extractions.csv](../outputs/option2_20260502_150055/llm_extractions.csv) | Alias for the latest local extraction (currently 4B) |
| [local_llm_model_comparison.md](../outputs/option2_20260502_150055/local_llm_model_comparison.md) | Why we chose 4B over 1B over 270M |
| [local_llm_model_comparison.csv](../outputs/option2_20260502_150055/local_llm_model_comparison.csv) | Same data in CSV form |
| [extraction_250.log](../outputs/option2_20260502_150055/extraction_250.log) | Run log for the 250-ticket extraction |

## Stage 6 — User-wants taxonomy

| File | What it has |
|---|---|
| [user_wants_taxonomy.csv](../outputs/option2_20260502_150055/user_wants_taxonomy.csv) | 17 wants with size, share, jobs, emotions, risk averages, examples |
| [user_wants_assignments.csv](../outputs/option2_20260502_150055/user_wants_assignments.csv) | 250 ticket → want assignments |
| [user_wants_workbook.xlsx](../outputs/option2_20260502_150055/user_wants_workbook.xlsx) | Taxonomy + want×emotion + want×money_risk + want×manager cross-tabs |
| [user_wants_findings.md](../outputs/option2_20260502_150055/user_wants_findings.md) | Markdown summary of the taxonomy |
| [user_wants_metadata.json](../outputs/option2_20260502_150055/user_wants_metadata.json) | Run config |
