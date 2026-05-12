# 01 — OLS with Fixed Effects

## The problem

Module 04 left you with a `manager_context_quality.csv` that ranks managers
by their average `context_depth_score`. Albert tops the table at 25.29
across 2,247 tickets. Aziz sits at 9.29 across 2,518 tickets. The 16-point
gap looks dramatic. You could walk into a coaching meeting tomorrow and
say "Albert documents three times as deeply as Aziz, on average".

You should not.

The first reaction of any honest reader is *"yes, but they handle different
work."* If Albert is mostly assigned to forensic ban appeals (long, rich
tickets by nature) and Aziz to quick technical resets ("can't log in" with
no extra information), then the 16-point gap reflects ticket assignment, not
writing quality. The raw average is descriptive but it is not *attribution*.
You cannot use it to coach individual managers without first answering the
question: given the same kind of case, who writes more context?

That is what
[`adjusted_manager_context`](../../scripts/option2_pipeline.py) does.
It fits a single OLS regression with manager dummies *and* fixed effects
for the four big confounders — category, question kind, user role,
resolution status, calendar month — and reports the per-manager
coefficient as "delta vs the baseline manager after controlling for
everything else". The output is
[`adjusted_manager_context_model.csv`](../../outputs/option2_20260502_150055/adjusted_manager_context_model.csv),
which is what you should walk into the meeting with.

This lesson is the regression part. The next lesson is the standard
errors. Together they cover everything you need to read and defend
that CSV.

## Linear regression in one paragraph

Ordinary Least Squares (OLS) fits `y = b0 + b1*x1 + b2*x2 + ... + e` by
minimising the sum of squared residuals. The intercept `b0` is the
predicted `y` when every `x` is zero. Each `bi` is the change in `y`
associated with a one-unit change in `xi`, *holding the other x's
constant*. That last clause is what "controlling for" means — the
coefficient on `x1` is read as "the partial relationship between `x1`
and `y` after the other regressors absorb their share of the variance".

For continuous predictors that interpretation is direct. For
categorical predictors (like `manager`, which takes values "Albert",
"Aziz", "Danila", ...) you cannot just plug the string into a regression.
You need numbers. Patsy's `C(...)` notation does the conversion for you.

## Patsy and the `C(...)` wrapper

The pipeline uses `statsmodels.formula.api.ols`, which accepts a
formula string in the Patsy DSL. Real call from
[scripts/option2_pipeline.py:923-933](../../scripts/option2_pipeline.py):

```python
try:
    import statsmodels.formula.api as smf
except Exception:
    return pd.DataFrame({"note": ["statsmodels unavailable; adjusted model skipped"]})

model_df = df[["context_depth_score", "manager", "category", "question_kind", "role", "status_en", "month"]].copy()
for col in ["manager", "category", "question_kind", "role", "status_en", "month"]:
    model_df[col] = model_df[col].fillna("").replace("", "Unknown")
try:
    fit = smf.ols("context_depth_score ~ C(manager) + C(category) + C(question_kind) + C(role) + C(status_en) + C(month)", data=model_df).fit(cov_type="HC3")
except Exception as exc:
    return pd.DataFrame({"note": [f"adjusted model failed: {exc}"]})
```

Read the formula left to right.

`context_depth_score ~ ...` says "the outcome is `context_depth_score`,
the regressors are everything to the right of the tilde". Both columns
must exist in `model_df`.

`C(manager)` says "treat `manager` as categorical and dummy-encode it
automatically". With 8 distinct managers in the data, `C(manager)`
expands into 7 indicator columns: one per non-baseline manager, taking
value 1 if the row's manager is that one and 0 otherwise. Patsy picks
the baseline alphabetically — "Albert" sorts first, so Albert becomes
the implicit reference. Every other manager gets a column named
`C(manager)[T.<name>]`. The `T.` prefix stands for "treatment contrast",
the default coding scheme.

`+` adds another term to the regression. So
`C(manager) + C(category) + C(question_kind) + C(role) + C(status_en) + C(month)`
asks Patsy to expand all six categorical variables into dummies and
include them all on the right-hand side of the equation.

Why the `for col in ... fillna("").replace("", "Unknown")` loop above?
Patsy refuses to fit when a categorical column has missing values; it
also treats empty strings as a separate level, which is rarely what you
want. The replacement collapses both to a single "Unknown" bucket so
the model is well-defined.

## Fixed effects: what they are and why we want them

A "fixed effect" is a categorical control whose individual coefficients
you do not care about. You include it because you want its associated
variance absorbed before reading the coefficient on the variable you
*do* care about — here, the manager.

