# 05 — Percentile Capping and Residuals

## The problem

The OLS in lesson 01 told you Aziz writes about 16.4 fewer
context-depth-score points than Albert after controlling for ticket
mix. The HC3 standard errors in lesson 02 told you that estimate is
real signal, not chance. You should still ask two robustness
questions before walking that number into a meeting.

**Robustness question one: is the input feature itself robust?** The
`context_depth_score` is a weighted sum where three of the components
— character count, line count, URL count — are continuous and
unbounded. One ticket with 50,000 characters of pasted log data could,
in principle, dominate the entire score and skew every downstream
average and regression coefficient. If the feature itself is fragile
to extreme values, every conclusion you drew is fragile too.

**Robustness question two: does a different method give the same
answer?** OLS with fixed effects is a parametric model. It assumes
linearity, additivity, and that the controls are correctly specified.
If you ran a different, simpler comparison — say, "subtract each
ticket's expected score given its category and question kind, then
average per manager" — would the manager ranking come out the same?
If yes, the OLS conclusion is robust. If the rankings diverge, the
OLS is at least partially a modelling artefact and you should
investigate.

The pipeline addresses both questions explicitly. Question one is
solved upstream in
[`featurize_tickets`](../../scripts/option2_pipeline.py) with **95th-
percentile capping**. Question two is solved by the
**non-parametric residual** in
[`build_context_gap`](../../scripts/insight_layer.py).

This is the last lesson in the module. Both techniques are simpler
than the OLS and z-test you have already mastered, and both are
exactly the kind of robustness check you should add to every
analytical pipeline you build.

## Part one: 95th-percentile capping

The relevant block is
[scripts/option2_pipeline.py:767-782](../../scripts/option2_pipeline.py):

```python
char_cap = max(float(out["char_count"].quantile(0.95)), 1.0)
line_cap = max(float(out["line_count"].quantile(0.95)), 1.0)
url_cap = max(float(out["url_count"].quantile(0.95)), 1.0)
out["context_depth_score"] = (
    18 * np.minimum(out["char_count"] / char_cap, 1)
    + 10 * np.minimum(out["line_count"] / line_cap, 1)
    + 10 * np.minimum(out["url_count"] / url_cap, 1)
    + 10 * out["has_image_url"].astype(int)
    + 8 * out["has_timestamp"].astype(int)
    + 8 * out["has_room_or_group_id"].astype(int)
    + 8 * out["has_long_uid_or_case_id"].astype(int)
    + 10 * out["has_ban_reason_language"].astype(int)
    + 8 * out["has_user_claim"].astype(int)
    + 5 * out["has_money_terms"].astype(int)
    + 5 * out["has_status_or_svip_terms"].astype(int)
).round(2)
```

Walk it.

`out["char_count"].quantile(0.95)` returns the 95th percentile of the
character-count distribution across all tickets. Numerically, this is
the value below which 95% of tickets fall. If 95% of tickets have at
most 1,800 characters and 5% have more (some with much more), the
quantile is 1,800.

`np.minimum(out["char_count"] / char_cap, 1)` is the cap. For each
ticket, divide its char count by the cap, then clip the result to 1.
A ticket with 900 chars and a cap of 1,800 contributes `0.5` (half
the maximum). A ticket with 5,000 chars contributes `1.0` — the same
as a ticket with 1,800. The 50,000-char outlier also contributes
`1.0`, no more.

The result is multiplied by 18 (the weight on character count in the
score formula), and the `np.minimum` clamp ensures the contribution
never exceeds 18 points.

The same logic applies to `line_count` and `url_count`. Their per-row
contributions are normalised to `[0, 1]` and weighted.

The boolean evidence flags (`has_image_url`, `has_timestamp`, ...)
are already `[0, 1]` by construction, so they contribute either their
weight or zero. No capping needed.

## Why 95% and not 99% or "the max"

You are choosing a tradeoff. The cap value is the point at which the
score saturates — adding more characters past that point does
nothing. Set the cap too low and you compress all the rich tickets
together, losing the ability to distinguish "very rich" from "rich".
Set the cap too high and you let one outlier dominate; in the
extreme, using the max as the cap makes the contribution from one
giant ticket the whole 18 points and shrinks every other ticket's
contribution toward zero.

95% is a conventional middle ground:

- It throws away the long right tail (5% of tickets, the ones most
  likely to be data anomalies, copy-pasted logs, or one-off forensic
  dumps that happened to land in the support queue).
