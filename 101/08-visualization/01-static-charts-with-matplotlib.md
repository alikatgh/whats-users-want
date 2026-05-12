# 01 — Static charts with matplotlib

## What problem does this solve

You have a finished analysis. Now you need to put a chart in a README, paste
one into a Slack message, drop one into an executive deck, or attach one to a
weekly email. Interactive charts can't do any of that — they need a browser
and a server. You want a **flat PNG** that survives screenshots and printers.

That is what matplotlib is for.

In this codebase the pipeline emits three such PNGs after every full run:

- `manager_context_depth.png` — bar chart, average evidence score per manager.
- `desire_trends.png` — line chart, monthly ticket counts per top-8 desire.
- `context_depth_vs_outcome.png` — boxplot, evidence score by band, split by
  resolved/unresolved.

They live alongside the Excel and CSV outputs in
`outputs/option2_<timestamp>/`. They are baked once during the pipeline run
and from then on they are immutable artefacts of that run.

## What's actually happening

Matplotlib is the original Python plotting library. It draws into a *figure*,
which is a canvas with axes; you add elements (bars, lines, points) to the
axes, and finally you save the figure to disk.

Seaborn is a thin layer on top of matplotlib. It does two things: it ships
opinionated defaults that look better than raw matplotlib, and it adds
high-level functions that take a DataFrame plus column names and produce a
chart in one call (`sns.barplot(data=df, x=..., y=...)` instead of building a
matplotlib bar chart from scratch).

Both libraries are *non-interactive*. The output is a PNG (or SVG, or PDF).

## The code in this codebase

Every static chart in the project lives in [scripts/option2_pipeline.py:530-569](../../scripts/option2_pipeline.py).

```python
def create_charts(df: pd.DataFrame, manager_summary: pd.DataFrame, out_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns
    except Exception as exc:
        print(f"[warn] matplotlib/seaborn unavailable: {exc}", file=sys.stderr)
        return

    sns.set_theme(style="whitegrid", font_scale=0.95)
    plt.figure(figsize=(10, 5))
    order = manager_summary.sort_values("avg_context_score", ascending=False)["manager"]
    sns.barplot(data=manager_summary, x="avg_context_score", y="manager", order=order, color="#2E6F95")
    plt.title("Average context depth score by manager")
    plt.xlabel("Context depth score")
    plt.ylabel("")
    plt.tight_layout()
    plt.savefig(out_dir / "manager_context_depth.png", dpi=180)
    plt.close()
```

That single block is the entire matplotlib lesson. Walk it line by line:

1. **Lazy import inside a try.** Matplotlib is a soft dependency — if the
   environment doesn't have it, the function emits a warning and returns
   instead of crashing. This is the same `optional_import` pattern from
   [Module 01 — Error handling](../01-python-foundations/05-error-handling-and-soft-fail.md).

2. **`sns.set_theme(style="whitegrid", font_scale=0.95)`** picks the default
   look for every chart in this run. The `whitegrid` background gives the
   chart light gridlines that help readers compare values. `font_scale=0.95`
   shrinks every text element by 5%, which makes a chart that has to fit in
   an Excel cell or a PowerPoint slide more legible.

3. **`plt.figure(figsize=(10, 5))`** creates a new canvas 10 inches wide
   by 5 inches tall. Width matters more than height for bar charts of
   ~10 managers; the canvas is wider than tall so the bars are readable.

4. **`order = manager_summary.sort_values(...)["manager"]`** computes the
   *display* order of the y-axis. Without this, seaborn would order managers
   alphabetically. We want the highest-scoring manager at the top, so we
   sort the summary DataFrame and pass the resulting Series of manager names
   to `order=`.

5. **`sns.barplot(data=..., x=..., y=..., order=..., color="#2E6F95")`** is
   the high-level seaborn call. `data=manager_summary` is the DataFrame.
   `x="avg_context_score"` is the value axis. `y="manager"` is the
   categorical axis. The fact that `x` is numeric and `y` is categorical
   tells seaborn to draw horizontal bars. `color="#2E6F95"` overrides
   seaborn's palette with a single muted blue — important when you don't
   want the chart to look like a pie chart of rainbows.

6. **`plt.title(...)`, `plt.xlabel(...)`, `plt.ylabel("")`** set chart
   labels. Setting `ylabel=""` hides the y-axis title because the manager
   names are self-explanatory.

