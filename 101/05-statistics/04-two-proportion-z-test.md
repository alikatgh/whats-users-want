# 04 — The Two-Proportion Z-Test

## The problem

The previous three lessons have all been regressions. This one is a
simpler test, but you will run it more often than any regression in the
pipeline. It is the workhorse of the opportunity backlog and the
emerging-topics ranking.

The setup. Module 04 left you with cluster IDs (`issue_id` from
BERTopic) on every ticket. For each cluster you can split tickets into
"the last 30 days" and "the 90 days before that". You can compute the
share of all recent tickets that fell in this cluster
(`p_recent = recent_tickets_in_cluster / total_recent_tickets`) and the
same share for the baseline window (`p_baseline = baseline_tickets_in_cluster
/ total_baseline_tickets`). If `p_recent > p_baseline` the cluster is
trending up.

The question is whether that trend is real or noise. With small
clusters — say, 14 recent tickets versus 39 baseline tickets — random
variation alone can produce a 1.13× lift. You need a statistical test.

The two-proportion z-test is that test. The pipeline computes it inside
[`build_opportunity_backlog`](../../scripts/insight_layer.py) for every
cluster and stores the result as the `trend_z` column in
[`opportunity_backlog.csv`](../../outputs/option2_20260502_150055/opportunity_backlog.csv).
Same test runs in
[`build_emerging_topics`](../../scripts/insight_layer.py) for the
30-vs-180-day comparison.

This lesson walks the formula line by line, explains the choices the
pipeline made, and shows you how to read the real numbers in the CSV.

## The formula and what each piece means

The exact formula from
[scripts/insight_layer.py:541-546](../../scripts/insight_layer.py):

```python
p_recent = recent_tickets / recent_n
p_baseline = baseline_tickets / baseline_n
lift = (p_recent + 0.0005) / (p_baseline + 0.0005)
p_pool = (recent_tickets + baseline_tickets) / (recent_n + baseline_n)
denom = math.sqrt(max(p_pool * (1 - p_pool) * (1 / recent_n + 1 / baseline_n), 1e-9))
z = (p_recent - p_baseline) / denom
```

Read it top-down.

`recent_tickets` is the count of tickets in this cluster within the
last 30 days. `recent_n` is the total number of tickets across all
clusters within the last 30 days. `p_recent` is the cluster's share of
the recent corpus.

`baseline_tickets` and `baseline_n` are the same counts for the prior
window — defined in
[scripts/insight_layer.py:523-525](../../scripts/insight_layer.py)
as the 90 days before the recent window:

```python
max_date = df["date"].max()
recent_start = max_date - pd.Timedelta(days=30)
baseline_start = max_date - pd.Timedelta(days=120)
```

`p_baseline` is the cluster's share of the baseline corpus.

`p_pool` is the **pooled proportion**: as if you ignored the
recent-vs-baseline split and computed the cluster's share across the
combined window. This is the proportion you'd see under the null
hypothesis that recent and baseline come from the same population.

The denominator `sqrt(p_pool * (1 - p_pool) * (1/recent_n + 1/baseline_n))`
is the standard error of the difference between two proportions, under
the null. The intuition: the variance of a single sample proportion is
`p(1-p)/n`. The variance of the difference between two independent
sample proportions is the sum: `p(1-p)/n1 + p(1-p)/n2`. Pulling `p(1-p)`
out gives `p(1-p) * (1/n1 + 1/n2)`. Taking the square root gives the
standard error. Using the pooled `p` for `p(1-p)` is the standard
choice when you assume both samples come from the same population.

`z = (p_recent - p_baseline) / denom` is the test statistic. Numerator
is the observed difference. Denominator is its expected magnitude under
the null. A `z` of 1.96 means the observed difference is 1.96 standard
errors away from zero, which corresponds to a two-sided p-value of
0.05 in the standard normal distribution. A `|z| > 1.96` is the
conventional "significant at 5%" threshold; `|z| > 2.58` corresponds
to 1%.

## Pooled vs unpooled standard error

Two flavours of the two-proportion z-test exist. They differ only in
the denominator.

**Pooled** (what the pipeline uses):

    SE = sqrt( p_pool * (1 - p_pool) * (1/n1 + 1/n2) )

