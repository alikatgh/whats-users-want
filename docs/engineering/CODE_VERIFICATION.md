# Code ↔ Docs Verification

**Verified:** 2026-05-29
**Method:** static read of each pipeline script against its engineering deep-dive
(`grep` for every documented formula/config/enum, then targeted reads of the
formula bodies). No code was executed; no `outputs/` were touched.
**Scope:** the 6 documented pipeline scripts + a census of undocumented scripts.

## Why this file exists

The engineering docs (`docs/engineering/01..09`) *describe* the code but nobody had
*checked* that the code still matches them. This file is that check, so future
sessions don't have to re-audit. **If `git log` shows no changes to a script
since the date above, trust this verdict instead of re-reading the script.**

---

## Top-line verdict

> **The documentation is substantively accurate.** Every load-bearing formula,
> config block, and enum was confirmed to match the code **verbatim**. **Zero
> code bugs were found.** All discrepancies are documentation-side: (1) line-number
> citations are uniformly stale because the code grew 2–4×, (2) two small
> doc-internal inconsistencies, (3) four scripts + one "Stage 7" are undocumented.

| Script | Doc | Verdict |
|---|---|---|
| `option2_pipeline.py` | `01-stage1-pipeline.md` | ✅ Accurate (line cites stale) |
| `bertopic_from_run.py` | `02-stage2-bertopic.md` | ✅ Accurate (line cites stale) |
| `insight_layer.py` | `03-stage3-insight.md` | ✅ Accurate (line cites stale) |
| `split_outlier_bucket.py` | `04-stage4-outlier-split.md` | ✅ Accurate (line cites stale) |
| `llm_extract_rich_tickets.py` | `05-stage5-llm.md` + `08-prompts-and-extraction.md` | ✅ Accurate (line cites stale) |
| `build_user_wants_taxonomy.py` | `06-stage6-taxonomy.md` | ✅ Accurate (one doc typo, line cites stale) |

---

## Verified claims (current, correct line numbers)

These line numbers are accurate as of 2026-05-29 and supersede the (stale)
citations inside the deep-dive docs.

### Stage 1 — `option2_pipeline.py` (2035 lines)
- `DESIRE_PATTERNS` (10 desires) — **L164**
- `EVIDENCE_LABELS` (10 flags) — **L181**
- `read_raw_csv` uses `dtype=str, keep_default_na=False` — **L378**
- CJK dup-prefix / `已解决` left alone — **L405**
- `context_depth_score` formula, weights `18/10/10/10/8/8/8/10/8/5/5`, first
  three capped at `quantile(0.95)` — **L772–784** ✅ exact
- `context_depth_band` `bins=[-1,15,35,60,101]`, labels `thin/basic/rich/forensic` — **L785–789** ✅ exact
- `model_text` URL masking — **L790**
- Adjusted manager OLS `context_depth_score ~ C(manager)+C(category)+C(question_kind)+C(role)+C(status_en)+C(month)`, `cov_type="HC3"` — **L935** ✅ exact
- Clustering: HDBSCAN `min_cluster_size=max(12,min(80,len//90))` — **L1378**;
  KMeans fallback `k=max(8,min(35,int(sqrt(len/2))))` — **L1386** ✅ exact
- CLI args (`--input`, `--output-dir`, `--embedding-backend`, `--embedding-model`) — **L2001+**

### Stage 2 — `bertopic_from_run.py` (262 lines)
- `CountVectorizer` (`min_df=3, max_df=0.85, ngram_range=(1,2)`) — **L149**
- `UMAP` (`n_neighbors=25, n_components=8, min_dist=0.0, metric=cosine, random_state=42`) — **L157**
- `HDBSCAN` (`min_cluster_size=min_topic_size, min_samples=max(5, mc//3)`) — **L165**
- `BERTopic(embedding_model=None, calculate_probabilities=False, low_memory=True)` — **L171–177** ✅ exact (the key "we provide our own embeddings" claim holds)
- `fit_transform(docs, embeddings)` — **L180**
- CLI `--min-topic-size` default `35` — **L256**

