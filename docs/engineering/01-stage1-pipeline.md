# 01 — Stage 1: `option2_pipeline.py`

The largest script. It reads `data_2may.csv`, produces `enriched_tickets.csv`, computes manager comparisons, embeds, clusters, exports tables, draws charts, and writes the initial `executive_findings.md`.

[Source](../../scripts/option2_pipeline.py).

## Module-level constants

### Regex patterns (lines 29-50)

| Constant | Pattern | Used by |
|---|---|---|
| `URL_RE` | `https?://\S+` | URL evidence flag, `model_text` masking |
| `IMAGE_RE` | URLs ending in `.jpg/.jpeg/.png/.webp/.gif` | Screenshot evidence flag |
| `TIMESTAMP_RE` | `2026-04-26 14:14:08` style | Timestamp evidence flag |
| `DATE_RE` | bare dates like `2026-04-26` | Date mention count |
| `ROOM_ID_RE` | `bg.xxx`, `sg_xxx`, `voice:xxx` etc. | Room/group ID evidence flag |
| `LONG_ID_RE` | `\b\d{12,18}\b` | UID/case ID evidence flag |
| `BAN_REASON_RE` | `ban\|banned\|insults\|violation\|...` | Ban-reason language flag |
| `USER_CLAIM_RE` | `i did nothing\|without reason\|wrongly\|...` | User-claim flag |
| `MONEY_RE` | `money\|withdraw\|diamonds\|recharge\|seller\|dealer\|...` | Money terms flag |
| `ACCOUNT_RE` | `account\|recover\|login\|password\|uid\|...` | Account-recover desire match |
| `STATUS_RE` | `svip\|level\|points\|badge\|...` | SVIP/status terms flag |
| `GROWTH_RE` | `channel\|group\|family\|host\|agency\|...` | Growth desire match |
| `REPORT_RE` | `report\|complaint\|scam\|fraud\|abuse\|...` | Abuse-protection desire match |
| `TECH_RE` | `bug\|error\|issue\|problem\|...` | Tech-fix desire match |
| `RULES_RE` | `how\|why\|policy\|rule\|...` | Understand-rules desire match |
| `URGENCY_RE` | `urgent\|asap\|please\|...` | `urgency_signal` count |

### `DESIRE_PATTERNS` (lines 52-63)

Maps each of 10 human desires to a regex. A ticket has `desire__<name> = True` if its question matches the pattern.

```
recover_access                  → ACCOUNT_RE
clear_name_or_get_fairness      → unban|ban|wrongly|appeal|...
earn_or_transact_money          → MONEY_RE
grow_audience_or_community      → GROWTH_RE
gain_status_or_privileges       → STATUS_RE
protect_from_abuse_or_scam      → REPORT_RE
fix_product_or_technical_flow   → TECH_RE
understand_rules_or_system_logic → RULES_RE
customize_identity_or_assets    → gift|prop|frame|avatar|...
play_or_entertainment           → game|play|durak|casino|...
```

### `EVIDENCE_LABELS` (lines 65-76)

The 10 boolean flags that feed `context_depth_score`:

```
has_url, has_image_url, has_timestamp, has_room_or_group_id,
has_long_uid_or_case_id, has_ban_reason_language, has_user_claim,
has_money_terms, has_status_or_svip_terms, has_multiline_note
```

## Functions

### `clean_text(value)` and `normalize_space(value)` (lines 90-99)

Defensive whitespace cleanup. `clean_text` keeps newlines (so `has_multiline_note` works); `normalize_space` collapses all whitespace to single spaces (used for matching and display).

### `first_existing(df, names)` (lines 102-111)

Returns the first column name from `names` that exists in the DataFrame, case-insensitive. Used to handle column variations across CSV exports (e.g. "Date" vs "date", or `分类` for Chinese "Category").

### `read_raw_csv(path)` (lines 114-120)

`pd.read_csv` with `dtype=str` and `keep_default_na=False`. Critical: this prevents pandas from coercing UID strings to floats and dropping zero-leading numbers. Then drops empty `Unnamed: N` columns that Excel exports often leave behind.

### `drop_noise_columns(df)` and `drop_summary_rows(df)`

Two cleaners that run between `read_raw_csv` and `canonicalize`. Both are on by default.

**`drop_noise_columns`** removes colleague-added Google-Sheets pivot columns:

- Any column whose name starts with `Role\n` or `SVIP\n` (cohort columns with inline dates and emoji like `Role\n📆: 2026-04-06`).
- The Russian `Статус` column when it is being used as a numeric pivot count rather than a real status (heuristic: ≥30% numeric values *or* ≥85% empty).

In the current dataset this drops 2 cohort columns and keeps `Статус` (which is mostly the meaningful Chinese status `已解决`).

**`drop_summary_rows`** removes rows that have **no Question text and no UID** — these are colleague-added empty placeholders or pivot rows like `,咨询信息Consulting info,0,,,`. In the current dataset this drops 26 of 6,728 rows.

