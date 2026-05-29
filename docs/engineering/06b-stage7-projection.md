# 06b — Stage 7: `project_user_wants_full_corpus.py`

[Source](../../scripts/project_user_wants_full_corpus.py).

The "smart rest" after the expensive local-LLM read. Stage 5 only extracted 250
rich tickets and Stage 6 clustered them into 17 wants. This stage **projects
those 17 wants onto all 6,728 cleaned tickets** using embedding similarity —
without sending every short ticket through the LLM. The output is an *auditable
census*, not a pretence that the model read everything.

The honesty design is the whole point. Every projected ticket is tagged with how
it got its want:

- `llm_confirmed` — actually read by the local model (the Stage 5 sample).
- `embedding_projection` — mapped to the learned taxonomy by centroid similarity.
- `low_confidence_projection` / `short_text_projection` / `rule_hint_only` —
  weak matches that are surfaced for review rather than overclaimed.

## What it consumes

- `<run_dir>/enriched_tickets.csv` — all cleaned tickets (required).
- `<run_dir>/user_wants_assignments.csv` — the 250 LLM-confirmed want assignments, used as ground truth (required).
- `<run_dir>/user_wants_taxonomy.csv` — the 17 wants, for labels/titles (required).
- `<run_dir>/user_wants_human_labels.csv` — optional human titles from `label_user_wants.py`, merged in if present.
- `<run_dir>/embeddings_local.npy` — optional Stage 1 cached embeddings (reused if shape aligns).

Reuses Stage 6's embedder via `from build_user_wants_taxonomy import embed_texts` (**L32**) so projection embeddings match the taxonomy embeddings.

## Pipeline

### 1. Embedding alignment — `_load_cached_ticket_embeddings` (**L142–164**)

Tries to reuse the Stage 1 cache rather than re-embed 6,728 tickets. Three cases:

- `embeddings_local.npy` row count == `len(enriched)` → use directly.
- count == number of valid `model_text` rows (`len ≥ 8`) → re-expand into a
  full-length matrix with zero rows for the filtered-out tickets, and return a
  `has_embedding` mask.
- otherwise → signal "embed live" (fall back to `embed_texts`).

All embeddings are L2-normalized (`_normalize_matrix`, **L83**) so the dot product is cosine.

### 2. Build one centroid per want

Two paths, preferring the cheaper cached one:

- **`_build_centroids_from_ticket_embeddings` (L167)** — join confirmed
  assignments to enriched rows, keep those with a cached embedding, and average
  each want's *ticket* embeddings into a centroid.
- **`_build_centroids_from_want_text` (L208)** — fallback: re-embed the
  confirmed `_want_text` strings (same construction as Stage 6) and average.

Each path also returns `centroid_meta` (`confirmed_rows`, `confirmed_avg_centroid_similarity`) per want.

### 3. Score and assign (**L347–355**)

```
scores      = ticket_embeddings @ centroids.T     # cosine, every ticket × every want
best_idx    = argmax(scores, axis=1)
best_scores = scores[i, best_idx]
margin      = best_score - second_best_score      # how decisive the top match is
```

### 4. Adaptive assignment threshold (**L370–376**)

The clever bit. The cutoff for "confident enough to project" is **calibrated
against the confirmed tickets' own scores**:

```
if --assignment-threshold given:   threshold = that value
elif confirmed tickets exist:      raw = quantile(confirmed_self_scores, 0.10)
                                   threshold = clip(raw - 0.03, 0.25, 0.55)
else:                              threshold = 0.25  (min_threshold)
```

So the bar is set just below where the *known-good* tickets land (10th percentile
minus a 0.03 slack), clamped to `[0.25, 0.55]`. If the LLM-confirmed tickets only
weakly match their own centroids, the projection threshold drops accordingly.

### 5. Per-ticket method + confidence band (**L379–422**)

`assignment_method` priority: `llm_confirmed` → (no embedding) `rule_hint_only`
→ (short text) `short_text_projection` else `rule_hint_only` → (below
threshold/margin) `low_confidence_projection` → else `embedding_projection`.

When a ticket has no embedding, it falls back to a rule hint:
`DESIRE_TO_JOB_HINTS` (**L45**) maps the Stage 1 `primary_desire` → a job → a want
via `_fallback_want_lookup` (**L244**); the default is the largest want.

`_confidence_band` (**L281**):
```
confirmed                                              → "confirmed"
score ≥ threshold+0.10 AND margin ≥ 2·margin_threshold → "high"
score ≥ threshold      AND margin ≥ margin_threshold   → "medium"
otherwise                                              → "low"
```

### 6. Review queue (**L297–311, L465–474**)

`_review_reason` flags a ticket for a targeted follow-up LLM pass when any of:
`low_similarity` (score < threshold), `ambiguous_match` (margin < margin_threshold),
`high_risk_signal` (`risk_signal_count ≥ 2`), `short_text` (< `min_text_chars`).

`risk_signal_count` (`_risk_signal_count`, **L271**) = sum of the boolean
`RISK_FLAG_COLUMNS` (money/status/ban-reason/user-claim/unresolved/screenshot) plus
`context_depth_score ≥ 24`.

The queue is ranked by `uncertainty_score` (**L466**):
```
uncertainty = max(threshold - confidence, 0)
            + max(margin_threshold - margin, 0)
            + 0.05 · risk_signal_count
```
and truncated to `--review-limit` (default 800).

## Output files (**L476–510**)

- `user_wants_all_assignments.csv` — every ticket → want, with method, confidence, margin, band, risk count, review flag, and joined context columns.
- `user_wants_full_corpus_summary.csv` — per-want estimated size/share, `llm_confirmed_tickets` vs `projected_tickets`, avg confidence, low-confidence count, review-queue count.
- `user_wants_review_queue.csv` — the top-`review_limit` uncertain/risky rows.
- `user_wants_full_corpus_workbook.xlsx` — sheets `full_corpus_summary`, `all_assignments`, `llm_review_queue`.
- `user_wants_projection_metadata.json` — thresholds used, embedding source, confirmed vs projected counts, timestamp.

## Command-line (**L514–526**)

```bash
python scripts/project_user_wants_full_corpus.py <run_dir> \
  [--max-chars 1600] [--min-text-chars 40] \
  [--assignment-threshold FLOAT] [--threshold-quantile 0.10] [--threshold-slack 0.03] \
  [--min-threshold 0.25] [--max-threshold 0.55] [--margin-threshold 0.03] \
  [--review-limit 800]
```

## Design notes

- **Confirmed vs projected are never blurred.** The summary reports both counts
  separately, and the metadata records `llm_confirmed_rows` vs `projected_rows`.
  This is the same uncertainty discipline as `docs/09-limitations.md` §1.
- **Cache reuse is best-effort.** If `embeddings_local.npy` doesn't align, it
  re-embeds live — correctness over speed.
- **Threshold is data-driven, not hand-set**, so a weaker taxonomy automatically
  produces a more cautious projection (lower bar → more rows land in the review
  queue rather than being silently mislabelled).
