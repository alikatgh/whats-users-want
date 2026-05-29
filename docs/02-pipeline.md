# 02 — Pipeline Walkthrough

The pipeline has seven stages. Each is a separate script in [scripts/](../scripts/). They write into the same run directory under `outputs/option2_<timestamp>/`. The current **want layer** (Stages 5–7) is `outputs/option2_20260513_030517/` (Mistral, 1,348 tickets). The **BERTopic / outlier / opportunity layers** (Stages 2–4) live only in the earlier free run `outputs/option2_20260502_150055/` (Gemma) and were not re-run on Mistral.

```
Stage 1  option2_pipeline.py          → clean, embed, cluster, score managers
Stage 2  bertopic_from_run.py         → validate clusters with topic modeling
Stage 3  insight_layer.py             → opportunity backlog, personas, evidence gaps
Stage 4  split_outlier_bucket.py      → split BERTopic noise bucket into 26 sub-themes
Stage 5  llm_extract_rich_tickets.py  → run a local Ollama model on rich tickets
Stage 6  build_user_wants_taxonomy.py → cluster extracted wants into a final taxonomy
Stage 7  project_user_wants_full_corpus.py → map every cleaned ticket to the learned wants
```

Each stage reads the artifacts from earlier stages. You can rerun any stage on its own.

---

## Stage 1 — `option2_pipeline.py`

**Purpose.** Turn raw CSV into a clean, feature-rich, semantically-clustered dataset.

**Inputs.** `data_2may.csv`

**What it does.**

1. **Robust CSV read.** Handles multi-line tickets (long manager notes that span lines). Result: 6,728 tickets, not the naive 15k rows.
2. **Light cleaning.** Trims whitespace, normalizes status/category strings across English/Russian/Chinese, parses dates, deduplicates trivial cases.
3. **Evidence feature extraction.** For each ticket, ten boolean flags are computed by regex:
    - `has_url`, `has_image_url`, `has_timestamp`, `has_room_or_group_id`, `has_long_uid_or_case_id`, `has_ban_reason_language`, `has_user_claim`, `has_money_terms`, `has_status_or_svip_terms`, `has_multiline_note`.
    - These become the **`context_depth_score`** — a single number per ticket measuring how much evidence the manager attached.
4. **Human-desire taxonomy (rule-based first pass).** Each ticket is tagged against ten coarse desires (recover_access, clear_name_or_get_fairness, earn_or_transact_money, grow_audience_or_community, gain_status_or_privileges, protect_from_abuse_or_scam, fix_product_or_technical_flow, understand_rules_or_system_logic, customize_identity_or_assets, play_or_entertainment).
5. **Semantic embeddings.** Each ticket's text is run through `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (a local 384-dimensional multilingual embedding model). Output: a 6,728 × 384 matrix saved as `embeddings_local.npy`.
6. **2D map + clustering.** UMAP reduces embeddings to 2D for visualization; HDBSCAN clusters the high-dimensional embeddings. Output: ~30 semantic clusters and a noise bucket.
7. **Manager context modeling.** A linear regression of `context_depth_score` on category, question kind, role, status, and month, with manager fixed effects. Tells us which managers add more evidence than peers, *after controlling for what they happen to handle*. Albert is the benchmark.
8. **DuckDB analytical store.** Every output table is also written into `analysis.duckdb` so future analyses can join easily.

**Key outputs.**
- `enriched_tickets.csv` — every ticket with all extracted features
- `semantic_clusters.csv` + `semantic_cluster_assignments.csv`
- `manager_context_quality.csv` + `adjusted_manager_context_model.csv`
- `desire_summary.csv`
- `semantic_ticket_map.html` — interactive UMAP map
- `option2_analysis_workbook.xlsx` — Excel summary
- `executive_findings.md` — Markdown summary

---

## Stage 2 — `bertopic_from_run.py`

**Purpose.** Validate Stage 1's clusters with a different technique. If two methods agree on the topics, the topics are real.

**Inputs.** `enriched_tickets.csv`, `embeddings_local.npy` from Stage 1.

**What it does.** Runs BERTopic, which combines:

- the same multilingual embeddings,
- UMAP for dimensionality reduction,
- HDBSCAN for clustering,
- **c-TF-IDF** for naming each topic with its most distinctive words.

The result is 53 named topics like `0_account_restore_deleted_number`, `1_diamonds_buy_buy diamonds_money`, `8_svip_svip points_buy svip_level`. Topic `-1` is the catch-all "noise" bucket — 1,381 tickets that did not fit any other topic. Stage 4 splits that bucket.