Both can be disabled with `--keep-pivot-columns` / `--keep-summary-rows`. The metadata block records the dropped column list and the dropped-row count so it's auditable.

### `strip_cjk_dup_prefix(value)`

Used by `canonicalize` on every category value. Strips a leading run of Chinese characters when they are immediately followed by the same value in English, with optional `&` and whitespace separators. Examples:

```
'咨询信息Consulting info'              -> 'Consulting info'
'解封&封禁 Unblocking & Banning'        -> 'Unblocking & Banning'
'货币相关 Currency related'             -> 'Currency related'
'已解决'                                -> '已解决'           (unchanged, no Latin)
'Consulting info'                       -> 'Consulting info'  (unchanged)
```

Pure-Chinese values like `已解决` are left alone because the regex requires a Latin letter to anchor the strip.

### `canonicalize(df)` (lines 123-149)

Normalizes column names from the messy CSV into a clean schema. Resolves Chinese category/status columns. Computes:

- `date` (parsed `pd.to_datetime`, dayfirst=True)
- `month` (period like `2026-04`)
- `is_resolved` = status in `["Closed", "Done"]` OR Chinese status equals "已解决"
- `is_unresolved` = `~is_resolved`

### `featurize_tickets(df)` (lines 152-212)

The heart of Stage 1. Computes ~25 columns per ticket:

1. **Length features:** `char_count`, `word_count`, `line_count`.
2. **Evidence counts:** `url_count`, `image_url_count`, `timestamp_count`, `date_mention_count`, `room_or_group_id_count`, `long_uid_or_case_id_count`.
3. **Boolean flags** (the 10 in `EVIDENCE_LABELS` plus `has_screenshot_evidence`).
4. **Desire flags** (one per `DESIRE_PATTERNS` key): `desire__<name> = True/False`.
5. **`primary_desire`** = the name of the desire flag that is True with highest priority (idxmax-based). If no desire matches, `primary_desire = "unclear_or_needs_llm"`.
6. **`urgency_signal`** = count of urgency-pattern matches.
7. **`evidence_element_count`** = sum of the 10 boolean evidence flags.
8. **`context_depth_score`** — the weighted formula:

   ```
   context_depth_score =
        18 * min(char_count / char_p95, 1)
      + 10 * min(line_count / line_p95, 1)
      + 10 * min(url_count / url_p95, 1)
      + 10 * has_image_url
      + 8 * has_timestamp
      + 8 * has_room_or_group_id
      + 8 * has_long_uid_or_case_id
      + 10 * has_ban_reason_language
      + 8 * has_user_claim
      + 5 * has_money_terms
      + 5 * has_status_or_svip_terms
   ```

   The first three terms cap at the 95th percentile so a single 10-paragraph ticket can't dominate. The score has a soft maximum around 100.

9. **`context_depth_band`** = `pd.cut(score, bins=[-1, 15, 35, 60, 101], labels=["thin","basic","rich","forensic"])`.
10. **`model_text`** = the question with URLs replaced by `[URL]` placeholder so embeddings learn structure rather than memorizing specific links.

### `build_manager_summary(df)` (lines 215-237)

Per-manager aggregates. Most useful columns:
- `tickets`: count
- `unique_users`: distinct UIDs handled
- `avg_context_score`, `median_context_score`
- `forensic_share`, `rich_or_forensic_share`: fraction of tickets in those bands
- `image_evidence_share`, `url_share`, `timestamp_share`, `room_id_share`, `user_claim_share`, `ban_reason_share`
- `unresolved_share`

### `adjusted_manager_context(df)` (lines 240-271)

Statsmodels OLS regression:

```
context_depth_score ~ C(manager) + C(category) + C(question_kind)
                    + C(role) + C(status_en) + C(month)
```

`cov_type="HC3"` for heteroskedasticity-robust standard errors. The first manager alphabetically becomes the baseline (Albert in this dataset). For every other manager, we report the coefficient (delta vs baseline), p-value, and the model R².

This is what produces the "Albert is +8.89 above next manager after controls" finding.

### `top_examples(df, n=80)` (lines 274-292)

Top 80 tickets by `context_depth_score` with their key columns. Used for the "rich examples" Excel sheet and the high_context_examples.csv file.

### `desire_summary(df)` (lines 295-310)

Per-desire counts, share, unresolved share, avg context, and top managers. The "Top Human Desires" section of the report comes from this.

### `make_text_matrix(texts, max_features=6000)` (lines 313-327)

Build TF-IDF features:

- `min_df=3` (term must appear in at least 3 docs)
- `max_df=0.82` (drop terms in >82% of docs — catches boilerplate)
- `ngram_range=(1,2)` (unigrams + bigrams)
- `strip_accents="unicode"`
- `stop_words="english"` (this is a known limitation for Russian/Chinese — see Stage 2 for a better-tuned vocabulary inside BERTopic)
- `token_pattern=r"(?u)\b[\w][\w'-]{2,}\b"` (≥3 char tokens)

