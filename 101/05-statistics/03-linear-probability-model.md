# 03 — The Linear Probability Model

## The problem

So far the regression in this module had a continuous outcome:
`context_depth_score`, a number between roughly 0 and 100. OLS makes
sense there. The next question the pipeline wants to answer is
*different*: does writing more context help resolve the ticket?

The outcome of interest is **resolved or not**. That is binary. Each
ticket either ended up resolved (1) or didn't (0). The
[`enriched_tickets.csv`](../../outputs/option2_20260502_150055/enriched_tickets.csv)
column `is_unresolved` is a boolean; the pipeline flips it to a 0/1
integer named `resolved_int` for the regression.

If you went looking for a textbook on binary outcomes, every chapter
would tell you to use **logistic regression**. Logit constrains
predicted probabilities to the interval `(0, 1)` and has neat maximum-
likelihood properties. You have probably written a `LogisticRegression`
fit in scikit-learn before.

The pipeline does not use logit. It uses OLS, on the 0/1 outcome,
with HC3 robust standard errors. Real call from
[scripts/insight_layer.py:1011-1018](../../scripts/insight_layer.py):

```python
model_df = df.copy()
model_df["resolved_int"] = (~model_df["is_unresolved"]).astype(int)
for col in ["manager", "category", "question_kind", "role", "month", "primary_desire"]:
    model_df[col] = model_df[col].fillna("Unknown").astype(str).replace("", "Unknown")
# A logit can fail on separation with many sparse categories; OLS/LPM is stable and interpretable.
formula = "resolved_int ~ context_depth_score + evidence_element_count + urgency_signal + C(category) + C(question_kind) + C(role) + C(month) + C(primary_desire)"
try:
    fit = smf.ols(formula, data=model_df).fit(cov_type="HC3")
```

This is a **linear probability model** (LPM). It looks unusual, it
violates one of the textbook assumptions of OLS, and the pipeline uses
it on purpose. This lesson explains why, and how to read the output
honestly.

## Why not logit: complete separation

Logit fits by maximum likelihood. The likelihood function involves
terms like `log(p)` and `log(1 - p)` for each observation; the optimiser
finds coefficients that maximise the joint log-likelihood. When the
data are well-behaved that procedure converges to a unique optimum.

It blows up when a categorical predictor *perfectly predicts* the
outcome. If every ticket in some sparse cell is resolved, the MLE for
the dummy on that cell wants to push the predicted probability to 1,
meaning the coefficient wants to go to `+infinity`. The optimiser
either fails to converge, throws a numerical warning and returns
nonsense, or quietly produces an estimate with infinite standard error.

This is **complete separation**. With a single categorical predictor
it is rare. With six categorical fixed effects crossed together, the
number of cells is the product of their levels:

- `category`: about 20 unique values
- `question_kind`: about 12 unique values
- `role`: 4 or 5 values
- `month`: 12 values
- `primary_desire`: 11 values

The Cartesian product is 20 × 12 × 5 × 12 × 11 ≈ 158,000 possible cells,
divided across only 6,728 tickets. Most cells have 0 tickets. Many of
the cells with any tickets at all have only 1 or 2, and because
resolution is roughly 80% in the corpus, plenty of those small cells
will be 100% resolved or 100% unresolved by chance. Each such cell is a
separation point.

The teaching note from
[scripts/insight_layer.py:953-963](../../scripts/insight_layer.py)
makes the point directly:

```python
# Why OLS on a 0/1 outcome (a "linear probability model"):
#
# The natural choice for binary outcomes is logistic regression —
# it constrains predicted probabilities to (0, 1) and has nice
# likelihood properties. But logit fits via maximum likelihood and
# runs into **complete separation** when categorical variables are
# sparse: if a (category × question_kind) cell has 100% resolved or
# 100% unresolved tickets, the MLE coefficient blows up to ±∞ and
# the optimiser fails (or worse, returns nonsense). Our 6,728
# tickets split across category × question_kind × role × month ×
# primary_desire have many sparse cells, so logit is fragile.
```

