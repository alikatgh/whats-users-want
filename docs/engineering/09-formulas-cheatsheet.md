# 09 — Formulas Cheatsheet

Every numeric score in the project, in one place. If asked "how exactly is X computed", point here.

---

## Stage 1

### `context_depth_score`

```
context_depth_score =
     18 * min(char_count / char_p95, 1)
   + 10 * min(line_count / line_p95, 1)
   + 10 * min(url_count / url_p95, 1)
   + 10 * has_image_url
   +  8 * has_timestamp
   +  8 * has_room_or_group_id
   +  8 * has_long_uid_or_case_id
   + 10 * has_ban_reason_language
   +  8 * has_user_claim
   +  5 * has_money_terms
   +  5 * has_status_or_svip_terms
```

- `char_p95`, `line_p95`, `url_p95` are the 95th percentiles across all tickets, computed once at runtime.
- The first three terms are capped at 1, so a single 10-page ticket cannot dominate.
- Theoretical max ≈ 100 (18 + 10 + 10 + 10 + 8 + 8 + 8 + 10 + 8 + 5 + 5 = 100).
- Boolean flags contribute 0 or their full weight, never partial.

### `context_depth_band`

```
band = pd.cut(score, bins=[-1, 15, 35, 60, 101],
              labels=["thin", "basic", "rich", "forensic"])
```

| Band | Score range |
|---|---|
| `thin` | -1 to 15 |
| `basic` | 15 to 35 |
| `rich` | 35 to 60 |
| `forensic` | 60+ |

### `evidence_element_count`

Plain sum of the 10 boolean evidence flags. Range 0-10.

### `urgency_signal`

Count of regex matches of `URGENCY_RE = "urgent|asap|please|plz|help|immediately|now|very|again|many times|still|cannot|can't|failed"` in the ticket text. Unbounded but typically 0-10.

### `desire_count`

Sum of the 10 boolean `desire__*` flags. Range 0-10.

### `is_resolved`

```
is_resolved = status_en in {"Closed", "Done"} OR status_cn == "已解决"
is_unresolved = NOT is_resolved
```

### Adjusted manager context delta

```
context_depth_score ~ C(manager) + C(category) + C(question_kind)
                    + C(role) + C(status_en) + C(month)

[OLS, HC3-robust SEs]
```

Reported per manager:
- `delta_vs_baseline` = OLS coefficient
- `p_value` = HC3 p-value (NaN for the baseline manager)
- `model_r2` = R² of the full model

Baseline = first manager alphabetically (Albert in this dataset).

---

## Stage 3

### `recent_lift` (per topic)

```
recent_lift = (p_recent + 0.0005) / (p_baseline + 0.0005)
```

where:

```
recent window   = max_date - 30d to max_date
baseline window = max_date - 120d to max_date - 30d
n_recent   = total tickets in recent window
n_baseline = total tickets in baseline window
p_recent   = topic_recent_tickets / n_recent
p_baseline = topic_baseline_tickets / n_baseline
```

The `+ 0.0005` smoothing prevents division by zero and tames lift for tiny topics.

### `trend_z` (per topic, two-proportion z-test)

```
p_pool = (recent + baseline) / (n_recent + n_baseline)
denom = sqrt(p_pool * (1 - p_pool) * (1/n_recent + 1/n_baseline))
trend_z = (p_recent - p_baseline) / denom
```

### `opportunity_score`

```
opportunity_score =
    sqrt(volume) * (
        1
      + 2.2 * unresolved_share
      + 1.2 * min(max(recent_lift - 1, 0), 3)
      + 1.4 * trust_money_risk
    )
    + 8 * rich_or_forensic_share
    + 0.06 * avg_context_score
```

- `volume` = number of tickets in the topic.
- `unresolved_share` = fraction unresolved.
- `recent_lift` capped between 0 (no lift) and 3 (3× lift).
- `trust_money_risk` = mean of `trust_money_flag` where `trust_money_flag = primary_desire ∈ RISK_DESIRES OR has_money_terms OR has_status_or_svip_terms`.
- `rich_or_forensic_share` = fraction in those bands.
- `avg_context_score` divided by ~17 via the 0.06 multiplier.

`RISK_DESIRES` = `{clear_name_or_get_fairness, earn_or_transact_money, protect_from_abuse_or_scam, gain_status_or_privileges, fix_product_or_technical_flow}`.

### `emergence_score`

```
emergence_score = sqrt(last_30_tickets) * min(recent_vs_prior_lift, 6) * (1 + recent_unresolved_share)
```

where `recent_vs_prior_lift` is the same lift formula but with the baseline window of 150 days (180 - 30).

### Context residual (manager) — non-parametric

