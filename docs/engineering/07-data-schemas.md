# 07 — Data Schemas

Every output file's columns. When someone asks "what's in this column?", this is the answer.

---

## `enriched_tickets.csv`

The single source of truth. 6,728 rows × ~60 columns.

### From the raw CSV

| Column | Type | Notes |
|---|---|---|
| `source_row` | str | Original row index (preserves CSV ordering). |
| `date_raw` | str | Original Date string. |
| `date` | datetime | Parsed; nulls allowed for malformed rows. |
| `month` | str | Period like `2026-04`. Empty if date is null. |
| `manager` | str | Manager name. "Unknown" if missing. |
| `role` | str | Manager role. |
| `role_secondary` | str | Role.1 column from the CSV (when present). |
| `uid` | str | User ID, kept as string to preserve leading zeros. |
| `question_kind` | str | Manager-assigned question kind. |
| `question` | str | Full ticket text including newlines. |
| `question_flat` | str | Whitespace-collapsed version for matching/display. |
| `delegate_to` | str | "Deligate to" or "Delegate to" column from CSV. |
| `status_en` | str | English status (Open / Done / Closed / etc.). |
| `category` | str | Manager-assigned category. |
| `status_cn` | str | Chinese status (when present). |
| `svip_level` | str | SVIP level if column exists. |
| `is_resolved` | bool | True if status_en ∈ {Closed, Done} or status_cn == "已解决". |
| `is_unresolved` | bool | ~is_resolved. |

### Length features

| Column | Type | Description |
|---|---|---|
| `char_count` | int | Length of `question`. |
| `word_count` | int | `\b\w+\b` matches in `question_flat`. |
| `line_count` | int | Number of non-empty lines in `question`. |

### Evidence counts

| Column | Type | Description |
|---|---|---|
| `url_count` | int | URLs found. |
| `image_url_count` | int | Image URLs found. |
| `timestamp_count` | int | Timestamp matches found. |
| `date_mention_count` | int | Loose date matches. |
| `room_or_group_id_count` | int | Room/group ID matches. |
| `long_uid_or_case_id_count` | int | 12-18 digit numbers. |

### Evidence flags (boolean)

| Column | True when... |
|---|---|
| `has_url` | `url_count > 0` |
| `has_image_url` | `image_url_count > 0` |
| `has_timestamp` | `timestamp_count > 0` |
| `has_room_or_group_id` | `room_or_group_id_count > 0` |
| `has_long_uid_or_case_id` | `long_uid_or_case_id_count > 0` |
| `has_ban_reason_language` | matches `BAN_REASON_RE` |
| `has_user_claim` | matches `USER_CLAIM_RE` |
| `has_money_terms` | matches `MONEY_RE` |
| `has_status_or_svip_terms` | matches `STATUS_RE` |
| `has_multiline_note` | `line_count >= 3` |
| `has_screenshot_evidence` | `has_image_url` OR text mentions "screen"/"screenshot" |

### Desire flags (boolean)

One per pattern: `desire__recover_access`, `desire__clear_name_or_get_fairness`, `desire__earn_or_transact_money`, `desire__grow_audience_or_community`, `desire__gain_status_or_privileges`, `desire__protect_from_abuse_or_scam`, `desire__fix_product_or_technical_flow`, `desire__understand_rules_or_system_logic`, `desire__customize_identity_or_assets`, `desire__play_or_entertainment`.

| Column | Type | Description |
|---|---|---|
| `desire_count` | int | Number of desire flags True. |
| `primary_desire` | str | Name of first matching desire (idxmax priority). `unclear_or_needs_llm` if no match. |
| `urgency_signal` | int | Count of urgency-pattern matches. |
| `evidence_element_count` | int | Sum of the 10 boolean evidence flags. |

### Context score and band

| Column | Type | Description |
|---|---|---|
| `context_depth_score` | float | The weighted context score (formula in [09-formulas](09-formulas-cheatsheet.md)). |
| `context_depth_band` | str | One of `thin` (≤15), `basic` (15-35), `rich` (35-60), `forensic` (>60). |
| `model_text` | str | Question with URLs replaced by `[URL]`. Input to embeddings. |

### Cluster fields (added by `cluster_texts`)