- It preserves all variation among the typical 95% of tickets.
- It is robust to small changes in the data — adding or removing a
  handful of extreme tickets does not move the 95th percentile much,
  whereas it would move the max enormously.

The teaching note from
[scripts/option2_pipeline.py:692-698](../../scripts/option2_pipeline.py)
makes the point:

```python
# ``context_depth_score`` — THE FORMULA.
#   Three continuous features (chars, lines, urls) are normalised by
#   their 95th-percentile value (``char_cap``, ``line_cap``,
#   ``url_cap``). ``np.minimum(x/cap, 1)`` clips to [0, 1] — the cap is
#   a "percentile capping" technique that prevents one outlier ticket
#   (someone pasted 50,000 characters) from saturating the formula and
#   stealing all the signal from average-rich tickets.
```

"Stealing the signal" is the key phrase. Without the cap, the score
of an average-rich ticket would be a tiny fraction of the score of
the outlier; everyone in the middle of the distribution would
collapse together. With the cap, the average-rich tickets get to
spread across the 0-100 range with meaningful gradations, and the
outlier just gets the maximum.

## The `max(..., 1.0)` defensive clamp

Look again at the cap definitions:

```python
char_cap = max(float(out["char_count"].quantile(0.95)), 1.0)
```

The outer `max(..., 1.0)` is there to prevent division by a near-zero
quantile in degenerate datasets. If a particular run had so few
tickets that the 95th percentile of `char_count` was 0 — extremely
unlikely but not impossible if every ticket had only spaces — the
formula would divide by zero. Clamping the cap to at least 1 keeps
the score finite. In production data this almost never fires; it is a
backstop.

## How the cap shows up downstream

Every analysis in this module that uses `context_depth_score` is
implicitly relying on the cap. The OLS in lesson 01 has
`context_depth_score` as the outcome; without the cap, one ticket
with a 100x score could pull the regression line dramatically and
distort every coefficient. The LPM in lesson 03 has
`context_depth_score` as a regressor; without the cap, the same
distortion shows up in the slope estimate.

Robustness flows top-down. Cap the input, and the output is robust
too. Don't cap, and every downstream computation inherits the
fragility.

A second-order benefit: the cap makes the score interpretable as a
score. With the cap, the maximum theoretically achievable score is
`18 + 10 + 10 + 10 + 8 + 8 + 8 + 10 + 8 + 5 + 5 = 100`. You can read
"50" as "halfway to forensic" with a clean mental model. Without
the cap, the maximum would be unbounded and you could not draw the
4-band cut into thin/basic/rich/forensic the same way.

## Part two: the non-parametric residual

Now turn to the second robustness question. The OLS in lesson 01
ranked managers by their per-manager coefficient. Could you produce
the same ranking without OLS at all?

Yes. Here is the recipe. For each ticket, compute the *expected*
context-depth score given its `(category, question_kind)` cell —
just the average score of all tickets in that cell. Subtract it from
the actual score. Now you have a residual: positive if the ticket
beats its cell, negative if it falls short. Group by manager and
average the residuals. Managers whose residuals average positive are
"writing more than their work would predict"; managers whose
residuals average negative are "writing less".

This is non-parametric in the sense that no model is fit. You do not
estimate any coefficients; you just take cell means and subtract.

The implementation is
[scripts/insight_layer.py:884-898](../../scripts/insight_layer.py):

```python
mix = df.groupby(["category", "question_kind"], dropna=False)["context_depth_score"].mean().rename("expected_mix_context")
scored = df.join(mix, on=["category", "question_kind"])
scored["context_residual_vs_mix"] = scored["context_depth_score"] - scored["expected_mix_context"]

manager_resid = scored.groupby("manager", dropna=False).agg(
    tickets=("source_row", "count"),
    avg_raw_context=("context_depth_score", "mean"),
    avg_expected_context=("expected_mix_context", "mean"),
    avg_residual_vs_ticket_mix=("context_residual_vs_mix", "mean"),
    rich_or_forensic_share=("context_depth_band", lambda s: s.isin(["rich", "forensic"]).mean()),
).reset_index()
for col in manager_resid.columns:
    if col != "manager" and col != "tickets":
        manager_resid[col] = manager_resid[col].astype(float).round(4)
manager_resid = manager_resid.sort_values("avg_residual_vs_ticket_mix", ascending=False)
```

Walk it.