The teaching note from
[scripts/option2_pipeline.py:892-899](../../scripts/option2_pipeline.py)
spells this out:

```python
# FIXED EFFECTS.
# ``C(category) + C(question_kind) + C(role) + C(status_en) +
# C(month)`` are fixed effects: we don't care about their individual
# coefficients, but we want them in the model so the residual variance
# in ``context_depth_score`` AFTER they're accounted for is what's
# attributable to the manager. ``C(month)`` controls for time trends
# (rules tightened or templates changed); ``C(role)`` controls for
# user type; ``C(status_en)`` for resolution state.
```

Walk through each one.

`C(category)` is the support category — "解封&封禁 Unblocking & Banning",
"咨询信息 Consulting info", "账号 Account", and so on. Some categories
are inherently chattier. Ban appeals come with timestamps and ban
codes. Account questions come with phone numbers. Without `C(category)`,
a manager who only handles ban appeals would *automatically* score
higher because their work product is naturally longer.

`C(question_kind)` is the question type slug from the canonicalisation
stage. Same logic: a "forensic" question kind has more evidence by
definition than a "general info" one.

`C(role)` is the user role (regular user, SVIP, dealer, ...). SVIP
disputes tend to have more attached identifiers; dealer disputes
involve more money mentions. We control so the manager coefficient
isn't picking up role-mix differences.

`C(status_en)` is the English-translated resolution status (`resolved`,
`pending`, ...). Pending tickets tend to have more notes because the
back-and-forth keeps adding context. Without controlling for status,
a manager whose tickets are all still pending would look richer.

`C(month)` is the calendar month. Templates change. New evidence rules
get rolled out. April 2026 tickets simply *are* longer than September
2025 tickets, on average, because the team's documentation expectations
ratcheted up. Without `C(month)`, a manager who joined in March 2026
would be unfairly compared to one who started in 2025.

After all five fixed effects are in the model, the coefficient on
`C(manager)[T.Aziz]` is the answer to: "holding category, question
kind, user role, status, and month constant, how much higher or lower
is Aziz's `context_depth_score` than Albert's?"

That is the question you actually want to ask.

## Reading the per-manager coefficients

Real output from
[`adjusted_manager_context_model.csv`](../../outputs/option2_20260502_150055/adjusted_manager_context_model.csv):

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

Albert's row shows `0.0` because Albert is the baseline. The model
does not estimate a separate coefficient for the reference level — the
intercept absorbs Albert's effect. Every other delta is read as
"this manager's context score is X points lower (or higher) than
Albert's, after the controls".

Aziz at `-16.399` means: across the same category × question kind ×
role × status × month bucket, Aziz writes about 16.4 fewer
context-depth-score points than Albert. The raw difference (25.29 -
9.29 = 16.0 points) is almost identical to the adjusted delta (16.4
points) because in this dataset the case-mix differences happen to be
small relative to the manager-effort differences. That is *evidence*
the raw average was already roughly correct — but you only know that
after running the adjustment.

Alexander at `-14.23` is `p=0.0`, confidently below Albert. Alexander
the joint pseudo-manager (`"Alexander, Aziz"` — the string assigned
when two managers co-handled a ticket) is at `-8.783` with `p=0.029`,
borderline — meaning the data marginally support a difference but you
should be cautious. We will return to *why* the joint pseudo-manager
has a much smaller delta than either solo Aziz or solo Alexander in
the next lesson on standard errors.

The `model_r2` of `0.3559` says the regression explains 35.59% of the
variance in `context_depth_score`. That is fine, not great. It means
ticket mix and manager identity together account for about a third of
why some tickets are richer than others; the remaining two-thirds is
within-(manager, category, kind, role, status, month) variation —
some tickets are simply richer than others for reasons the model
doesn't see. A 35% R² is normal for ticket-level support data; you
should be suspicious if it were 90%, because that would mean almost
no idiosyncratic variation, which is implausible.

## Reading the coefficient extraction code

The Python that produces the CSV from the fitted model is
[scripts/option2_pipeline.py:937-954](../../scripts/option2_pipeline.py):

```python
rows = []
base_manager = sorted(model_df["manager"].unique())[0]
intercept = fit.params.get("Intercept", 0.0)
for manager in sorted(model_df["manager"].unique()):
    term = f"C(manager)[T.{manager}]"
    coef = 0.0 if manager == base_manager else float(fit.params.get(term, 0.0))
    pval = np.nan if manager == base_manager else float(fit.pvalues.get(term, np.nan))
    rows.append(
        {
            "manager": manager,
            "adjusted_context_delta_vs_baseline": round(coef, 3),
            "baseline_manager": base_manager,
            "p_value": None if np.isnan(pval) else round(pval, 5),
            "model_r2": round(float(fit.rsquared), 4),
            "interpretation": "positive means richer context after controlling for category/kind/role/status/month",
        }
    )
return pd.DataFrame(rows).sort_values("adjusted_context_delta_vs_baseline", ascending=False)
```