### Stage 3 — `insight_layer.py` (1419 lines)
- `RISK_DESIRES` (5 members) — **L75–81** ✅ exact
- `issue_id` fallback `bertopic_topic ?? cluster_id ?? -999` — **L253–260** ✅ exact
- `issue_action` thresholds (`0.35/0.20`, `1.8/10`, etc.) — **L397–403** ✅ exact
- `trust_money_flag = primary_desire ∈ RISK_DESIRES | has_money_terms | has_status_or_svip_terms` — **L535** ✅ exact
- `recent_lift = (p_recent+0.0005)/(p_baseline+0.0005)` — **L543**; z-denom with `1e-9` floor — **L545**
- `opportunity_score = sqrt(volume)*(1 + 2.2*unresolved + 1.2*min(max(lift-1,0),3) + 1.4*risk) + 8*rich_share + 0.06*avg_context` — **L552–557** ✅ exact (incl. the additive `+8` and `+0.06` terms)
- `emergence_score = sqrt(last_30).clip(≥0) * lift.clip(≤6) * (1+recent_unresolved)` — **L674–678** ✅ exact
- 7-persona cascade — `persona_for_user` **L682**, `build_repeat_user_personas` **L745**
- `context_value_model` OLS (LPM), coef×100 → probability points — formula **L1016**, scaling **L1027** ✅ exact

### Stage 4 — `split_outlier_bucket.py` (826 lines)
- `choose_k`: requested `max(3,min(requested,max(3,n//12)))`; auto `max(8,min(32,round(sqrt(n/2))))` — **L236–238** ✅ exact (both branches)
- Refuse split if `< 50` outlier rows — **L427**; `embedding_row` preserved — **L426**
- `MiniBatchKMeans(n_clusters=k, random_state=42, n_init=30, batch_size=512)` — **L434** ✅ exact
- Per-row confidence `1 - chosen_dist / max(distances.mean(axis=1), 1e-9)`, clipped `[0,1]` — **L437–438** ✅ exact. **`axis=1` is correct (per-row mean) — confirmed NOT a bug.**
- TF-IDF naming `max_features=7000` — **L441**; silhouette on sample — **L490**
- `create_map` UMAP `min_dist=0.08` — **L607**

### Stage 5 — `llm_extract_rich_tickets.py` (2098 lines)
- `JOB_VALUES` (13) — **L131–145** ✅ exact; `EMOTION_VALUES` (9) — **L146** ✅ exact; `EVIDENCE_VALUES` — **L147**; `NOTE_QUALITY_VALUES` — **L148**
- `JOB_ALIASES` (8 entries: `investigate_fraud→avoid_scam`, …) — **L149–158** ✅ exact
- `GENERIC_PHRASES` (17 entries) — **L293–311** ✅ exact; `SNAKE_TOKEN_RE` — **L292**
- OpenAI call `temperature=0, response_format={"type":"json_object"}` — **L640–641**
- Ollama call `localhost:11434/api/chat`, `format=schema or "json"`, `temperature=0`, `num_ctx=8192` — **L811–814** ✅ exact
- `is_concrete_phrase` — **L912**; `call_rules` risk-level formulas (e.g. `safety=clip(1+3·has_severe,1,5)`) — **L1349** (docstring **L1364**) ✅ exact
- Quality flags `invalid_job`/`invalid_emotion` — **L1270/1272**; `normalize_result_enums` — **L1282**

### Stage 6 — `build_user_wants_taxonomy.py` (1011 lines)
- `build_want_text` joins 4 fields, drops `nan/none/other` — **L178–218** ✅ exact
- Embedding model `paraphrase-multilingual-MiniLM-L12-v2` — **L266**
- HDBSCAN `min_samples=1, cluster_selection_epsilon=0.15` — **L398–402** ✅ exact
- Fallback trigger `outliers > 0.4*n OR clusters < 8` — **L407** ✅ exact
- KMeans `k=max(10,min(20,n//14))`, `n_init="auto", random_state=42` — **L415–416** ✅ exact
- `label_cluster(top_n=6)`, drops `STOPWORDS` or `len(token)<=3`, joins `_` — **L461/507/511**
- Centroid + cosine `centroid_similarity` — **L621–636**; crosstab sheets — **L771**

---

## Discrepancies found (all documentation-side, none are code bugs)

### D1 — Line-number citations are uniformly stale *(low severity, pervasive)*
The deep-dive docs cite line ranges from when the scripts were ~⅓ their current
size. Current vs cited:

| Script | Actual lines | Docs cite up to | Drift |
|---|---|---|---|
| `option2_pipeline.py` | 2035 | ~777 | ~2.6× |
| `llm_extract_rich_tickets.py` | 2098 | ~490 | ~4× |
| `insight_layer.py` | 1419 | ~411 | ~3.5× |
| `build_user_wants_taxonomy.py` | 1011 | ~235 | ~4× |
| `split_outlier_bucket.py` | 826 | ~291 | ~2.8× |
| `bertopic_from_run.py` | 262 | ~111 | ~2.4× |

The *substance* (formulas, function names, behavior) is still correct — only the
`:line` anchors are wrong. Use the "Verified claims" section above as the
corrected citation reference.

### D2 — `02-stage2-bertopic.md`: noise-bucket size stated two ways *(cosmetic)* — ✅ RESOLVED 2026-05-29
The Stage 2 doc says topic `-1` holds **1,381** tickets; the architecture doc and
Stage 4 doc say **1,331**. Both are right but unlabeled: `choose_k`'s docstring
(`split_outlier_bucket.py:208,228`) reconciles them — **1,381** is the raw
BERTopic `-1` count; **1,331** is after re-merging into the semantic frame (some
rows drop in the join). Docs should state which number is which.

### D3 — `06-stage6-taxonomy.md`: "four sheets" then lists five *(cosmetic)* — ✅ RESOLVED 2026-05-29
The doc says the workbook "has four sheets" but enumerates five: `taxonomy`,
`assignments`, `want_x_emotion`, `want_x_money_risk`, `want_x_manager`. Code
writes all five. Fix the word "four" → "five".

### D4 — Undocumented scripts *(medium severity — coverage gap)* — ✅ RESOLVED 2026-05-29
`scripts/` has 10 Python files; the engineering docs only deep-dive 6. Missing:

| Script | Lines | What it does | Doc status |
|---|---|---|---|
| `project_user_wants_full_corpus.py` | 540 | **"Stage 7"** — projects the 17 wants onto all 6,728 tickets via centroids + confidence bands + review queue | In `README`/`AGENTS.md` + architecture data-flow, but **no `engineering/` deep-dive** and not in the `engineering/README.md` layout table |
| `build_longitudinal_insights.py` | 496 | Month-by-month rising/fading wants, next-month growth, repeat-user sequences/archetypes | **Undocumented** |
| `label_user_wants.py` | 461 | Ollama writes a 3–7 word human title + 1-sentence summary per want cluster → `user_wants_human_labels.csv` | **Undocumented** |
| `export_static_readout.py` | 170 | Packages the static management readout (HTML/CSS/JS + CSVs) into a CDN-ready folder; runs no ML | Referenced via `run_static_readout.sh` in `AGENTS.md`, no deep-dive |

### D5 — No `docs/BUG_JOURNAL.md` *(process gap)* — ✅ RESOLVED 2026-05-29
The global operating rules require every project to keep `docs/BUG_JOURNAL.md`.
This repo has none. Bootstrap with `/init-bug-journal` or copy the template.

---

## What was NOT verified
- **Runtime behavior / output numbers.** Reported results (Albert residual
  `+8.89`, `context_value_model` coef `+0.153 p=0.241`, 248/250 valid extractions)
  were **not** reproduced — that needs `data_2may.csv` and a full run. This audit
  confirms the *code can produce* those quantities (the formulas/specs match), not
  that the specific numbers are current.
- **The 4 undocumented scripts' internal correctness** — only their purpose
  (module docstring) was read, not their formulas.
- **System-prompt wording drift** in Stage 5 — enums/configs/flags were verified
  exact; the long natural-language system prompts were spot-checked, not diffed
  word-for-word against `08-prompts-and-extraction.md`.

## Resolution log (2026-05-29, same session)
- **D2** — fixed: `02-stage2-bertopic.md` now explains 1,381 (raw `-1`) vs 1,331 (post-merge).
- **D3** — fixed: `06-stage6-taxonomy.md` "four sheets" → "five sheets".
- **D4** — fixed: added `06b-stage7-projection.md` (full Stage 7 deep-dive) and listed the
  3 utility scripts in `engineering/README.md`.
- **D5** — fixed: created `docs/BUG_JOURNAL.md`; journal pointer added to `AGENTS.md`.
- **D1** — *mitigated, not closed*: the corrected line numbers live in this file's
  "Verified claims" section, but the deep-dive docs (01–09) still carry their original
  stale `:line` cites. Rewriting them in place is a larger optional cleanup.

## Re-run guard
Re-run this audit only if `git log --since=2026-05-29 -- scripts/` is non-empty.