7. **`plt.tight_layout()`** tells matplotlib to recompute the margins so
   nothing gets clipped. If you don't call this, long manager names can
   spill outside the canvas.

8. **`plt.savefig(out_dir / "manager_context_depth.png", dpi=180)`** writes
   the PNG. `dpi=180` is roughly twice the default; the result is sharp
   enough for retina screens and big enough for slides without being huge
   on disk.

9. **`plt.close()`** releases the figure. If you skip this, every figure
   you create stays in memory; for a long-running script that draws dozens
   of charts you'd OOM eventually.

The next two charts in the same function follow the identical pattern:

```python
plt.figure(figsize=(12, 6))
monthly = df.groupby(["month", "primary_desire"]).size().reset_index(name="tickets")
top_desires = df["primary_desire"].value_counts().head(8).index
monthly = monthly[monthly["primary_desire"].isin(top_desires)]
sns.lineplot(data=monthly, x="month", y="tickets", hue="primary_desire", marker="o")
plt.xticks(rotation=45, ha="right")
plt.title("User desire trends over time")
plt.xlabel("Month")
plt.ylabel("Tickets")
plt.tight_layout()
plt.savefig(out_dir / "desire_trends.png", dpi=180)
plt.close()
```

Here the new pieces are:

- **`groupby([...]).size().reset_index(name="tickets")`** — the same
  pattern from [Module 02 — groupby](../02-data-with-pandas/04-groupby-and-aggregations.md).
  We get one row per (month, desire) pair with a count column.
- **`hue="primary_desire"`** — a third dimension on a 2D chart. seaborn
  draws one line per unique value of the hue column, in the legend it
  uses different colors. This is the standard "small multiples on one
  chart" trick.
- **`plt.xticks(rotation=45, ha="right")`** — tilt the month labels 45
  degrees so they don't overlap. `ha="right"` (horizontal alignment)
  places them flush right under each tick.

And the boxplot:

```python
plt.figure(figsize=(10, 6))
sns.boxplot(data=df, x="context_depth_band", y="context_depth_score", hue="is_unresolved")
plt.title("Context depth distribution and unresolved outcome")
plt.xlabel("Context depth band")
plt.ylabel("Context depth score")
plt.tight_layout()
plt.savefig(out_dir / "context_depth_vs_outcome.png", dpi=180)
plt.close()
```

`sns.boxplot` shows the median, the inter-quartile range, and outliers as
dots. With `hue="is_unresolved"` you get two side-by-side boxes per band
— resolved on one side, unresolved on the other. This is the chart the
team uses to confirm that there isn't a strong relationship between
evidence score and resolution (matching the formal regression result from
[module 05 lesson 03](../05-statistics/03-linear-probability-model.md)).

## Why we chose this approach

We picked matplotlib for the pipeline-time PNGs and Plotly for the
dashboard for one reason: **readers don't always have a browser**. The
manager who reads a weekly email about manager context residuals isn't
opening a Streamlit dashboard. They open the email, see the PNG, and
move on. PNGs survive copy-paste, print, screenshot, and re-share.

Plotly charts produce HTML files (and inline iframes inside Streamlit).
Try to attach one to an email — it doesn't render. Try to print one —
you get the JS console output. Both libraries have a place; static beats
interactive when the consumer is offline.

## Try it

Open a fresh Python shell and reproduce one of the charts manually:

```bash
.venv/bin/python -c "
import pandas as pd, matplotlib.pyplot as plt, seaborn as sns
df = pd.read_csv('outputs/option2_20260502_150055/manager_context_quality.csv')
sns.set_theme(style='whitegrid')
plt.figure(figsize=(10, 5))
order = df.sort_values('avg_context_score', ascending=False)['manager']
sns.barplot(data=df, x='avg_context_score', y='manager', order=order, color='#2E6F95')
plt.tight_layout()
plt.savefig('/tmp/test_chart.png', dpi=180)
plt.close()
print('wrote /tmp/test_chart.png')
"
open /tmp/test_chart.png
```

Now change `color="#2E6F95"` to `palette="viridis"` and re-run. Notice
that seaborn picks one color per bar from the viridis colormap — useful
when you have many categories, distracting when you have only ten.
