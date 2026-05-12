# 02 — Robust Standard Errors

## The problem

Lesson 01 fit an OLS regression and read out per-manager coefficients
from
[`adjusted_manager_context_model.csv`](../../outputs/option2_20260502_150055/adjusted_manager_context_model.csv).
The third column there is `p_value`. For Aziz, `p = 0.0` (printed
zero, actually a number smaller than 1e-5). For "Alexander, Aziz" the
joint pseudo-manager, `p = 0.029`. Those p-values determine whether
you can defensibly say "Aziz writes less context than Albert" versus
"the data are too noisy to tell".

The p-value is computed from a **standard error**, which is computed
under an assumption — that the residuals (the differences between
each ticket's actual `context_depth_score` and the model's predicted
score) have **the same variance everywhere**. That assumption is
called *homoskedasticity*. In real ticket data it is almost never
true. Variance scales with predicted value, with category, with how
long the ticket is, with which manager wrote it.

When the assumption fails — and it will fail — the default OLS
standard errors are wrong, the t-statistics are wrong, and the
p-values lie. The coefficients themselves are still unbiased; only
the uncertainty estimates are broken. You can still see the point
estimate, but you cannot honestly say whether it is statistically
distinguishable from zero.

The fix is the **Huber-White sandwich estimator**, which produces
standard errors that are valid under arbitrary heteroskedasticity. The
pipeline uses the HC3 variant in both regressions:

- [`adjusted_manager_context`](../../scripts/option2_pipeline.py)
  passes `cov_type="HC3"` to `.fit()`.
- [`build_context_value_model`](../../scripts/insight_layer.py) does
  the same.

This lesson explains what those four characters do.

## What heteroskedasticity actually looks like

Imagine you fit `context_depth_score ~ C(manager) + ...` and look at
the residuals — actual minus predicted, one number per ticket.

For tickets where the model predicted a score around 5 (a thin,
quick-resolve ticket), the residuals cluster tightly around zero;
maybe a typical residual is plus or minus 3 points. The model is
fairly confident there.

For tickets where the model predicted a score around 40 (a forensic
ban appeal), the residuals scatter widely; some are +20, some are
-15. The model knows roughly where the score should land but has much
less precision.

That is heteroskedasticity. The variance of the residual depends on
the predicted value. Plot residuals versus predicted; if the cloud
fans out into a horn shape rather than staying in a horizontal band,
you have it.

For binary outcomes the situation is even worse: if `y` is 0 or 1
and the model predicts probability `p`, the residual variance is
`p(1-p)`, which is exactly zero when `p` is near 0 or 1 and exactly
0.25 when `p` is 0.5. There is no way to make the residual variance
constant — it is a mathematical consequence of the outcome being
binary. Lesson 03 will return to that point in detail.

## What the default OLS standard error gets wrong