**Unpooled** (sometimes called Welch-style):

    SE = sqrt( p1*(1-p1)/n1 + p2*(1-p2)/n2 )

The pooled form is preferred when the **null hypothesis** is that the
two proportions are equal. Under the null, both samples are drawing
from a single population with proportion `p_pool`, so it makes sense
to estimate variance as if that were true. This makes the test more
powerful (smaller SE, larger z) when the null is roughly true, which
is exactly the case the test is designed to detect.

The unpooled form is preferred when constructing a confidence interval
for the *difference*, because the CI is about the actual difference,
not about whether it's zero. Under the alternative hypothesis, the two
populations have different proportions, so estimating each
separately is more honest.

The pipeline computes a **test statistic**, not a confidence interval,
so pooled is correct.

## Why the +0.0005 smoothing in `lift` but not in `z`

Two related but separate quantities come out of the same calculation.
The lift `(p_recent + 0.0005) / (p_baseline + 0.0005)` is a *ratio*
useful for ranking and human reading ("this topic surged 1.7x"). The
z statistic is a *test* that asks whether the difference is signal.

The lift formula divides by `p_baseline`. If `p_baseline` is exactly
zero — a topic that had no tickets in the baseline window — the
division is undefined. Without the smoothing constant, you would
either get a `DivisionByZeroError` or, worse, an infinite lift that
sorts to the top of every ranking and dominates the report.

The +0.0005 is a Laplace-style smoothing. It is small enough to barely
affect lifts based on many tickets:

- For `p_baseline = 0.05` (a healthy-sized topic) the denominator
  becomes 0.0505 instead of 0.05, a 1% change.
- For `p_baseline = 0.001` the denominator becomes 0.0015, a 50%
  change — the lift gets pulled toward 1, which is exactly the
  behaviour you want for tiny topics.

The teaching note from
[scripts/insight_layer.py:464-470](../../scripts/insight_layer.py):

```python
# The ``+ 0.0005`` smoothing in ``lift = (p_recent + 0.0005) /
# (p_baseline + 0.0005)`` is a tiny but critical trick. Without it, a
# topic with zero baseline tickets would yield a divide-by-zero or an
# infinite lift (a "topic of one" looking like a 1000x surge). The
# smoothing constant is small enough to barely affect lifts based on
# many tickets and large enough to bound lifts for tiny topics. This
# is the same idea as Laplace smoothing in NLP.
```

The z statistic does not get smoothing. Why? Because the z denominator
already has a different defensive trick — `max(..., 1e-9)` — that
prevents division by zero in the rare case where the pooled proportion
is exactly zero (no tickets in the cluster across the entire window).
And more importantly: the z-test is built around variances, not
ratios. Adding a smoothing constant to the proportions inside the z
formula would change what the test is testing. A z-test on smoothed
proportions is not the same hypothesis as a z-test on raw proportions,
and the standard normal distribution would no longer apply to the
output. So z is computed on raw proportions; the +0.0005 stays out of
it.

## Reading real `trend_z` numbers

[`opportunity_backlog.csv`](../../outputs/option2_20260502_150055/opportunity_backlog.csv)
has one row per cluster. The relevant columns are `recent_tickets`,
`baseline_tickets`, `recent_lift`, and `trend_z`. Five real rows:

```
issue_label,recent_tickets,baseline_tickets,recent_lift,trend_z
8_svip_svip points_buy svip_level,26,42,1.695,2.209
27_proofs_scammer_insulting_user insulting,23,35,1.794,2.284
21_group_unban group_unblock group_group blocked,16,25,1.738,1.823
0_account_restore_deleted_number,68,156,1.205,1.345
16_ban_penalty_reason_class,15,60,0.698,-1.298
```

Walk each one.

**Cluster 8 (SVIP/SVIP points)**: 26 recent vs 42 baseline. Lift = 1.7x.
z = +2.209. Above 1.96, so significant at 5%. This is a real surge.
The recent-window share genuinely grew faster than the baseline-window
share, and noise alone is unlikely to produce the gap. This is exactly
the kind of cluster the opportunity backlog should flag.

**Cluster 27 (proofs/scammer)**: 23 recent vs 35 baseline. Lift = 1.8x.
z = +2.284. Significant. Even smaller absolute volume than cluster 8,
but the lift is larger, which keeps z above the threshold.