**Key outputs.**
- `bertopic_topics.csv`
- `bertopic_assignments.csv`
- `bertopic_barchart.html`

---

## Stage 3 — `insight_layer.py`

**Purpose.** Turn the topics into business decisions.

**What it does.**

1. **Opportunity backlog.** Each topic gets a score combining size, unresolved share, recent lift (is it growing?), money/trust risk, and average context depth. The top items are concrete actions: "automate self-serve", "create escalation playbook", "split this messy bucket", etc.
2. **Emerging topic detection.** For each topic, compares last-30-days volume to the prior baseline. Topics with high z-scores are emerging issues that the team may not have noticed yet.
3. **Repeat-user personas.** Users who file 3+ tickets are clustered into seven behavioural personas (creator/channel operator, commerce-dispute risk, repeat-ban appeal, account-recovery repeat, SVIP optimizer, multi-problem power user, generic repeat).
4. **Evidence gaps.** For each topic and each manager, what evidence types are usually missing.
5. **Manager evidence coaching.** Per-manager checklist of "you are X% below benchmark on attaching screenshots/IDs/multiline notes."
6. **Context value model.** A logistic regression asking: "after controlling for everything else, does writing richer notes correlate with higher resolution?" The result is honest — context depth has a small positive but not statistically significant correlation with resolution. Rich notes are mainly valuable for understanding, escalation, and downstream classifiers, not for closing tickets faster.

**Key outputs.**
- `opportunity_backlog.csv`
- `emerging_topics.csv`
- `repeat_user_personas.csv`
- `manager_context_residuals.csv`
- `issue_evidence_gaps.csv`
- `manager_evidence_coaching.csv`
- `context_value_model.csv`
- `insight_layer_workbook.xlsx`

---

## Stage 4 — `split_outlier_bucket.py`

**Purpose.** BERTopic dumps everything it cannot confidently cluster into topic `-1`. With 1,381 tickets in there, that bucket is the largest "topic" in the dataset and hides real signal.

**What it does.** Re-embeds just the outlier tickets and forces them into 26 sub-themes (forcing means using KMeans rather than HDBSCAN, so no ticket is left as noise).

**Why it matters.** This surfaces small but important groups that BERTopic missed, like `outlier_13_voice_microphone_voice_room_room_can_t` (59 tickets about voice/room issues) and `outlier_11_points_want_didn_t_account_number` (104 tickets about points and account number disputes).

**Key outputs.**
- `outlier_subtopics.csv` — the 26 sub-themes
- `outlier_subtopic_assignments.csv`
- `outlier_subtopic_map.html`
- `refined_opportunity_backlog.csv` — the Stage 3 backlog re-ranked with the new sub-themes

---

## Stage 5 — `llm_extract_rich_tickets.py`

**Purpose.** Until now, every layer was statistical: we counted, embedded, and clustered. Stage 5 asks an LLM to actually *read* each ticket and extract a structured record.

**Why this is the most important stage.** Statistics tells you *what topics exist*. The LLM tells you *what the user actually wanted, what they were feeling, what was at stake, and what the platform could have done differently*. That is the difference between a topic dashboard and an intent dashboard.

**What it does.**

1. **Picks the highest-signal candidate tickets** up to `--limit`. Strategy `risk_balanced` favours tickets that are evidence-rich (so the model has something to work with) and high-risk (money, trust, abuse). The current run read **1,348**; the original laptop baseline read 250.
2. **Calls a local model via Ollama.** No API key, no paid inference, no data leaving the machine. The current run uses Mistral Small 3.2 24B (RunPod GPU); the original laptop baseline used Gemma 3:4B.
3. **Extracts a JSON record per ticket** with these fields:
    - `literal_request` — what the user said
    - `actual_user_want` — what they actually want
    - `job_to_be_done` — one of: recover_access, understand_punishment, protect_community, avoid_scam, fix_product_flow, prove_innocence, restore_visibility, buy_or_sell_diamonds, grow_channel, gain_status, other
    - `user_emotion` — anxious, angry, confused, desperate, hopeful, neutral, urgent
    - `urgency_level`, `trust_risk_level`, `money_risk_level`, `safety_policy_risk_level` — each on a 1-5 scale
    - `evidence_present`, `evidence_missing` — what the manager attached vs. what is still needed
    - `support_next_step` — what should happen next
    - `product_opportunity` — what platform change would prevent this ticket
    - `manager_note_quality` — assessment of the note itself
    - `entities` — extracted UIDs, room/group IDs, timestamps, ban reasons, money amounts, counterparties, URL count, user claim