The textbook OLS standard error formula assumes residuals are
independent and have a single shared variance `sigma^2`. Under that
assumption the variance of the coefficient vector `b` is

    Var(b) = sigma^2 * (X'X)^(-1)

and `sigma^2` is estimated as the sum of squared residuals divided
by degrees of freedom. The square root of the diagonal of that
matrix gives standard errors. The t-statistic for each coefficient is
`coef / SE`, and the p-value comes from the t (or normal) distribution.

If residual variance is not constant — if it depends on the row's
predictors — then `sigma^2 * (X'X)^(-1)` is the wrong matrix. It
will systematically understate uncertainty for some coefficients and
overstate it for others. P-values come out artificially small for
the noisy regions of the data, which makes things look more
significant than they are. That is exactly the failure mode you do
not want when you are about to walk into a coaching meeting.

## The Huber-White sandwich estimator

Friedhelm Eicker, Peter Huber, and Halbert White, in three papers
between 1963 and 1980, derived a different formula that works under
arbitrary heteroskedasticity:

    Var(b) = (X'X)^(-1) * (X' * Omega * X) * (X'X)^(-1)

The reason it is called a "sandwich" is the structure: there are
two slices of `(X'X)^(-1)` (the bread) around a meat term involving
`Omega`. `Omega` is the diagonal matrix of squared residuals — one
per observation. The sandwich form lets each row contribute its own
variance to the standard error rather than assuming a single
shared `sigma^2`.

You do not have to compute this by hand. Statsmodels does it for you
when you pass `cov_type="HC3"` to `.fit()`. The "HC" stands for
"heteroskedasticity-consistent". The number after it picks one of
five variants — HC0, HC1, HC2, HC3, HC4 — that differ only in how
they correct for finite-sample bias.

## Why HC3 specifically

The five HC variants modify the meat slice differently. HC0 uses raw
squared residuals. HC1 multiplies by `n / (n - k)` to account for
degrees of freedom. HC2 divides each squared residual by `1 - h_i`
where `h_i` is the leverage of observation i (a measure of how
extreme that row's predictors are). HC3 divides by `(1 - h_i)^2`
— the most aggressive correction — and is the one MacKinnon and
White (1985) recommended for small to medium samples.

HC3 is more conservative than HC0 in the sense that it produces
slightly larger standard errors and therefore slightly larger
p-values. That is what you want for honest reporting: it makes the
test harder to pass, which is exactly the right direction when you
suspect heteroskedasticity might be inflating false-positive rates.

The teaching note from
[scripts/option2_pipeline.py:901-910](../../scripts/option2_pipeline.py)
captures the practical summary:

```python
# WHY HC3-ROBUST STANDARD ERRORS.
# The OLS standard p-value formula assumes residuals are
# homoskedastic — same variance everywhere. In support-ticket data
# that's almost never true: variance scales with category, ticket
# length, and so on. ``cov_type="HC3"`` switches to MacKinnon &
# White's HC3 sandwich estimator, which produces standard errors
# that are valid under arbitrary heteroskedasticity. HC3 is the
# most conservative of the HC variants and the modern default for
# small/medium samples. The point estimates (the deltas) don't change
# — only the standard errors and therefore the p-values.
```

Three takeaways from that note.

First, "the point estimates don't change". This is critical. Switching
the standard-error type does not move the coefficients at all. The
coefficient on `C(manager)[T.Aziz]` will still read `-16.399`
whether you pass `cov_type="HC3"` or omit it entirely. Only the
SEs, t-stats, and p-values shift.

Second, "small/medium samples". Our N is 6,728. That counts as
medium. For very large N (millions of rows) HC0 and HC3 produce
nearly identical results because the leverage-based correction
becomes negligible. For our scale, the correction matters by a few
percent.

Third, "valid under arbitrary heteroskedasticity". The estimator does
not require you to *model* the heteroskedasticity. It works regardless
of which functional form the residual variance takes. That makes it
robust in the engineering sense: you do not need to be right about
the variance pattern, only to acknowledge that there might be one.

## How `cov_type="HC3"` flows into the CSV

The output column `p_value` in
[`adjusted_manager_context_model.csv`](../../outputs/option2_20260502_150055/adjusted_manager_context_model.csv)
comes directly from `fit.pvalues[term]`. When you pass
`cov_type="HC3"` to `.fit()`, statsmodels recomputes the covariance
matrix using the HC3 sandwich formula. Every downstream property of
the fit — `bse` (standard errors), `tvalues` (t-statistics),
`pvalues`, `conf_int()` — is computed from that HC3 matrix.

So when the CSV reads `p = 0.02892` for "Alexander, Aziz" and
`p = 0.0` for solo Aziz, those are HC3 p-values. They are the
honest version. Without HC3 they would be smaller — sometimes
materially smaller. A coefficient that looks `p = 0.02` under default
SEs might be `p = 0.08` under HC3, and the latter is the one you
should believe.

## A case study: why "Alexander, Aziz" has p = 0.029 but Aziz alone has p = 0.000

Look at the CSV again:

```
manager,adjusted_context_delta_vs_baseline,baseline_manager,p_value,model_r2
Albert,0.0,Albert,,0.3559
"Alexander, Aziz",-8.783,Albert,0.02892,0.3559
Leonid,-12.859,Albert,0.0,0.3559
Danila,-13.261,Albert,0.0,0.3559
"Aziz, Alexander",-13.628,Albert,0.00236,0.3559
Alexander,-14.23,Albert,0.0,0.3559
Firuz,-15.237,Albert,0.0,0.3559
Aziz,-16.399,Albert,0.0,0.3559
```

"Alexander, Aziz" is the joint label that appears when two managers
co-handled a ticket. Solo Aziz handled 2,518 tickets. Solo Alexander
handled 381. The joint label appears on 1 ticket (you can verify
from
[`manager_context_residuals.csv`](../../outputs/option2_20260502_150055/manager_context_residuals.csv)).
The "Aziz, Alexander" version (different ordering) appears on 4.

A coefficient estimated from 1 ticket has enormous standard error.
That is why the joint pseudo-managers' p-values are much larger
(0.029, 0.002) despite the deltas being similar in magnitude to the
solo ones. The sandwich formula correctly inflates the SE because
those rows have tiny effective sample size; the default formula
would also inflate it but less aggressively, because it doesn't
know that those particular rows live alone in their own
pseudo-manager bucket.

This is exactly the regime where HC3 earns its keep. The leverage
`h_i` for those single-ticket rows is high (they are all alone in
their level), so dividing by `(1 - h_i)^2` blows up the squared
residual contribution and produces a properly cautious SE. Default
OLS would understate uncertainty here.

The solo-Aziz delta, by contrast, is estimated from 2,518 tickets.
The standard error is small either way; HC3 versus default makes a
small percentage difference. The p-value rounds to 0.0 under both.

## What about clustered standard errors?

You may have read that for repeated observations on the same unit
(in our case: many tickets handled by the same manager) the
"correct" robust SE is *clustered* by manager — not just
heteroskedasticity-robust. The argument is that manager-level
shocks (a particularly bad week for Aziz, a template change Albert
adopted early) introduce correlation among that manager's
residuals, and HC3 alone doesn't account for that.

The pipeline does not cluster, and the reason is pragmatic: with
only 8 managers, cluster-robust SEs are themselves badly behaved.
Cluster-robust inference assumes you have many clusters (typically
30+) for asymptotic theory to apply. With 8 clusters the standard
errors get *too* large in unpredictable ways. HC3 strikes a
reasonable middle ground — it is heteroskedasticity-robust, which
is the failure mode we are most worried about, and it does not
require us to assume independence within manager (it does not
*assume* the opposite either; it is just silent on within-manager
correlation).

If we had 50 managers we would cluster. With 8 we don't.

## How to verify HC3 is actually being applied

You can read it off the fit object. After running

```python
fit = smf.ols(formula, data=m).fit(cov_type="HC3")
```

inspect:

```python
print(fit.cov_type)              # 'HC3'
print(fit.bse["C(manager)[T.Aziz]"])     # HC3 standard error
print(fit.pvalues["C(manager)[T.Aziz]"]) # p-value computed from that SE
```

If you re-fit without `cov_type="HC3"` and compare:

```python
fit_default = smf.ols(formula, data=m).fit()
print(fit_default.cov_type)              # 'nonrobust'
print(fit_default.bse["C(manager)[T.Aziz]"])
print(fit_default.pvalues["C(manager)[T.Aziz]"])
```

you will see:
- `fit.params` is identical between the two — the coefficients do
  not depend on the SE choice.
- `fit.bse` differs — HC3 is usually a touch larger.
- `fit.pvalues` differs proportionally — slightly larger under HC3.

For solo-Aziz the difference is negligible because the cell is
huge. For "Alexander, Aziz" the difference is larger because the
cell is tiny. That is exactly the pattern HC3 is designed to
capture.

## When to be suspicious of even HC3

Robust standard errors fix one specific problem: heteroskedasticity.
They do not fix:

- *Specification error*. If you forgot a fixed effect that matters
  — say, you didn't control for `month` and there is a strong time
  trend correlated with manager assignment — the coefficient itself
  is biased, not just the SE. HC3 cannot save you from a
  mis-specified model. You have to add the missing covariate.
- *Endogeneity*. If `manager` is correlated with an unobserved
  variable that also drives `context_depth_score` (for example,
  ticket-routing rules that send hard cases to Albert), the
  coefficient is again biased. HC3 doesn't help. You need an
  instrumental variable or a randomised assignment.
- *Within-cluster correlation that you have many clusters for*. If
  your data had 50 managers, you would want cluster-robust SEs
  rather than HC3.

The pipeline is honest about the first two: the
[interpretation](../../outputs/option2_20260502_150055/adjusted_manager_context_model.csv)
column reads "positive means richer context after controlling for
category/kind/role/status/month" — *after controlling for those*.
It does not claim the coefficient is causal.

## Try it

Save as `try_robust_se.py` in the project root.

```python
import pandas as pd
import statsmodels.formula.api as smf

ROOT = "outputs/option2_20260502_150055"
df = pd.read_csv(f"{ROOT}/enriched_tickets.csv", low_memory=False)

cols = ["context_depth_score", "manager", "category", "question_kind",
        "role", "status_en", "month"]
m = df[cols].copy()
for c in cols[1:]:
    m[c] = m[c].fillna("").replace("", "Unknown")

formula = ("context_depth_score ~ C(manager) + C(category) + C(question_kind) "
           "+ C(role) + C(status_en) + C(month)")

fit_default = smf.ols(formula, data=m).fit()
fit_hc3     = smf.ols(formula, data=m).fit(cov_type="HC3")

print(f"{'manager':<24s} {'coef':>10s}   {'SE_def':>8s}  {'p_def':>8s}   {'SE_HC3':>8s}  {'p_HC3':>8s}")
for term in fit_hc3.params.index:
    if not term.startswith("C(manager)[T."):
        continue
    name = term.removeprefix("C(manager)[T.").rstrip("]")
    coef = fit_hc3.params[term]
    se_d = fit_default.bse[term]
    p_d  = fit_default.pvalues[term]
    se_h = fit_hc3.bse[term]
    p_h  = fit_hc3.pvalues[term]
    print(f"{name:<24s} {coef:+10.3f}   {se_d:8.3f}  {p_d:8.4f}   {se_h:8.3f}  {p_h:8.4f}")

print()
print(f"Coefficients identical:  {fit_default.params.equals(fit_hc3.params)}")
print(f"Default cov_type:        {fit_default.cov_type}")
print(f"HC3 cov_type:            {fit_hc3.cov_type}")
```

Expected behaviour:

- `fit_default.params.equals(fit_hc3.params)` prints `True`. The
  point estimates do not depend on the SE choice.
- For solo Aziz, `SE_def` and `SE_HC3` are close; both p-values
  round to 0.
- For "Alexander, Aziz" (the 1-ticket pseudo-manager), `SE_HC3` is
  noticeably larger than `SE_def`, and `p_HC3` ≈ 0.029 matches
  the CSV. `p_def` is smaller — the default SE understates
  uncertainty for that high-leverage row, exactly as the theory
  predicts.

If you want one more sanity check: pass `cov_type="HC0"` and
`cov_type="HC1"` to see how the lighter variants compare. For our
sample size HC3 produces SEs roughly 1-3% larger than HC0, which
is the small-sample correction in action.

The next lesson tackles a different failure mode: what happens when
the outcome itself is 0 or 1, and why we use OLS on it anyway.