**Cluster 21 (group/unban group)**: 16 recent vs 25 baseline. Lift =
1.7x. z = +1.823. Below 1.96. The point estimate looks like a surge,
but with this sample size you cannot rule out that the lift is noise.
Worth watching, not yet worth flagging.

**Cluster 0 (account/restore)**: 68 recent vs 156 baseline. Lift =
1.2x. z = +1.345. Larger absolute counts, smaller relative lift, z not
significant. Big topic, no surge.

**Cluster 16 (ban penalty)**: 15 recent vs 60 baseline. Lift = 0.7x.
z = -1.298. The cluster *shrank*, but not significantly. You should
not announce a decline unless |z| > 1.96 in the negative direction
either.

The pattern: clusters with both reasonable absolute volume *and*
substantial lift cross the z = 1.96 line. Clusters with only volume
or only lift do not.

## The defensive `max(..., 1e-9)` clamp

Look at the denominator again:

```python
denom = math.sqrt(max(p_pool * (1 - p_pool) * (1 / recent_n + 1 / baseline_n), 1e-9))
```

The `max(..., 1e-9)` is there because `p_pool` could be 0 (empty
cluster) or 1 (every ticket is in this cluster). In either case
`p_pool * (1 - p_pool)` is exactly zero, the variance is zero, and
the z denominator collapses. Dividing by zero produces `inf` or
`nan`, which corrupts the CSV.

The teaching note from
[scripts/insight_layer.py:472-473](../../scripts/insight_layer.py):

```python
# ``max(...,  1e-9)`` inside the ``sqrt`` of the z denominator is the
# same defensive idea — never let the denominator become exactly zero.
```

Substituting `1e-9` produces a finite (but enormous) denominator, so
z comes out finite (and tiny). That is the right behaviour: an empty
cluster cannot have a meaningful trend, and a tiny z reflects that.

## What `recent_n` and `baseline_n` are

These are total ticket counts in the windows, *not* per-cluster. From
[scripts/insight_layer.py:528-529](../../scripts/insight_layer.py):

```python
recent_n = max(int(recent_mask.sum()), 1)
baseline_n = max(int(baseline_mask.sum()), 1)
```

The `max(..., 1)` clamp avoids divide-by-zero in the proportion
calculation if a window happens to be empty, which would only happen
in pathological data.

For the May 2026 run, `recent_n` is roughly 1,200 (tickets in the last
30 days) and `baseline_n` is roughly 3,500 (tickets in the prior 90
days). Each cluster's `p_recent` and `p_baseline` are normalised by
those totals, so the test is asking "did this cluster's *share* of
the corpus grow?" — which is what you want — rather than "did the
absolute count grow?", which is dominated by overall ticket volume
trends.

## Why we test share, not absolute count

If overall ticket volume drops 30% in the last 30 days (a holiday lull,
say), every cluster's absolute count drops too. A cluster whose
**share** stayed flat would have its **count** down 30%, but it isn't
genuinely shrinking — the whole pie is smaller.

By dividing each cluster's count by the window total, we control for
overall corpus size. The two-proportion z-test is then asking "did the
mix change?", which is the question the opportunity backlog cares
about. A cluster whose share grew is genuinely emerging, even if
absolute volume across the corpus is flat.

## The same z-test in `build_emerging_topics`

[`build_emerging_topics`](../../scripts/insight_layer.py) runs the
same calculation with a different baseline window: 30 days vs the
*180* days before. The relevant block is
[scripts/insight_layer.py:658-669](../../scripts/insight_layer.py):

```python
recent_mask = df["date"].ge(windows["last_30"])
prior_mask = df["date"].ge(max_date - pd.Timedelta(days=180)) & df["date"].lt(windows["last_30"])
n_recent = max(int(recent_mask.sum()), 1)
n_prior = max(int(prior_mask.sum()), 1)
r = int((sub["date"].ge(windows["last_30"])).sum())
p = int((sub["date"].ge(max_date - pd.Timedelta(days=180)) & sub["date"].lt(windows["last_30"])).sum())
pr = r / n_recent
pp = p / n_prior
pool = (r + p) / (n_recent + n_prior)
z = (pr - pp) / math.sqrt(max(pool * (1 - pool) * (1 / n_recent + 1 / n_prior), 1e-9))
row["recent_vs_prior_lift"] = round((pr + 0.0005) / (pp + 0.0005), 3)
row["recent_vs_prior_z"] = round(z, 3)
```