```
expected_mix_context(category, question_kind) = mean(context_depth_score)
                                                  for that (category, question_kind) cell
context_residual_vs_mix = context_depth_score - expected_mix_context

avg_residual_vs_ticket_mix per manager = mean over their tickets
```

### Evidence gap score (per issue)

For each required evidence type, `missing_share = 1 - mean(flag)`. Then:

```
evidence_gap_score = mean(missing_share over all required evidence types)
```

### Context value model

OLS:

```
resolved_int ~ context_depth_score + evidence_element_count + urgency_signal
              + C(category) + C(question_kind) + C(role) + C(month) + C(primary_desire)
```

Reported coefficients converted to "probability points per unit" by multiplying by 100 (since `resolved_int` is 0/1, the linear-probability-model coefficient is in probability units already).

### Evidence coaching gap

```
gap = benchmark_rate(flag) - manager_rate(flag)   # only kept if gap > 0.03
```

Top 4 gaps per manager are surfaced as "you are 30% below benchmark on attaching screenshots".

---

## Stage 4

### k for outlier KMeans

```
if --n-subtopics is provided:
    k = max(3, min(requested, max(3, n_docs // 12)))
else:
    k = max(8, min(32, round(sqrt(n_docs / 2))))
```

### Per-row confidence

```
distances = km.transform(X)  # shape (n_docs, k)
chosen_dist = distances[i, label_i]
confidence_i = clip(1 - chosen_dist / mean(distances_i), 0, 1)
```

Higher = more central.

### Silhouette (cluster quality metric)

`sklearn.metrics.silhouette_score(X_sample, labels_sample, metric="cosine")` on a 1,200-row sample. Range [-1, 1]; >0.1 is acceptable for short-text clustering, >0.2 is good.

---

## Stage 5

### Risk levels in `call_rules`

```
urgency_level = clip(round(1 + len(URGENT_matches)/2 + has_claim + has_scam), 1, 5)
trust_risk    = clip(round(1 + 2 * has_ban + 2 * has_scam + has_status), 1, 5)
money_risk    = clip(round(1 + 3 * has_money + has_scam), 1, 5)
safety_risk   = clip(round(1 + 3 * has_severe_terms), 1, 5)
```

`has_severe_terms` = matches regex `(pornographic|insult|abuse|scam|fraud|violence|threat)`.

### Note quality from context_depth_score

```
forensic if score >= 60
rich     if 35 <= score < 60
adequate otherwise
```

### `needs_human_review`

```
needs_human_review = trust_risk >= 4 OR money_risk >= 4 OR safety_risk >= 4
```

(In rules backend; LLM backends emit their own boolean.)

---

## Stage 6

### `_want_text`

```
_want_text = " | ".join([actual_user_want, job_to_be_done, product_opportunity, literal_request])
```

with empty/`nan`/`other` values dropped.

### Centroid similarity

```
centroid_k = mean(embeddings where label == k)
similarity_i = dot(embedding_i, centroid_k_i) / (norm(embedding_i) * norm(centroid_k_i))
```

Range [-1, 1]; for normalized embeddings effectively [0, 1].

### KMeans fallback k

```
n_clusters = max(10, min(20, len(embeddings) // 14))
```

### HDBSCAN fallback trigger

```
if outlier_count > 0.4 * n  OR  num_clusters < 8:
    fall back to KMeans
```

---

## Quick reference card

| Score | Where | Range | High = |
|---|---|---|---|
| `context_depth_score` | Stage 1 | 0-100 | rich evidence note |
| `evidence_element_count` | Stage 1 | 0-10 | many evidence types present |
| `urgency_signal` | Stage 1 | 0+ | many urgency words |
| `recent_lift` | Stage 3 | ≥0 | recent volume up vs baseline |
| `trend_z` | Stage 3 | -∞ to +∞ | statistically significant rise |
| `opportunity_score` | Stage 3 | unbounded | act on this issue |
| `emergence_score` | Stage 3 | ≥0 | growing fast |
| `evidence_gap_score` | Stage 3 | 0-1 | manager notes are missing required evidence |
| `silhouette_cosine_sample` | Stage 4 | -1 to 1 | clustering is well separated |
| `outlier_subtopic_confidence` | Stage 4 | 0-1 | ticket is central to its sub-theme |
| `urgency_level` | Stage 5 | 1-5 | urgent |
| `trust_risk_level` | Stage 5 | 1-5 | platform trust at stake |
| `money_risk_level` | Stage 5 | 1-5 | money at stake |
| `safety_policy_risk_level` | Stage 5 | 1-5 | CSAM/abuse/severe at stake |
| `confidence` | Stage 5 | 0-1 | LLM is sure |
| `centroid_similarity` | Stage 6 | 0-1 | ticket is central to its want cluster |