OLS does not have this problem. Its closed-form solution
`b = (X'X)^(-1) X'y` always exists (as long as X has full rank), and
sparse cells just produce coefficients with large standard errors
rather than infinite coefficients. The optimiser does not need to
converge; there is no optimiser. You get an answer.

## What you give up: predictions outside [0, 1]

The price you pay is that linear-probability predictions are not
constrained to the unit interval. For a ticket with very low predicted
resolution probability, the model might output `-0.05`. For a very
high one, `1.10`. Those are not valid probabilities in the strict
sense — you cannot report them as predictions for a *single* ticket.

Two things to know about this.

First, if you only want to interpret the *coefficients* — "how much
does writing one more context-depth point shift the probability of
resolution, on average, holding controls constant?" — you do not
care about the unit-interval issue. The coefficient is an unbiased
estimate of the *average marginal effect* of the predictor on the
probability, regardless of where individual predictions land. That is
exactly what we want here.

Second, when you report numbers per ticket, you can clip predicted
probabilities to `[0, 1]` post hoc. The pipeline does not do this
because the LPM output is a coefficient table, not a per-row prediction.

The teaching note continues at
[scripts/insight_layer.py:965-973](../../scripts/insight_layer.py):

```python
# OLS doesn't have this problem. It always converges in closed
# form. The coefficients are interpreted as **changes in
# probability** because the outcome is ``{0, 1}``: a coefficient
# of 0.012 on ``context_depth_score`` means "each additional
# context-score point is associated with a 1.2 percentage point
# increase in probability of resolution, holding everything else
# constant". We multiply by 100 in the output (×100) so the column
# reads as "probability points" — much more intuitive for a non-
# statistician audience than "log-odds" or raw OLS coefficients.
```

## Reading `coef * 100` as "probability points"

The interpretation hinges on the outcome being literally 0 or 1. When
the regression equation reads

    resolved_int = b0 + b_context * context_depth_score + ...

a one-unit change in `context_depth_score` is associated with a change
of `b_context` in `resolved_int`. Since `resolved_int` is in `[0, 1]`,
that change is a change in *probability*. Multiplying by 100 converts
to **percentage points** (often called "probability points" to avoid
confusion with percent change).

Look at the coefficient extraction in
[scripts/insight_layer.py:1021-1034](../../scripts/insight_layer.py):

```python
wanted = ["context_depth_score", "evidence_element_count", "urgency_signal"]
rows = []
for term in wanted:
    rows.append(
        {
            "term": term,
            "coef_probability_points": round(float(fit.params.get(term, np.nan)) * 100, 3),
            "p_value": round(float(fit.pvalues.get(term, np.nan)), 6),
            "conf_low_pp": round(float(fit.conf_int().loc[term, 0]) * 100, 3) if term in fit.params.index else np.nan,
            "conf_high_pp": round(float(fit.conf_int().loc[term, 1]) * 100, 3) if term in fit.params.index else np.nan,
            "model_r2": round(float(fit.rsquared), 4),
            "interpretation": "Linear probability model for resolved status; controls for category, kind, role, month, primary desire. This is correlation, not causal proof.",
        }
    )
```

`fit.params[term] * 100` converts the raw OLS coefficient to
probability points. `fit.conf_int()` returns the 95% confidence
interval matrix; we pull both bounds and convert each to probability
points. Only three terms are reported by name — the three continuous
predictors. The categorical fixed effects are nuisance parameters; they
are in the model to absorb confounders, not to be interpreted on their
own.

## The three real coefficients

[`context_value_model.csv`](../../outputs/option2_20260502_150055/context_value_model.csv):

```
term,coef_probability_points,p_value,conf_low_pp,conf_high_pp,model_r2
context_depth_score,0.153,0.241372,-0.103,0.409,0.1609
evidence_element_count,-2.073,0.17194,-5.048,0.901,0.1609
urgency_signal,0.813,0.25537,-0.588,2.214,0.1609
```

Read each one carefully.

`context_depth_score: 0.153 pp, p = 0.24, CI [-0.10, +0.41]`. The
point estimate says: each additional context-depth-score point is
associated with a 0.153 percentage-point increase in the probability
of resolution, after controlling for category, kind, role, month, and
primary desire. The 95% confidence interval includes zero. The
p-value of 0.24 means we cannot reject the null hypothesis that the
true coefficient is zero. **This effect is not statistically
distinguishable from zero in our data.**