Same formula, longer baseline. The longer baseline gives more
statistical power to detect medium-term trends, at the cost of less
sensitivity to short-term shifts. The two tables answer different
questions: the opportunity backlog flags acute issues that are surging
*right now*; the emerging-topics table flags issues that are *building
over the year*. Both use the same statistical test.

## What the z-test does not test

Three things to keep in mind.

**The z-test does not test whether the cluster is important.** A z of
2.2 on a 26-ticket cluster is statistically significant, but the
cluster is small. The opportunity_score formula combines z with
volume and unresolved share precisely so the ranking does not get
hijacked by tiny noisy clusters that happen to have significant z.

**The z-test does not adjust for multiple comparisons.** If you run
the test on 53 clusters at the 5% level, you expect about 2-3
"significant" results purely by chance, with no real underlying
trend. The pipeline does not Bonferroni-correct because the test is
used as one input to a ranking, not as a publishable hypothesis test.
You should still be careful when reading the very borderline cases:
out of 53 clusters, a handful with z near 2.0 are likely chance.

**The z-test assumes large samples.** The normal approximation breaks
down when expected counts are very small. A common rule of thumb:
both `recent_tickets` and `baseline_tickets` should be at least 5,
and both `recent_n - recent_tickets` and `baseline_n -
baseline_tickets` should be at least 5. For the small clusters in
our data, this is borderline. For tiny clusters with only 3-4 recent
tickets, you should not trust the z-test at all; a Fisher exact test
would be more honest. The pipeline does not run Fisher because the
output is downstream of an opportunity_score formula that already
de-weights tiny clusters via `sqrt(volume)`.

## Try it

Save as `try_z_test.py`:

```python
import math
import pandas as pd

ROOT = "outputs/option2_20260502_150055"
df = pd.read_csv(f"{ROOT}/enriched_tickets.csv", low_memory=False, parse_dates=["date"])

max_date = df["date"].max()
recent_start = max_date - pd.Timedelta(days=30)
baseline_start = max_date - pd.Timedelta(days=120)

recent_mask = df["date"].ge(recent_start)
baseline_mask = df["date"].ge(baseline_start) & df["date"].lt(recent_start)

recent_n = max(int(recent_mask.sum()), 1)
baseline_n = max(int(baseline_mask.sum()), 1)

print(f"recent_n   = {recent_n}")
print(f"baseline_n = {baseline_n}")
print(f"max_date   = {max_date.date()}")
print()

# Recompute z for the top clusters
print(f"{'issue_id':<6s} {'r':>5s} {'b':>5s} {'p_recent':>10s} {'p_base':>10s} {'lift':>6s} {'z':>7s}")
for issue_id, sub in df.groupby("issue_id", dropna=False):
    r = int((sub["date"].ge(recent_start)).sum())
    b = int((sub["date"].ge(baseline_start) & sub["date"].lt(recent_start)).sum())
    if r + b < 50:
        continue
    pr = r / recent_n
    pb = b / baseline_n
    lift = (pr + 0.0005) / (pb + 0.0005)
    pool = (r + b) / (recent_n + baseline_n)
    denom = math.sqrt(max(pool * (1 - pool) * (1/recent_n + 1/baseline_n), 1e-9))
    z = (pr - pb) / denom
    print(f"{str(issue_id):<6s} {r:>5d} {b:>5d} {pr:>10.4f} {pb:>10.4f} {lift:>6.3f} {z:>+7.3f}")

# Cross-check against the canonical CSV
canonical = pd.read_csv(f"{ROOT}/opportunity_backlog.csv")
print()
print("From CSV (top 5 by opportunity_score):")
print(canonical[["issue_label", "recent_tickets", "baseline_tickets",
                 "recent_lift", "trend_z"]].head().to_string(index=False))
```

Expected: your computed `z` values match the CSV's `trend_z` column to
three decimal places. If they do not match, the most common cause is
a different `max_date` — make sure your `parse_dates=["date"]` worked
and you read the same run directory.

The next lesson zooms back out to two robustness techniques that
sit on either side of the regression and z-test workflow: percentile
capping in feature engineering, and non-parametric residuals as a
sanity check on OLS.