4. **Validates each output.** Bad JSON or invalid enum values are flagged (`_quality_flag`), not silently kept.
5. **Falls back gracefully.** Has three backends in priority order:
    - `ollama` — local Ollama model (Mistral Small 3.2 is the new default)
    - `ollama_hybrid` — small local model + deterministic rules for hard fields
    - `rules` — pure regex/lookup, free, no model, weakest output
    - `openai` — paid, optional, never used in this run

**Local LLM model trade-offs:**
- `gemma3:270m` — too weak for ticket reasoning. Empty/template outputs.
- `gemma3:1b` — produces valid JSON but over-collapses jobs.
- `mistral-small3.2:24b` — **what the current run uses.** 1,348/1,348 valid (0 bad / 0 error) on RunPod GPU; strongest instruction-following and structured output.
- `gemma3:4b` — the original laptop baseline. 248/250 valid, 2 invalid-job outputs auto-flagged. Still owns the BERTopic/outlier layers.

**Key outputs.**
- `llm_extraction_candidates.csv` — the 250 chosen tickets
- `llm_extraction_schema.json` — human-readable extraction contract
- `llm_extraction_response_schema.json` — formal JSON Schema passed to Ollama structured-output mode
- `llm_extraction_prompt.md` — exact prompt sent to the model
- `ollama_<model>_extractions.csv` / `.jsonl` — structured per-ticket records
- `llm_extractions.csv` — alias to the latest extraction
- `local_llm_model_comparison.md` — side-by-side of the three models

---

## Stage 6 — `build_user_wants_taxonomy.py`

**Purpose.** Stage 5 gave us the structured records (1,348 on the current run). Stage 6 collapses them into a real taxonomy of *what users want*, using the LLM-extracted text rather than the original messy ticket text.

**What it does.**

1. For each extracted ticket, builds a `_want_text` by concatenating `actual_user_want | job_to_be_done | product_opportunity | literal_request`.
2. Embeds those `_want_text` strings with the same multilingual sentence-transformers model.
3. Clusters them. First tries HDBSCAN (lets tickets be unclustered). If too many tickets fall into the noise bucket, falls back to KMeans (forces every ticket into a cluster). On the current 1,348-ticket run this yields **20 wants**; the original 250-ticket run gave 17.
4. For each cluster, computes:
    - size and share
    - top jobs and emotions
    - average money/trust/urgency risk
    - 3 example tickets closest to the cluster centroid
    - 2 example next-step recommendations
5. Joins back to the enriched tickets so each assignment has manager, category, date, and original Question.
6. Writes a Markdown summary, a CSV taxonomy, a CSV per-ticket assignments table, and an Excel workbook with **want × emotion**, **want × money_risk**, and **want × manager** cross-tabs.

**Key outputs.**
- `user_wants_taxonomy.csv` — one row per discovered want (20 on the current run)
- `user_wants_assignments.csv` — one row per LLM-read ticket (1,348 on the current run)
- `user_wants_workbook.xlsx`
- `user_wants_findings.md`

---

## Stage 7 — `project_user_wants_full_corpus.py`

**Purpose.** Stage 6 gives a high-quality taxonomy from tickets the local LLM actually read. Stage 7 projects the rest of the cleaned corpus into that taxonomy without pretending every short row received a deep LLM read.

**What it does.**

1. Treats `user_wants_assignments.csv` as the LLM-confirmed set.
2. Embeds each confirmed `_want_text` and builds one centroid per discovered want.
3. Embeds every cleaned ticket from `enriched_tickets.csv`.
4. Assigns each ticket to the nearest discovered want with a confidence band.
5. Marks weak, ambiguous, or high-risk rows for a targeted follow-up LLM review queue.

**Key outputs.**
- `user_wants_all_assignments.csv` — every cleaned ticket mapped to a discovered want
- `user_wants_full_corpus_summary.csv` — estimated full-corpus size/share per want
- `user_wants_review_queue.csv` — smart shortlist for the next LLM pass
- `user_wants_full_corpus_workbook.xlsx`
- `user_wants_projection_metadata.json`

---

## How the stages depend on each other

```
data_2may.csv ──> Stage 1 ─┬─> Stage 2 ──> Stage 3 ──> Stage 4
                           │
                           └─> Stage 5 ──> Stage 6 ──> Stage 7
```

Stages 2-4 are about validation and decisions. Stages 5-7 are about meaning: deep LLM extraction, user-want taxonomy, and full-corpus projection. You can present either branch, but the most novel result is the Stage 6/7 combination.