`sorted(model_df["manager"].unique())[0]` is the baseline-finder. Sorted
strings put Albert first alphabetically, so Albert is the reference.
The loop builds a row per manager. For the baseline manager, both the
coefficient and p-value are forced to placeholder values (0.0 and
NaN) because the model didn't estimate them. For everyone else,
`fit.params[f"C(manager)[T.{manager}]"]` pulls the coefficient and
`fit.pvalues[f"C(manager)[T.{manager}]"]` pulls the matching p-value.

Note the literal `T.` in the term name. That is Patsy's notation for
treatment contrasts. If you ever look at `fit.params.index`, you will
see entries like `C(manager)[T.Aziz]`, `C(category)[T.账号 Account]`,
`Intercept`, plus the three numeric covariates if the formula included
any.

## Baseline choice is arbitrary but consistent

Albert is the baseline because alphabet. The teaching note in
[scripts/option2_pipeline.py:912-916](../../scripts/option2_pipeline.py)
admits this:

```python
# BASELINE CHOICE.
# ``sorted(unique)[0]`` makes Albert (alphabetically first) the
# reference manager. All deltas are interpreted as "vs Albert". This
# is arbitrary but consistent — flipping the baseline shifts every
# coefficient by a constant but preserves rank-order.
```

If you re-fit the model with Aziz as the baseline, every other
manager's coefficient would shift up by 16.4 (the size of the original
Aziz delta). Albert's coefficient would become `+16.4`, Alexander's
would be `+2.2` (= 16.4 - 14.2), and so on. The rank order is
preserved. Statistical significance is preserved. The story is the
same.

What changes is the *narrative*. With Albert as the baseline, the
story reads "everyone else is below Albert by X". With Aziz as the
baseline, it reads "everyone else is above Aziz by X". The pipeline
picks the alphabetical-first manager so that nobody can accuse you of
choosing a baseline to make a particular manager look good or bad.

## What `model_r2 = 0.3559` does and does not tell you

R² is not a measure of whether your conclusions are right. It is a
measure of how much variance the model explains. A model can have a
high R² and still be missing the variable that actually causes the
outcome. A model can have a low R² and still produce coefficients that
are unbiased estimates of the partial relationships you wanted.

The teaching note from
[scripts/option2_pipeline.py:920-922](../../scripts/option2_pipeline.py):

```python
# ``fit.rsquared`` is the model's R² — fraction of variance
# explained — useful as a sanity check (low R² means the controls
# don't explain much, so deltas should be read carefully).
```

What "deltas should be read carefully" means in practice: if R² were
0.05, the controls are doing almost nothing, and the manager
coefficient is essentially the raw difference with extra steps. The
adjustment is not buying you anything; the residual variance is too
big to attribute to anyone. At R² = 0.36, the controls *are*
absorbing meaningful structure, and the adjusted deltas are different
enough from the raw averages to be worth reporting.

You should always print R² alongside coefficients. A reader who is
shown deltas without R² is being asked to trust the model on faith.

## Try it

Save as `try_ols_fixed_effects.py` in the project root and run with
`python try_ols_fixed_effects.py`.

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

fit = smf.ols(
    "context_depth_score ~ C(manager) + C(category) + C(question_kind) "
    "+ C(role) + C(status_en) + C(month)",
    data=m,
).fit(cov_type="HC3")

print(f"R^2 = {fit.rsquared:.4f}")
print(f"N   = {int(fit.nobs)}")
print()
print("Manager deltas (vs Albert):")
for term in fit.params.index:
    if term.startswith("C(manager)[T."):
        name = term.removeprefix("C(manager)[T.").rstrip("]")
        print(f"  {name:24s} {fit.params[term]:+8.3f}  p={fit.pvalues[term]:.4f}")

# Reproduce the CSV order
adjusted = pd.read_csv(f"{ROOT}/adjusted_manager_context_model.csv")
print("\nFrom CSV:")
print(adjusted.to_string(index=False))
```

Expected: `R^2 = 0.3559`, `N = 6728`, and the printed deltas match the
CSV. If they don't, the most likely cause is a `low_memory=False`
omission causing dtype drift in `month` or `status_en` — those columns
must arrive as strings.

Now ask yourself the next-step question: the deltas are large, but how
do you know they aren't artefacts of the standard-error formula? OLS's
default SEs assume residuals have constant variance. They don't here.
That is the next lesson.