`evidence_element_count: -2.073 pp, p = 0.17, CI [-5.05, +0.90]`. The
point estimate is *negative*: each additional evidence element is
associated with a 2.07 pp *decrease* in the probability of resolution.
That sounds wrong, but the CI is wide and includes zero, p = 0.17.
You cannot say evidence count hurts; you can only say that conditional
on the controls already in the model, this regression does not detect
a positive effect.

`urgency_signal: 0.813 pp, p = 0.26, CI [-0.59, +2.21]`. Each
additional urgency word ("please", "urgent", "asap") is associated with
a 0.81 pp lift, p = 0.26. Not significant.

## What "not significant" honestly means

It does not mean the effect is zero. It does not mean writing more
context is useless. It means **this particular regression, with these
particular controls, on these particular 6,728 tickets, cannot
distinguish the true effect from zero**.

Several alternative readings are all consistent with the data:

- The true effect is zero. Writing more context genuinely doesn't
  change the resolution probability after you already know the
  category, kind, role, month, and primary desire.
- The true effect is small but positive (say, 0.1 pp). The regression
  does not have enough power at this sample size to detect such a
  small effect, and the CI ends up including zero.
- The true effect is heterogeneous — context helps for some kinds of
  tickets and hurts for others — and it averages to near zero across
  the corpus. The regression, which fits a single coefficient
  averaged across all tickets, cannot pick up that pattern.
- The controls absorb most of the variation that "more context"
  would otherwise explain. If managers who write more context also
  handle categories that resolve better, `C(category)` already
  captures that and there's nothing left for `context_depth_score` to
  add.

The fourth reading is the most likely. The fixed effects are doing
real work. Without `C(category)`, the raw correlation between
`context_depth_score` and `resolved_int` is positive and significant.
Conditioning on category absorbs nearly all of it.

That is the **honest** finding the pipeline reports. The interpretation
column reads, verbatim:

> Linear probability model for resolved status; controls for category,
> kind, role, month, primary desire. This is correlation, not causal
> proof.

You should propagate that caveat to anyone you show the table to.

## Why R² = 0.16 here vs 0.36 in the manager model

Lesson 01 had R² = 0.36 for the manager-context regression. This LPM
has R² = 0.16. Same dataset, same fixed-effect set (mostly), different
outcome.

The difference is the outcome's variance. `context_depth_score` ranges
0-100 with a wide spread; there is a lot of variance to explain.
`resolved_int` is 0 or 1 with mean 0.805 (80.5% of tickets are
resolved). Its variance is `0.805 * 0.195 ≈ 0.157`. There is much less
total variance in the binary outcome to begin with, so explaining "a
lot" of it is mathematically harder. R² of 0.16 on a binary outcome
is roughly comparable to R² of 0.36 on a continuous one.

You should not compare R² across outcomes naively. A low R² on a
binary outcome can still represent a useful model.

## Heteroskedasticity is even worse for binary outcomes

Lesson 02 explained why HC3 is needed. For binary outcomes the
argument is even stronger. The variance of a Bernoulli outcome is
literally `p(1 - p)`, where `p` is the predicted probability. As `p`
moves from 0.5 toward 0 or 1, the variance shrinks; as it moves
toward 0.5, the variance grows. There is no way to design a binary-
outcome regression where homoskedasticity holds.

This is exactly why
[scripts/insight_layer.py:975-982](../../scripts/insight_layer.py)
emphasises HC3:

```python
# HC3 robust standard errors: ``cov_type="HC3"`` swaps the default
# OLS standard errors (which assume homoskedasticity — equal error
# variance across observations) for the Davidson-MacKinnon HC3
# sandwich estimator. The classic OLS SE is wrong when error
# variance depends on X — and on a binary outcome it always does
# (variance is ``p(1-p)`` which depends on predicted ``p``). HC3
# is the standard small-sample-friendly heteroskedasticity-robust
# choice, slightly more conservative than HC0/HC1/HC2.
```