### `embed_texts(texts, backend, out_dir, model_name)` (lines 330-360)

Three backends:

- `tfidf` — uses `make_text_matrix`. No external dependencies.
- `local` — uses `sentence_transformers.SentenceTransformer(model_name)`. Default model: `paraphrase-multilingual-MiniLM-L12-v2`. **Caches** to `out_dir / embeddings_local.npy` and reloads on subsequent calls.
- `openai` — uses the `OpenAI` Python client and `text-embedding-3-small` (or whatever `--embedding-model` says). Requires `OPENAI_API_KEY`.

All embeddings are saved as `.npy` arrays of dtype float32, normalized for cosine.

### `cluster_texts(df, out_dir, backend, model_name)` (lines 363-490)

The full clustering pipeline:

1. Filter to `model_text` length >= 8.
2. Embed via `embed_texts`.
3. If TF-IDF, run TruncatedSVD(n_components ≤ 80) then L2-normalize.
4. Try UMAP twice:
   - 2-component for visualization (`x`, `y`).
   - 10-component for clustering (`n_components=10, min_dist=0.0`).
5. Try HDBSCAN with adaptive `min_cluster_size = max(12, min(80, len // 90))`. If it fails, fall back to MiniBatchKMeans with `k = max(8, min(35, sqrt(n/2)))`.
6. Build cluster labels by computing **mean TF-IDF per cluster** and taking the top 12 distinctive terms. (For embedding-based clusters, we still build a TF-IDF over the same texts to get human-readable terms — this is c-TF-IDF in spirit before BERTopic does it formally in Stage 2.)
7. Build per-cluster summary: tickets, share, avg_context, unresolved_share, top_terms, top_desires, top_categories, top_managers, three example texts.
8. Write `semantic_ticket_map.html` via plotly.express.scatter on the 2-component UMAP coords.

Returns three DataFrames: `assignments`, `cluster_summary`, `backend_info`.

### `build_network(df, out_dir)` (lines 493-527)

Builds a co-occurrence graph between desires and categories using `networkx`. Each ticket contributes one node per active desire plus one `category::<X>` node, and an edge between every pair (so a ticket with 3 active desires + 1 category creates 6 edges).

Outputs:
- `desire_category_network_edges.csv` (only edges with weight ≥ 8)
- `network_nodes.csv` (returned to caller — has degree centrality and weighted degree)

### `create_charts(df, manager_summary, out_dir)` (lines 530-569)

Three matplotlib/seaborn PNGs:
- `manager_context_depth.png` — barplot ordered by avg_context_score
- `desire_trends.png` — line plot of monthly ticket counts per top-8 desire
- `context_depth_vs_outcome.png` — boxplot of context_depth_score by band, hued by is_unresolved

### `write_markdown_report(...)` (lines 572-649)

Composes the initial `executive_findings.md` with sections:

- header (timestamp, ticket count, unique users, date range, resolved %, rich/forensic %, NLP backend used)
- "What This Pipeline Measures" (boilerplate paragraph)
- "Strongest Context Signal" (top manager by avg context)
- "Top Human Desires" (top 8)
- "Largest Semantic Clusters" (top 10 clusters by ticket count + the noise bucket)
- "Adjusted Manager Context Model" (top 8 managers by coefficient)
- "Output Files" (list of CSVs)

### `export_excel(out_dir, tables)` (lines 652-657)

Writes one `option2_analysis_workbook.xlsx` with one sheet per table. Sheet names are sanitized to ≤31 chars per Excel's limit.

### `export_analytical_store(out_dir, tables)` (lines 660-697)

For each table:
- Write `parquet/<name>.parquet`.
- Register as a DuckDB table named `<safe_name>` in `analysis.duckdb`.

Also creates two convenience views:
- `manager_context_rank` (sorted by avg_context)
- `high_risk_user_needs` (desires with unresolved ≥ 20% or avg_context ≥ 24)

### `run(args)` (lines 700-759)

The top-level orchestrator. Builds the timestamped output directory, runs every other function in order, persists everything, and prints run metadata as JSON.

## Command-line arguments (lines 762-777)

```
--input             default: data_2may.csv
--output-dir        default: outputs
--embedding-backend choices: [tfidf, local, openai]; default: tfidf
--embedding-model   default: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

## Why this design

- **Single script for Stage 1** rather than a notebook because every output is reproducible and consumable by downstream stages without manual steps.
- **Soft-fail on optional libraries** so a partial environment still produces basic outputs.
- **Cap `char_count`, `line_count`, `url_count` at p95** in `context_depth_score` because a single 10-page ticket otherwise dominates the score distribution and ruins manager comparisons.
- **`primary_desire` from a fixed taxonomy** rather than discovered from data because Stage 1 needs to be deterministic for downstream regressions; discovered topics happen in Stage 2 and beyond.
- **`model_text` masks URLs** so the embedding step learns "URL is present" rather than memorizing specific CDN paths.
