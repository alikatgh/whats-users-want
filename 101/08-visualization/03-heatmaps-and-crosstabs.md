# 03 — Heatmaps and crosstabs

## What problem does this solve

You have two categorical variables — say, `want_label` and `user_emotion` —
and you want to see how they relate. A bar chart can show one categorical
distribution. Two stacked bars can show one nested in the other but only
clumsily. The right shape for *"how many tickets fall into every (want,
emotion) cell?"* is a 2D table where rows are wants, columns are emotions,
and each cell is a count.

That table is a **crosstab**. Rendered as a colored grid, it's a **heatmap**.
The dashboard uses heatmaps anywhere a 2D summary makes the relationship
obvious at a glance.

## What's actually happening

Pandas builds the crosstab. Plotly draws the heatmap. The pipeline is:

1. `pd.crosstab(rows_series, cols_series)` returns a DataFrame whose rows
   are unique values of the first argument, columns are unique values of
   the second, and cell values are the count of co-occurrences.
2. Pass `.values` (a 2D NumPy array) plus row/column labels to
   `px.imshow`. That's it.

The reason this two-step works is a happy accident of API design.
`pd.crosstab` returns *exactly* the shape `px.imshow` expects.

## The code in this codebase

[scripts/dashboard/pages/02_What_Users_Want.py](../../scripts/dashboard/pages/02_What_Users_Want.py)
renders three heatmaps in three tabs (want × emotion, want × money_risk,
want × manager). The pattern is the same for all three:

```python
with tab1:
    if "user_emotion" in filtered.columns:
        ct = pd.crosstab(filtered[heat_y_col], filtered["user_emotion"])
        fig = px.imshow(
            ct.values,
            x=ct.columns,
            y=ct.index,
            aspect="auto",
            color_continuous_scale="Blues",
            text_auto=True,
            height=max(360, 22 * len(ct)),
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Emotion", yaxis_title="Want")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(ct, use_container_width=True)
```

Walk it line by line:

1. **`pd.crosstab(filtered[heat_y_col], filtered["user_emotion"])`** —
   `heat_y_col` is either `"want_title"` (friendly Gemma label) or
   `"want_label"` (raw token id), determined earlier in the page. The
   first argument becomes rows; the second becomes columns. The result
   is a DataFrame indexed by want and column-named by emotion, with
   counts as values. Rows that have nothing in common with any column
   value get zero in every cell.

2. **`px.imshow(ct.values, x=ct.columns, y=ct.index, ...)`** — `imshow`
   means "image show". It renders a 2D matrix as a colored grid. We pass
   the underlying NumPy array (`.values`) plus the row labels (`y=`) and
   column labels (`x=`) separately, because `imshow` is designed for
   image data where you have an array and metadata about its axes.

3. **`aspect="auto"`** — let cells stretch to fill the figure. The
   default `aspect="equal"` makes every cell a square; for a wide-screen
   dashboard with 17 wants × 9 emotions, square cells leave huge empty
   margins on the sides.

4. **`color_continuous_scale="Blues"`** — sequential color scale. The
   higher the count in a cell, the darker the blue. Sequential scales are
   the right choice when zero is the meaningful baseline. Lesson 04
   covers when to use a different scale.

5. **`text_auto=True`** — overlay the count value on top of every cell.
   Without this, the user can see *which* cell is darker but can't tell
   if the dark cell is 5 or 50. With text labels, the heatmap doubles as
   a crosstab table you can read.

6. **`height=max(360, 22 * len(ct))`** — adaptive height. Same idea as
   the bar chart: reserve ~22 pixels per row with a 360-pixel floor.

7. **`fig.update_layout(margin=..., xaxis_title="Emotion", yaxis_title="Want")`**
   — set axis titles on the figure object after creating it. You could
   pass `labels={...}` to `px.imshow` directly, but `update_layout` is
   the more general pattern and what `px.imshow` does internally anyway.