| Column | Type | Description |
|---|---|---|
| `cluster_id` | int | Stage 1 cluster id. -1 = HDBSCAN noise. |
| `cluster_probability` | float | HDBSCAN soft-membership; 1.0 for KMeans fallback. |
| `x`, `y` | float | UMAP 2D coordinates. |
| `nlp_backend` | str | Which embedding backend was used. |

---

## `manager_context_quality.csv`

Per-manager rollup. Sorted by `(avg_context_score desc, tickets desc)`.

| Column | Type | Description |
|---|---|---|
| `manager` | str | |
| `tickets` | int | |
| `unique_users` | int | |
| `avg_context_score` | float | mean(`context_depth_score`) |
| `median_context_score` | float | median |
| `forensic_share` | float | fraction in `forensic` band |
| `rich_or_forensic_share` | float | fraction in `rich` ∪ `forensic` |
| `avg_char_count` | float | |
| `avg_line_count` | float | |
| `url_share` | float | mean(`has_url`) |
| `image_evidence_share` | float | mean(`has_image_url`) |
| `timestamp_share` | float | |
| `room_id_share` | float | |
| `user_claim_share` | float | |
| `ban_reason_share` | float | |
| `unresolved_share` | float | |

---

## `adjusted_manager_context_model.csv`

OLS coefficients for `context_depth_score ~ C(manager) + C(category) + ...`.

| Column | Description |
|---|---|
| `manager` | |
| `adjusted_context_delta_vs_baseline` | OLS coefficient for this manager dummy. |
| `baseline_manager` | The reference manager (alphabetically first; Albert here). |
| `p_value` | HC3-robust p-value. NaN for the baseline. |
| `model_r2` | R² of the full model. |
| `interpretation` | Boilerplate explanatory string. |

---

## `desire_summary.csv`

| Column | Description |
|---|---|
| `desire` | Name of desire (one of 10). |
| `tickets` | Count where `desire__<name> == True`. |
| `share` | tickets / total. |
| `unresolved_share` | unresolved count / tickets. |
| `avg_context_score` | mean within desire. |
| `top_managers` | Comma-joined top 3 managers handling this desire. |

---

## `semantic_clusters.csv` (Stage 1)

| Column | Description |
|---|---|
| `cluster_id` | int. -1 is noise. |
| `tickets` | size. |
| `share` | tickets / total. |
| `avg_context_score` | mean. |
| `unresolved_share` | mean. |
| `top_terms` | Comma-joined top 10 TF-IDF terms. |
| `top_desires` | Comma-joined top 4 primary_desires. |
| `top_categories` | Comma-joined top 4 categories. |
| `top_managers` | Comma-joined top 4 managers. |
| `example_1`, `example_2`, `example_3` | Compact example texts. |
| `nlp_backend` | "local:sentence-transformers/..." etc. |

---

## `semantic_cluster_assignments.csv` (Stage 1)

| Column | Description |
|---|---|
| `source_row` | Joins back to enriched_tickets. |
| `model_text` | The text that was embedded. |
| `manager`, `category`, `question_kind`, `primary_desire` | Cached metadata. |
| `context_depth_score`, `is_unresolved` | Cached metadata. |
| `cluster_id` | int. |
| `cluster_probability` | float. |
| `x`, `y` | UMAP 2D coords. |
| `nlp_backend` | str. |

---

## `bertopic_topics.csv` (Stage 2)

| Column | Description |
|---|---|
| `Topic` | int. -1 is noise. |
| `Count` | tickets in topic. |
| `Name` | Auto-generated like `1_diamonds_buy_buy diamonds_money` (top 4 c-TF-IDF terms). |
| `Representation` | List of top 10 c-TF-IDF terms. |

---

## `bertopic_assignments.csv` (Stage 2)

Same as Stage 1 assignments + columns `bertopic_topic, Name, Representation, Count`.

---

## `opportunity_backlog.csv` (Stage 3)

| Column | Description |
|---|---|
| `issue_id` | str (BERTopic topic id, or cluster_id, or "outlier_<n>" after Stage 4). |
| `issue_label` | Human-readable label. |
| `tickets` | int. |
| `unique_users` | int. |
| `repeat_user_share` | fraction of tickets from users with ≥2 tickets. |
| `unresolved_share` | float. |
| `avg_context_score` | float. |
| `rich_or_forensic_share` | float. |
| `urgency_avg` | float (mean of urgency_signal). |
| `trust_money_risk` | float (fraction with risk_desire ∪ money ∪ status flags). |
| `recent_tickets` | int (last 30 days). |
| `baseline_tickets` | int (days 30-120 prior). |
| `recent_lift` | float. |
| `trend_z` | float (two-proportion z). |
| `top_desires`, `top_categories`, `top_managers` | comma-joined. |
| `example_1`, `example_2`, `example_3` | compact ticket texts. |
| `opportunity_score` | float (formula in [09-formulas](09-formulas-cheatsheet.md)). |
| `recommended_action` | Rule-derived sentence (see Stage 3 doc). |