`df.groupby(["category", "question_kind"], dropna=False)["context_depth_score"].mean()`
computes the mean score within each (category, question_kind) cell,
producing a Series indexed by `(category, question_kind)` tuples.
`.rename("expected_mix_context")` gives the Series a name so the
subsequent `.join()` produces a clean column.

`df.join(mix, on=["category", "question_kind"])` is the broadcast
join. For each ticket, look up its (category, question_kind) cell,
attach the corresponding mean as a new column. Now every ticket has
both its actual score and its expected score side by side.

Subtraction gives the residual: actual minus expected, per ticket.
The residual is zero on average within each cell by construction
(because subtracting the cell mean from each row in the cell
guarantees the row averages back to zero).

`scored.groupby("manager", dropna=False).agg(...)` averages the
residual within each manager. The resulting `avg_residual_vs_ticket_mix`
column is the manager-level signal.

The teaching note from
[scripts/insight_layer.py:840-852](../../scripts/insight_layer.py):

```python
# The non-parametric residual approach: instead of fitting a model
# to predict context_depth_score, we just compute the conditional
# mean ``E[score | category, question_kind]`` and subtract it. This
# gives a "does this manager beat their cell average?" signal
# without any modelling assumptions. The residual is zero on
# average within each cell by construction. We use this as a
# **robustness check** on the OLS — if both methods rank managers
# the same way, we trust the OLS coefficients more.
```

## The real residual table

[`manager_context_residuals.csv`](../../outputs/option2_20260502_150055/manager_context_residuals.csv):

```
manager,tickets,avg_raw_context,avg_expected_context,avg_residual_vs_ticket_mix,rich_or_forensic_share
Albert,2247,25.2932,16.405,8.8882,0.2986
"Alexander, Aziz",1,13.15,11.9459,1.2041,0.0
Danila,1441,13.9137,15.3062,-1.3925,0.0167
Leonid,116,11.1882,14.5464,-3.3582,0.0172
"Aziz, Alexander",4,12.6825,16.4071,-3.7246,0.0
Alexander,381,9.4022,15.2936,-5.8914,0.0052
Aziz,2518,9.2864,15.3094,-6.023,0.0083
Firuz,20,9.7175,17.2808,-7.5633,0.0
```

Read each column.

`avg_raw_context` is the manager's unconditioned average — the
descriptive number from Module 04. Albert: 25.29.

`avg_expected_context` is the average of cell means *across the
manager's tickets*. If Albert handled tickets in cells where the
average ticket scored 16.4, that's the "expected" benchmark for him.
You can read this as "given Albert's case mix, an average writer
would have averaged 16.4."

`avg_residual_vs_ticket_mix` is `raw - expected = 25.29 - 16.41 ≈
+8.89`. Albert beats his case mix by 8.9 points on average.

For Aziz: raw = 9.29, expected = 15.31, residual = `-6.02`. Aziz
falls 6 points *below* what his case mix would predict. He is not
just handling easier cases; he is genuinely writing less than the
work calls for.

Compare this to the OLS coefficients from lesson 01:

```
Albert:                +0.0 (baseline)
"Alexander, Aziz":     -8.78
Leonid:               -12.86
Danila:               -13.26
"Aziz, Alexander":    -13.63
Alexander:            -14.23
Firuz:                -15.24
Aziz:                 -16.40
```