If you fit this regression without `cov_type="HC3"` the p-values would
be misleadingly small. HC3 buys you valid inference.

## Why we report only three terms, not the fixed effects

The fixed-effect coefficients exist in `fit.params`. You can read them
out if you want — there are dozens of them, one per non-baseline
level for each of the five categorical regressors. The pipeline
*deliberately* drops them from the output table.

[scripts/insight_layer.py:990-995](../../scripts/insight_layer.py):

```python
# Why we report only three terms: the categorical fixed effects are
# controls — we include them so the continuous coefficients on
# ``context_depth_score``, ``evidence_element_count``, and
# ``urgency_signal`` are estimated *holding category, kind, role,
# month, and desire constant*. We don't need to interpret them
# individually; they are nuisance parameters that absorb confounders.
```

The fixed effects are doing their job by being in the model. Listing
their coefficients in the report would invite readers to overinterpret
them. "Look, `C(category)[T.账号 Account]` is +5 percentage points!"
That number is the partial association of "category is account" with
resolution probability after every other control is in the model — a
quantity that is genuinely meaningful but not the question we are
asking. We are asking about context, evidence, and urgency. Stick to
those three.

## When to use logit instead

Use logit when you have few categorical regressors with no separation
risk, you need per-row predicted probabilities constrained to `(0, 1)`,
or you are willing to interpret coefficients as log-odds. Use the LPM
when you have many high-cardinality categoricals and separation is a
practical risk, you only need average marginal effects, and robust SEs
are available. The pipeline's situation matches the LPM checklist
exactly.

## Try it

Save as `try_linear_probability.py`:

```python
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf

ROOT = "outputs/option2_20260502_150055"
df = pd.read_csv(f"{ROOT}/enriched_tickets.csv", low_memory=False)

m = df.copy()
m["resolved_int"] = (~m["is_unresolved"]).astype(int)
for c in ["category", "question_kind", "role", "month", "primary_desire"]:
    m[c] = m[c].fillna("Unknown").astype(str).replace("", "Unknown")

formula = ("resolved_int ~ context_depth_score + evidence_element_count "
           "+ urgency_signal + C(category) + C(question_kind) + C(role) "
           "+ C(month) + C(primary_desire)")

fit = smf.ols(formula, data=m).fit(cov_type="HC3")

print(f"R^2:        {fit.rsquared:.4f}")
print(f"N obs:      {int(fit.nobs)}")
print(f"Mean y:     {m['resolved_int'].mean():.4f}")
print()
print(f"{'term':<30s} {'pp':>10s}  {'p':>8s}  {'CI95 (pp)':>20s}")
for t in ["context_depth_score", "evidence_element_count", "urgency_signal"]:
    coef = fit.params[t] * 100
    pval = fit.pvalues[t]
    lo, hi = fit.conf_int().loc[t] * 100
    print(f"{t:<30s} {coef:+10.3f}  {pval:8.4f}  [{lo:+7.3f}, {hi:+7.3f}]")

# Look for separation hints
preds = fit.predict(m)
print()
print(f"Predictions outside [0,1]: {((preds < 0) | (preds > 1)).sum()} of {len(preds)}")
print(f"Min pred:  {preds.min():.4f}")
print(f"Max pred:  {preds.max():.4f}")
```

Expected output:
- R² of about 0.16, N = 6728.
- The three coefficients match
  [`context_value_model.csv`](../../outputs/option2_20260502_150055/context_value_model.csv)
  to three decimals.
- A nonzero count of predictions outside `[0, 1]`. That is the LPM
  artefact: the model is happily extrapolating beyond the unit
  interval for some rows. As long as you only interpret coefficients,
  this is fine.

If you want a comparison: try `smf.logit(formula, data=m).fit()` and
watch what happens. On 6,728 rows with this many categorical levels
the optimiser will throw `ConvergenceWarning` and several columns of
the parameter vector will be flagged as "perfectly predicted". That
is the exact failure the pipeline avoids by sticking to the LPM.

The next lesson moves from regression to a much simpler test — the
two-proportion z-test that the opportunity backlog uses to detect
genuine recent surges in cluster volume.