---

## `emerging_topics.csv` (Stage 3)

| Column | Description |
|---|---|
| `issue_id`, `issue_label` | |
| `total_tickets` | size of topic. |
| `last_30_tickets` / `last_60_tickets` / `last_90_tickets` | window counts. |
| `last_30_share_of_issue` / etc. | window count / total. |
| `recent_vs_prior_lift` | (last 30 days share) / (180-day baseline share). |
| `recent_vs_prior_z` | two-proportion z. |
| `recent_unresolved_share` | unresolved % in the last 30 days. |
| `top_desires` | comma-joined. |
| `emergence_score` | float. |

---

## `repeat_user_personas.csv` (Stage 3)

One row per UID with ≥2 tickets.

| Column | Description |
|---|---|
| `uid` | |
| `persona` | One of seven labels (see Stage 3 doc). |
| `tickets` | int. |
| `active_days_span` | int days from first to last ticket. |
| `first_date`, `last_date` | dates. |
| `unresolved_share` | float. |
| `avg_context_score` | float. |
| `managers_seen` | top 5 managers. |
| `top_desires`, `top_issues` | top 5 each. |
| `high_context_example_1`, `_2` | text. |

---

## `manager_context_residuals.csv` (Stage 3)

| Column | Description |
|---|---|
| `manager` | |
| `tickets` | |
| `avg_raw_context` | mean context_depth_score. |
| `avg_expected_context` | mean of `(category, question_kind)` group means. |
| `avg_residual_vs_ticket_mix` | raw - expected. |
| `rich_or_forensic_share` | |

---

## `issue_evidence_gaps.csv` (Stage 3)

For issues with ≥20 tickets.

| Column | Description |
|---|---|
| `issue_label` | |
| `tickets` | |
| `avg_context_score` | |
| `unresolved_share` | |
| `required_evidence` | comma-joined list of evidence columns expected. |
| `largest_missing_evidence` | top 4 evidence types missing, formatted `"flag:XX%"`. |
| `evidence_gap_score` | mean missing-share across all required types. |

---

## `context_value_model.csv` (Stage 3)

OLS on `resolved_int`.

| Column | Description |
|---|---|
| `term` | one of `context_depth_score`, `evidence_element_count`, `urgency_signal`. |
| `coef_probability_points` | coefficient × 100. |
| `p_value` | HC3-robust. |
| `conf_low_pp`, `conf_high_pp` | 95% CI in probability points. |
| `model_r2` | overall R². |
| `interpretation` | boilerplate string. |

---

## `manager_evidence_coaching.csv` (Stage 3)

| Column | Description |
|---|---|
| `manager` | |
| `benchmark_manager` | typically Albert. |
| `tickets` | |
| `avg_context_score` | |
| `rich_or_forensic_share` | |
| `top_evidence_gaps_vs_benchmark` | up to 4 human-language items separated by ;. |
| `<flag>_share` | rate per evidence flag. |

---

## `outlier_subtopics.csv` (Stage 4)

| Column | Description |
|---|---|
| `outlier_subtopic_id` | int 0..k-1. |
| `outlier_subtopic_label` | `outlier_<id>_<terms>`. |
| `tickets` | int. |
| `share_of_outlier` | fraction of the original noise bucket. |
| `avg_confidence` | mean KMeans confidence. |
| `avg_context_score` | float. |
| `rich_or_forensic_share` | float. |
| `unresolved_share` | float. |
| `top_terms` | comma-joined top 12. |
| `top_desires`, `top_categories`, `top_managers` | top 5 each. |
| `example_1`..`example_4` | compact texts. |

---

## `outlier_subtopic_assignments.csv` (Stage 4)

Subset of `semantic_cluster_assignments.csv` + `bertopic_topic`, plus:

| Column | Description |
|---|---|
| `embedding_row` | Index into the global embeddings array. |
| `outlier_subtopic_id` | int. |
| `outlier_subtopic_confidence` | 0-1. |
| `outlier_subtopic_terms` | comma-joined top 10. |
| `outlier_subtopic_label` | `outlier_<id>_<terms>`. |

---

## `outlier_split_metrics.csv` (Stage 4)

| Metric | Description |
|---|---|
| `silhouette_cosine_sample` | silhouette score on a 1,200-row cosine sample. |
| `outlier_topic` | which BERTopic topic was split (always -1). |
| `outlier_docs` | number of tickets split. |
| `subtopics` | k chosen. |

---

## `refined_opportunity_backlog.csv` (Stage 4)

Same schema as `opportunity_backlog.csv`, but rows where `issue_id == "-1"` have been replaced with one row per outlier subtopic.

---

## `llm_extraction_candidates.csv` (Stage 5)

| Column | Description |
|---|---|
| `source_row` | str. |
| `date_raw`, `manager`, `uid`, `category`, `question_kind`, `status_en`, `primary_desire`, `issue_label` | metadata. |
| `context_depth_score`, `context_depth_band` | |
| `char_count`, `url_count`, `image_url_count`, `timestamp_count`, `room_or_group_id_count` | |
| `llm_input_text` | The compacted ticket sent to the LLM. |

---

## `<backend>_<model>_extractions.csv` (Stage 5)

Flattened from JSONL via `pd.json_normalize`. Nested `entities.*` become dotted columns.

| Column | Description |
|---|---|
| `source_row` | str (must match input). |
| `literal_request` | model-extracted. |
| `actual_user_want` | |
| `job_to_be_done` | one of `JOB_VALUES`. |
| `user_emotion` | one of `EMOTION_VALUES`. |
| `urgency_level`, `trust_risk_level`, `money_risk_level`, `safety_policy_risk_level` | int 1-5. |
| `evidence_present` | list of `EVIDENCE_VALUES`. |
| `evidence_missing` | list of free strings. |
| `entities.uids` | list. |
| `entities.room_or_group_ids` | list. |
| `entities.timestamps` | list. |
| `entities.ban_reasons` | list. |
| `entities.money_or_diamond_amounts` | list. |
| `entities.counterparties` | list. |
| `entities.url_count` | int. |
| `entities.user_claim` | str (free text). |
| `support_next_step` | model-extracted. |
| `product_opportunity` | model-extracted. |
| `manager_note_quality` | one of `NOTE_QUALITY_VALUES`. |
| `needs_human_review` | bool. |
| `confidence` | 0-1. |
| `_status` | "ok" / "bad_output" / "error". |
| `_quality_flag` | only present if `_status == "bad_output"`. One of source_row_schema_echo, source_row_mismatch, empty_required_fields, schema_echo, invalid_job, invalid_emotion, too_vague. |
| `_backend` | str. |
| `_model` | str. |
| `_normalized_job_from`, `_normalized_emotion_from` | original value when an alias was applied. |

---

## `user_wants_taxonomy.csv` (Stage 6)

| Column | Description |
|---|---|
| `want_id` | int. -1 only when HDBSCAN was kept as outlier path. |
| `want_label` | snake_case derived from top tokens. |
| `size` | int. |
| `share` | size / total. |
| `top_jobs` | "job:count, ..." top 3. |
| `top_emotions` | "emotion:count, ..." top 3. |
| `avg_money_risk`, `avg_trust_risk`, `avg_urgency` | mean 1-5 risk levels. |
| `high_money_risk_share`, `high_trust_risk_share` | fraction with risk ≥ 4. |
| `example_1`, `example_2`, `example_3` | _want_text near the centroid. |
| `next_step_1`, `next_step_2` | model-suggested next steps. |

---

## `user_wants_assignments.csv` (Stage 6)

| Column | Description |
|---|---|
| `source_row` | str. |
| `want_id`, `want_label` | from clustering. |
| `centroid_similarity` | 0-1. |
| `_want_text` | the joined string fed to the embedder. |
| `job_to_be_done`, `user_emotion`, `urgency_level`, `trust_risk_level`, `money_risk_level` | from extraction. |
| `product_opportunity`, `support_next_step` | from extraction. |
| `Manager`, `Question`, `Status`, `Category`, `Date` | optionally joined from `enriched_tickets.csv`. |
