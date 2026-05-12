# 03 — Stage 3: `insight_layer.py`

[Source](../../scripts/insight_layer.py).

This is where we cross from "we have topics" to "we have a backlog and personas." Every section adds one decision-relevant artifact.

## Inputs and joining (lines 59-101)

`load_run(run_dir)` reads `enriched_tickets.csv`, parses dates, coerces booleans (since CSV round-trips them as strings), and merges in BERTopic assignments if available.

The merging logic in [insight_layer.py:88-101](../../scripts/insight_layer.py#L88-L101) is important:

- If BERTopic exists, every ticket gets `issue_id` = `bertopic_topic` if BERTopic assigned one, else falls back to the Stage 1 `cluster_id`.
- If neither, `issue_id = -999` (bad data signal).
- `issue_label` falls back to `cluster_<id>` when BERTopic did not provide a name.

So `issue_id` is the single field downstream uses to group tickets, regardless of which clusterer labelled them.

## Section A — Opportunity backlog

`build_opportunity_backlog(df)` (lines 142-203).

For each `issue_id`, computes:

- `tickets`, `unique_users`, `repeat_user_share`
- `unresolved_share`
- `avg_context_score`
- `rich_or_forensic_share` = fraction in band ∈ {rich, forensic}
- `urgency_avg` (mean of `urgency_signal`)
- `trust_money_risk` = mean of `trust_money_flag`, where `trust_money_flag = primary_desire ∈ RISK_DESIRES OR has_money_terms OR has_status_or_svip_terms`
- `recent_tickets` (last 30 days), `baseline_tickets` (days 30-120 before max date)
- `recent_lift` = `(p_recent + 0.0005) / (p_baseline + 0.0005)`
- `trend_z` = standard two-proportion z-statistic between recent and baseline shares (lines 162-166)
- `top_desires`, `top_categories`, `top_managers`, three example questions

Then the **opportunity score**:

```
opportunity_score =
    sqrt(volume) * (
        1 + 2.2 * unresolved_share
          + 1.2 * min(max(recent_lift - 1, 0), 3)
          + 1.4 * trust_money_risk
    )
    + 8 * rich_or_forensic_share
    + 0.06 * avg_context_score
```

The `sqrt(volume)` prevents giant topics from drowning out smaller, riskier ones. The capped lift (`min(..., 3)`) prevents one freak month from dominating. `trust_money_risk` is weighted heavily (1.4×) because financial/safety issues outweigh nuisances.

### `issue_action(row)` (lines 117-139)

A rule-based recommendation that turns the row into a one-line action:

| Condition | Action |
|---|---|
| issue_id == "-1" | Split semantic outlier bucket: sample, relabel, and rerun guided topics. |
| issue_id == "-999" | Fix source data quality: missing or unclustered text rows need review. |
| `trust_money_risk ≥ 0.35` AND `unresolved_share ≥ 0.20` | Create escalation playbook + policy owner; this is trust/money/status risk. |
| `recent_lift ≥ 1.8` AND `recent_tickets ≥ 10` | Investigate as emerging issue; create daily monitor and sample 20 cases. |
| `tickets ≥ 100` AND `unresolved_share < 0.10` AND `avg_context_score < 14` | Automate/self-serve; high-volume low-complexity support demand. |
| `avg_context_score ≥ 24` AND `rich_or_forensic_share ≥ 0.25` | Build casebook/training set; rich evidence can teach classifiers and agents. |
| label contains `dealer/diamonds/seller/scam` | Map money journey; separate legitimate commerce from scam/dispute flows. |
| label contains `blocked/unban/ban` | Improve ban transparency: reason, evidence, appeal path, repeat penalty history. |
| label contains `account/restore/deleted` | Design account-recovery self-service with identity and phone/SIM edge cases. |
| label contains `channel/group/limit` | Create creator/channel ops workflow: visibility, limits, ownership, feed health. |
| else | Review representative examples; decide FAQ, macro, product fix, or escalation. |

## Section B — Emerging topics

`build_emerging_topics(df)` (lines 206-243).

Compares **last-30-days** volume against the previous 150-day baseline (days 30-180 before max date) for each topic. Computes:

- `last_30_tickets`, `last_60_tickets`, `last_90_tickets` (and their share-of-issue)
- `recent_vs_prior_lift` — the same lift formula
- `recent_vs_prior_z` — two-proportion z-test
- `recent_unresolved_share` — unresolved fraction in last 30 days
- `emergence_score = sqrt(last_30_tickets) * min(lift, 6) * (1 + recent_unresolved_share)`

Sorted descending by `emergence_score`, then by `last_30_tickets`. The "Emerging Topics" section of the report is `head(10)` of this.

## Section C — Repeat-user personas

`build_repeat_user_personas(df)` (lines 264-290) and `persona_for_user(group)` (lines 246-261).

For each UID with ≥2 tickets, assigns one of seven personas using a priority cascade:

```
1. earn_or_transact_money + (protect_from_abuse_or_scam OR mentions scam/diamonds)
   → commerce_dispute_or_scam_risk
2. clear_name_or_get_fairness + unresolved_mean ≥ 0.25
   → repeat_ban_appeal_or_fairness_seeker
3. grow_audience_or_community
   → creator_channel_operator
4. gain_status_or_privileges
   → svip_status_optimizer
5. recover_access
   → account_recovery_repeat_user
6. ≥4 distinct desires
   → multi_problem_power_user
7. else
   → general_repeat_user
```

The output table includes per-user diagnostics: tickets, active_days_span, first/last date, unresolved_share, avg_context_score, managers_seen, top_desires, top_issues, two example tickets.

## Section D — Context residuals and evidence gaps

`build_context_gap(df)` (lines 293-338).

### Manager residuals

For each `(category, question_kind)` pair, compute the population mean `context_depth_score`. That is the "expected mix context" for a ticket of that type. Then `context_residual_vs_mix = context_depth_score - expected_mix_context` per ticket. Aggregate by manager.

This is the **observed** version of the regression in Stage 1: it does not make distributional assumptions. The ranking by `avg_residual_vs_ticket_mix` is what produces:

> Albert: residual +8.89 (raw 25.29, expected mix 16.41)

### Issue evidence gaps

For each issue_label with ≥20 tickets, derive what evidence *should* be present based on dominant desire:

- If the dominant desire is `clear_name_or_get_fairness` or label mentions ban/unban/penalty → require `[has_timestamp, has_ban_reason_language, has_user_claim]`.
- If `earn_or_transact_money` or `protect_from_abuse_or_scam` or label mentions money/diamonds/scam/dealer → require `[has_money_terms, has_image_url, has_long_uid_or_case_id]`.
- If `grow_audience_or_community` or label mentions channel/group/room/creator → require `[has_room_or_group_id, has_image_url]`.
- Default → `[has_url, has_image_url, has_multiline_note]`.

Then for each required evidence type, compute `1 - mean(flag)` as the "missing share" and record the top-4 largest gaps. The score is `mean(missing_shares)`.

## Section E — Context value model

`build_context_value_model(df)` (lines 341-371).

A linear-probability model (OLS, not logit, to avoid separation issues with sparse categories):

```
resolved_int ~ context_depth_score + evidence_element_count + urgency_signal
              + C(category) + C(question_kind) + C(role) + C(month) + C(primary_desire)
```

`cov_type="HC3"` for robust SEs.

We report only the three continuous coefficients (`context_depth_score`, `evidence_element_count`, `urgency_signal`) as **probability points per unit** (the OLS coefficient × 100), with p-values and 95% CI.

Result for the current run:
- `context_depth_score`: +0.153 pp/unit, p=0.241, CI [-0.103, +0.409]
- `evidence_element_count`: -2.073 pp/unit, p=0.172, CI [-5.048, +0.901]
- `urgency_signal`: +0.813 pp/unit, p=0.255, CI [-0.588, +2.214]

None statistically significant. The honest interpretation: rich notes are not a productivity lever; they are an understanding lever.

## Section F — Manager evidence coaching

`build_manager_evidence_coaching(df)` (lines 374-411).

Picks the benchmark manager (Albert if present, else the manager with highest mean context score). For each evidence column, computes the benchmark's rate. Then for each manager:

```
gap = benchmark_rate - manager_rate
if gap > 0.03:
    record (column, gap)
```

Sort gaps descending, take top 4, render as `"<human label> (+X% to benchmark)"`. The human labels are:

```
has_url                 → "attach source links/screens"
has_image_url           → "attach image evidence"
has_timestamp           → "record exact event/ban timestamps"
has_room_or_group_id    → "capture room/group/channel IDs"
has_long_uid_or_case_id → "capture UID/case IDs"
has_ban_reason_language → "copy ban/review reason text"
has_user_claim          → "quote user's claim or denial"
has_money_terms         → "mark money/diamond/payment involvement"
has_status_or_svip_terms → "mark SVIP/status/points involvement"
has_multiline_note      → "write structured multiline notes"
```

## Outputs

`write_outputs(run_dir, tables)` writes one CSV per table, an Excel workbook with one sheet per table, and registers each as a DuckDB table in the existing `analysis.duckdb`.

`append_report` adds an "Insight Layer" section to `executive_findings.md`. If a previous insight section is already there, it is replaced (not duplicated) using a marker-based split.

## Output tables (one CSV each)

- `opportunity_backlog.csv`
- `emerging_topics.csv`
- `repeat_user_personas.csv`
- `manager_context_residuals.csv`
- `issue_evidence_gaps.csv`
- `context_value_model.csv`
- `manager_evidence_coaching.csv`
- `insight_layer_workbook.xlsx`

## Command-line

```bash
python scripts/insight_layer.py [outputs/option2_<TIMESTAMP>]
```

Run-dir is optional; defaults to the latest folder under `outputs/`.