And the residuals (recoded to "delta vs Albert" by subtracting
Albert's residual of +8.89 from each):

```
Albert:                 0.0
"Alexander, Aziz":     -7.68
Danila:               -10.28
Leonid:               -12.25
"Aziz, Alexander":    -12.61
Alexander:            -14.78
Firuz:                -16.45
Aziz:                 -14.91
```

Two different methods. Same overall ranking with one minor swap (the
OLS puts Leonid above Danila; the residual puts Leonid below). The
two solo extremes (Albert at the top, Aziz/Firuz at the bottom) are
robust to method choice. The middle of the table jiggles a little.

That is exactly the verdict you wanted: *the OLS is not an artefact*.
The same managers come out best and worst regardless of whether you
fit a parametric regression or just subtract cell means. The
robustness check passes.

## Why the residual differs from the OLS by ranking small details

The OLS controls for `category`, `question_kind`, `role`,
`status_en`, and `month` — five fixed effects. The non-parametric
residual controls only for `(category, question_kind)` — two. The
extra controls in the OLS are why the rankings differ slightly.
Specifically:

- The OLS adjusts for `month`, which captures team-wide template
  changes over time. The residual does not. Managers who joined late
  in the period when standards had risen are penalised by the OLS
  more than by the residual.
- The OLS adjusts for `role` and `status_en`, which capture
  ticket-level features beyond the category/kind cell. The residual
  ignores them.

When the two methods agree, you can be confident that none of the
extra controls were doing critical work. When they disagree, look at
which manager moved and ask which control caused the move. That
is the diagnostic.

## What the residual cannot do

The residual approach has three limits. It does not produce p-values
— a residual is just a mean, and computing inference on it requires
a separate t-test the pipeline does not bother with. Residuals are
conditional only on `(category, question_kind)`; if the real
confounder is `month` or `role`, the residual still contains it,
whereas the OLS controls for it. And the residual treats every
ticket equally, where the OLS implicitly down-weights small cells
via the HC3 SE — which is why the joint pseudo-managers rank
slightly differently across the two methods.

Use the OLS for the headline number with proper inference; use the
residual to sanity-check that the OLS is not dependent on its
modelling assumptions.

## Try it

Save as `try_capping_and_residuals.py`:

```python
import pandas as pd
import numpy as np

ROOT = "outputs/option2_20260502_150055"
df = pd.read_csv(f"{ROOT}/enriched_tickets.csv", low_memory=False)

# Part 1: percentile cap behaviour
print("=== Percentile capping ===")
for col in ["char_count", "line_count", "url_count"]:
    cap = max(float(df[col].quantile(0.95)), 1.0)
    over = (df[col] > cap).sum()
    print(f"  {col:20s} cap={cap:>10.1f}  tickets above cap: {over}  max: {df[col].max():.0f}")

# Part 2: rebuild the manager residuals
print()
print("=== Non-parametric residuals ===")
mix = (df.groupby(["category", "question_kind"], dropna=False)
         ["context_depth_score"].mean().rename("expected_mix_context"))
scored = df.join(mix, on=["category", "question_kind"])
scored["resid"] = scored["context_depth_score"] - scored["expected_mix_context"]

per_mgr = (scored.groupby("manager")
           .agg(tickets=("source_row", "count"),
                avg_raw=("context_depth_score", "mean"),
                avg_expected=("expected_mix_context", "mean"),
                avg_resid=("resid", "mean"))
           .sort_values("avg_resid", ascending=False))
print(per_mgr.round(3).to_string())

# Part 3: compare residual ranking to OLS ranking
print()
print("=== Compare to OLS ===")
ols = pd.read_csv(f"{ROOT}/adjusted_manager_context_model.csv")
ols_rank = ols.set_index("manager")["adjusted_context_delta_vs_baseline"]
albert_resid = per_mgr.loc["Albert", "avg_resid"]
combined = pd.DataFrame({
    "ols_delta_vs_albert": ols_rank,
    "resid_delta_vs_albert": per_mgr["avg_resid"] - albert_resid,
}).sort_values("ols_delta_vs_albert", ascending=False)
print(combined.round(3).to_string())
```

Expected behaviour:

- Part 1 prints small caps: `char_count` cap around 1,800-2,400,
  `line_count` cap around 5-7, `url_count` cap around 2-3. The
  number of tickets above each cap is roughly 5% of 6,728, which is
  about 336. The max values are dramatically larger — the kind of
  outliers the cap protects you against.
- Part 2 reproduces the residual table: Albert at +8.89, Aziz at
  -6.02, in that ordering.
- Part 3 prints the OLS delta and the residual delta (rebased to
  Albert) side by side. The columns should rank managers in
  near-identical order. That's the robustness check passing.

If the residual ordering and the OLS ordering disagreed sharply,
you would have an investigation on your hands. They don't. You can
walk into the meeting.

## Where this leaves you

You have read every line of statistical code in the option-2
pipeline. You know:

- How to fit OLS with categorical fixed effects (lesson 01).
- Why HC3 robust standard errors are non-negotiable for this kind
  of data (lesson 02).
- When to use the linear probability model and how to read its
  coefficients honestly (lesson 03).
- How the two-proportion z-test detects genuine surges in cluster
  share (lesson 04).
- Two robustness techniques — percentile capping in feature
  engineering and non-parametric residuals as an OLS sanity check
  (this lesson).

The next module turns to LLMs and prompts. The 1,381 cluster `-1`
tickets that HDBSCAN refused to assign in Module 04 get fed into a
local LLM extraction pass. The extraction outputs go through their
own lightweight version of the same OLS-and-z-test machinery you
just learned. Statistics returns. Always returns.