8. **`st.plotly_chart(fig, use_container_width=True)`** then
   **`st.dataframe(ct, use_container_width=True)`** — show the heatmap
   AND the underlying crosstab table. Some users want to skim colors;
   others want to copy exact numbers. Showing both costs nothing.

The next two tabs in the same page change only the column input and the
color scale:

```python
with tab2:
    if "money_risk_level" in filtered.columns:
        ct = pd.crosstab(filtered[heat_y_col], filtered["money_risk_level"].astype(int))
        fig = px.imshow(
            ct.values,
            x=[f"Risk {c}" for c in ct.columns],
            y=ct.index,
            aspect="auto",
            color_continuous_scale="Reds",
            text_auto=True,
            height=max(360, 22 * len(ct)),
        )
```

Two things changed:

- **`color_continuous_scale="Reds"`** — money risk is a thing to be
  alarmed by, so the dark end of the scale is red instead of blue.
  Pure cosmetic; same shape underneath.
- **`x=[f"Risk {c}" for c in ct.columns]`** — list comprehension to
  rename the column labels at display time. `ct.columns` is `[1, 2, 3,
  4, 5]` (integer risk levels); we want them shown as `"Risk 1"`,
  `"Risk 2"`, etc. on the heatmap. The comprehension is the cleanest
  way to map a list of values to a list of labels without mutating the
  DataFrame.

The third tab uses `color_continuous_scale="Greens"` because manager
distribution is neither alarming nor neutral — green just keeps the three
heatmaps visually distinct.

## Why we chose this approach

Three reasons.

First, **`pd.crosstab` is the right primitive**. It does exactly the
thing you want without intermediate `groupby` + `pivot` choreography. If
you ever find yourself writing `df.groupby(["a", "b"]).size().unstack()`,
you've reinvented `pd.crosstab` and the result is identical.

Second, **`px.imshow` accepts the crosstab shape natively**. There's no
adapter step. If we'd picked a different chart kind — say,
`px.density_heatmap` — we'd have to give it raw rows of (want, emotion)
pairs and let Plotly do the counting. That's slower and harder to debug
when the counts look wrong.

Third, **`text_auto=True` solves the "is dark = 5 or 50?" problem**
without any extra code. Heatmaps without numeric labels are a common UX
mistake: pretty, uninformative.

## A heatmap is not always the right answer

If your two variables have many unique values (say, 200 wants × 50
managers), the cells become so small you can't read them. At that point
switch to:

- A **bar chart per row** (faceted small multiples).
- A **table** (just `st.dataframe(ct)` without the chart).
- A **grouped bar chart** with one dimension as the x-axis and the other
  as `color=`.

The sweet spot for `px.imshow` is around 5-25 rows × 5-25 columns. The
dashboard sticks inside that band.

## Try it

Run a quick crosstab of your own. Open a Python shell:

```bash
.venv/bin/python -c "
import pandas as pd, plotly.express as px
df = pd.read_csv('outputs/option2_20260502_150055/enriched_tickets.csv')
ct = pd.crosstab(df['primary_desire'], df['context_depth_band'])
print(ct)
fig = px.imshow(ct.values, x=ct.columns, y=ct.index,
                aspect='auto', text_auto=True,
                color_continuous_scale='Blues')
fig.write_html('/tmp/heatmap.html')
print('wrote /tmp/heatmap.html')
"
open /tmp/heatmap.html
```

You'll see a 10×4 heatmap of desire × context band. Notice that
`fix_product_or_technical_flow` and `clear_name_or_get_fairness` lean
toward higher evidence bands (rich/forensic) — those are tickets where
managers naturally write more.

Now mutate the crosstab before plotting:

```python
ct_pct = (ct.div(ct.sum(axis=1), axis=0) * 100).round(1)
```

That converts each row to "share of this desire that fell in this band".
Re-render with `text_auto='.0f'` to see percentages instead of counts.
Same shape, different question answered.
