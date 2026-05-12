# Module 05 — Statistics

By the end of Module 04 you have cluster IDs (`-1` to `52` from BERTopic, plus a
`-999` sentinel) attached to every ticket, a per-row `context_depth_score`, a
`primary_desire` slug, and resolution flags. You can answer descriptive
questions: how many tickets in cluster 6, what share are unresolved, who
handled them.

Descriptive answers are not enough.

When you write "Albert averages a context score of 25.29, Aziz averages 9.29",
the obvious next question — and the question every reader will ask — is
*"yes, but Aziz handles different work."* If Albert is mostly assigned to ban
appeals and Aziz to quick technical resets, the difference is in the case
mix, not in the writing. The 16-point gap could entirely reflect ticket
assignment.

When you write "the unresolved share in cluster 8 is 23.5% recently versus
19.2% in the prior 90 days", the obvious next question is *"is that real or
noise?"* A 4-percentage-point difference on a base of 26 recent tickets
versus 42 baseline tickets could easily be a coin flip.

This module builds the statistical machinery to answer both kinds of
question with numbers you can defend. The pipeline already runs every
technique below; you will read the real code, the real outputs, and learn
to interpret them.

## Prerequisites

- [Module 01 — Python Foundations](../01-python-foundations/README.md). You
  need NumPy arithmetic, `try/except` patterns for optional imports, and
  the conventions of the `outputs/option2_20260502_150055/` directory.
- [Module 02 — Data with pandas](../02-data-with-pandas/README.md). You
  need `groupby`, `value_counts`, boolean masks, `pd.Timedelta`, and
  knowledge of the `enriched_tickets.csv` schema (`context_depth_score`,
  `is_unresolved`, `manager`, `category`, `question_kind`, `role`,
  `status_en`, `month`, `primary_desire`).
- [Module 03 — Text and NLP](../03-text-and-nlp/README.md). You need to
  remember how the evidence flags (`has_url`, `has_image_url`, ...) and
  the `context_depth_score` formula are constructed in `featurize_tickets`.
- [Module 04 — Dimensionality and Clustering](../04-dimensionality-and-clustering/README.md).
  You need `issue_id` (the BERTopic cluster ID) and `issue_label` (the
  c-TF-IDF top-words label) on every ticket. The opportunity-backlog
  rankings in this module are computed per `issue_id`.
- The `outputs/option2_20260502_150055/` run on disk. Lessons load
  [`adjusted_manager_context_model.csv`](../../outputs/option2_20260502_150055/adjusted_manager_context_model.csv),
  [`manager_context_residuals.csv`](../../outputs/option2_20260502_150055/manager_context_residuals.csv),
  [`context_value_model.csv`](../../outputs/option2_20260502_150055/context_value_model.csv),
  [`opportunity_backlog.csv`](../../outputs/option2_20260502_150055/opportunity_backlog.csv),
  and [`enriched_tickets.csv`](../../outputs/option2_20260502_150055/enriched_tickets.csv).

## What you will be able to do after this module

- Read the OLS formula
  `context_depth_score ~ C(manager) + C(category) + C(question_kind) + C(role) + C(status_en) + C(month)`
  in
  [`adjusted_manager_context`](../../scripts/option2_pipeline.py) and
  explain every term: why each fixed effect is in the model, what
  baseline category Patsy picks automatically, and how to read a
  per-manager coefficient as "delta vs Albert after controlling for
  ticket mix". Reproduce the `-16.399` delta for Aziz from
  [`adjusted_manager_context_model.csv`](../../outputs/option2_20260502_150055/adjusted_manager_context_model.csv)
  by hand from the model output.
- Defend the choice of `cov_type="HC3"` in the same call. Explain in
  one paragraph what heteroscedasticity is, why default OLS standard
  errors lie when residuals scale with predicted value, and why HC3
  is the right small-sample-friendly variant of the Huber-White
  sandwich estimator. Show that flipping the argument off would
  change the p-values without changing the coefficient point estimates.
- Read the linear-probability model in
  [`build_context_value_model`](../../scripts/insight_layer.py) and
  explain in two sentences why we use OLS on a 0/1 outcome
  (`resolved_int`) instead of logit, citing complete separation in
  sparse categorical dummies. Convert the raw OLS coefficient
  `0.00153` on `context_depth_score` to "0.153 probability points
  per unit" and read the p-value of `0.241` honestly: the effect is
  not significant.
- Walk the two-proportion z-test
  `z = (p_recent - p_baseline) / sqrt(p_pool * (1-p_pool) * (1/n1 + 1/n2))`
  from [`build_opportunity_backlog`](../../scripts/insight_layer.py)
  line by line: the pooled-variance form, why we pool under the null,
  why we add `+ 0.0005` smoothing to the lift formula but not to
  the z statistic, and the |z| > 1.96 threshold for 5% significance.
  Read the real `trend_z = 2.209` for cluster 8 (`svip_svip points_buy svip_level`)
  in [`opportunity_backlog.csv`](../../outputs/option2_20260502_150055/opportunity_backlog.csv)
  and decide whether the recent uptick is signal or noise.
- Read the 95th-percentile capping logic in
  [`featurize_tickets`](../../scripts/option2_pipeline.py) — `char_cap`,
  `line_cap`, `url_cap` — and explain why the cap protects the score
  from the kind of 50,000-character outlier ticket that would otherwise
  saturate the formula.
- Read the non-parametric residual computation in
  [`build_context_gap`](../../scripts/insight_layer.py): subtract
  the `(category, question_kind)` cell mean from each ticket's score,
  group by manager, average. Verify Albert's residual of `+8.89`
  in
  [`manager_context_residuals.csv`](../../outputs/option2_20260502_150055/manager_context_residuals.csv)
  matches the OLS direction (Albert above baseline) — the same ranking
  from two methods is your robustness check that the OLS is not a
  modelling artefact.

## Lessons

| # | Lesson | What it covers |
|---|---|---|
| 01 | [OLS with fixed effects](01-ols-with-fixed-effects.md) | Linear regression. Patsy `C(...)` for categorical fixed effects. The real `adjusted_manager_context` model. Reading per-manager deltas (Aziz `-16.4`). |
| 02 | [Robust standard errors](02-robust-standard-errors.md) | Why default OLS SEs lie under heteroscedasticity. Huber-White HC0-HC3. Why we pick HC3 in this codebase. |
| 03 | [Linear probability model](03-linear-probability-model.md) | OLS on a 0/1 outcome instead of logit. Complete separation. Reading the real `0.153 pp` / `-2.073 pp` / `0.813 pp` coefficients honestly. |
| 04 | [Two-proportion z-test](04-two-proportion-z-test.md) | The pooled-variance z-test from `build_opportunity_backlog`. The `+0.0005` smoothing on lift. Real `trend_z` numbers like `2.209` for SVIP. |
| 05 | [Percentile capping and residuals](05-percentile-capping-and-residuals.md) | The 95th-percentile cap on length features. Non-parametric residual as a robustness check. Albert `+8.89` confirmed by both methods. |

Each lesson is 1500-2500 words and ends with a runnable "Try it" against
`outputs/option2_20260502_150055/`.

## What's next

- [Module 06 — LLMs and Prompts](../06-llms-and-prompts/README.md) takes
  the cluster `-1` outliers and produces a 250-row `(want, job, emotion)`
  taxonomy. The statistical machinery here applies again.
- [Module 09 — Streamlit Dashboards](../09-streamlit-dashboards/README.md)
  renders the adjusted-manager deltas, the residual table, and the
  opportunity backlog live.
- [Module 11 — The Findings](../11-the-findings/README.md) translates
  these numbers into recommendations.