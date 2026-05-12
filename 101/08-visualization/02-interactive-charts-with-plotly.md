# 02 — Interactive charts with Plotly

## What problem does this solve

Static PNGs lose information. The manager dashboard has 6,728 tickets — if
you draw all of them as dots on a 1,000-pixel-wide chart, neighbouring dots
overlap and you can't tell what's there. With an interactive chart you can
**zoom**, **pan**, **hover for tooltips**, and **filter the legend**. That
gets you signal back. The trade-off is that interactive charts need a
browser to render, so they can't be emailed or printed.

Inside Streamlit (covered in module 09) every chart should be Plotly. Only
fall back to matplotlib when you need a flat PNG artefact you can share
outside the browser.

## What's actually happening

Plotly produces an HTML+JS bundle that knows how to draw itself. Plotly
Express (the `plotly.express` module) is the thin wrapper that takes a
DataFrame plus column names and returns a configured figure object.

A Plotly Express call has three flavours of arguments:

- **Mappings from columns to visual channels:** `x=`, `y=`, `color=`,
  `size=`, `hover_name=`, `hover_data=`. Each one says "use this column as
  this visual property."
- **Modifiers that change the geometry:** `orientation=`, `log_x=`,
  `barmode=`, `nbins=`, `points=`, `render_mode=`. They tweak how marks are
  drawn.
- **Layout adjustments after the fact via `fig.update_layout(...)`:**
  margins, axis titles, legend position, hidden tick labels.

The pattern is always: build the figure with Plotly Express, then mutate
its layout. That separation lets the data-shape decisions stay close to
the data and the cosmetic decisions stay close to the visual.

## The code in this codebase

[scripts/dashboard/pages/03_Opportunities.py](../../scripts/dashboard/pages/03_Opportunities.py)
draws the topic landscape — a bubble chart of impact score vs ticket
count, colored by trust/money risk:

```python
fig = px.scatter(
    plot_df,
    x="Tickets",
    y="Impact score",
    size="Tickets",
    color="Trust / money risk" if "Trust / money risk" in plot_df.columns else None,
    hover_name="Topic" if "Topic" in plot_df.columns else None,
    hover_data={
        c: True
        for c in ["Unresolved share", "Recent vs baseline", "Recommended action"]
        if c in plot_df.columns
    },
    log_x=True,
    height=460,
    color_continuous_scale="Reds",
)
fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig, use_container_width=True)
```

Channels mapped:

- `x="Tickets"` — horizontal position by topic size.
- `y="Impact score"` — vertical position by the composite opportunity score.
- `size="Tickets"` — bubble area also by ticket count, so high-volume topics
  visually dominate.
- `color="Trust / money risk"` — a continuous numeric column drives a
  colorbar; high-risk topics appear redder. (Covered in lesson 04.)
- `hover_name="Topic"` — when the user hovers a bubble, the topic label
  appears bold at the top of the tooltip.
- `hover_data={...}` — extra fields shown in the tooltip body. The dict
  form (`{col: True}`) tells Plotly "include this column"; you can also
  pass `{col: False}` to *exclude* a column that would otherwise appear.

Modifiers:

- `log_x=True` — log-scale the x axis. Topic counts span from 4 to 1,400;
  on a linear scale the small topics are crushed against the axis. Log
  scale stretches them apart so you can see them.
- `height=460` — fixed pixel height. Without this the chart auto-scales
  to its container, which can be too tall on a wide monitor.
- `color_continuous_scale="Reds"` — the named Plotly colorscale.

Layout:

- `fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))` — shrink the
  default margins so the chart uses every pixel of the Streamlit container.

[scripts/dashboard/pages/02_What_Users_Want.py](../../scripts/dashboard/pages/02_What_Users_Want.py)
draws horizontal bars for the want clusters:

```python
fig = px.bar(
    counts_df(counts, "Want", "Tickets"),
    x="Tickets",
    y="Want",
    orientation="h",
    height=max(380, 28 * len(counts)),
)
fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig, use_container_width=True)
```

Two new patterns here:

- **`height=max(380, 28 * len(counts))`** — adaptive height. Hard-coded
  pixel heights make labels overlap when you have many bars. The formula
  reserves ~28 pixels per bar with a 380-pixel floor.
- **`yaxis={"categoryorder": "total ascending"}`** — sort the y axis by
  the bar values. Without this Plotly orders categories alphabetically,
  which buries the largest cluster halfway down.

[scripts/dashboard/pages/05_Repeat_Customers.py](../../scripts/dashboard/pages/05_Repeat_Customers.py)
shows boxplots and histograms:

```python
fig = px.histogram(f, x="tickets", nbins=30, height=240, labels={"tickets": "Tickets per customer"})
fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), yaxis_title="Customers")
st.plotly_chart(fig, use_container_width=True)
```

```python
fig = px.box(
    f,
    x="persona_label",
    y="unresolved_share",
    points="outliers",
    height=320,
    labels={"persona_label": "Profile", "unresolved_share": "Unresolved share"},
)
```

`px.histogram(x="tickets", nbins=30)` bins the tickets-per-customer column
into 30 buckets. `nbins` is a hint, not a guarantee — Plotly will tweak it
slightly to land on round numbers.

`px.box` draws box-and-whisker plots per category. `points="outliers"`
plots only the outlier points instead of every point — important when each
box represents thousands of tickets and overplotting would obscure the
boxes themselves.

The `labels=` dict renames axis titles in the rendered chart without
mutating the underlying DataFrame columns. This keeps internal column
names like `persona_label` clean but shows users `"Profile"`.

## Why we chose this approach

Plotly Express was picked over the lower-level `plotly.graph_objects`
module for one reason: **the express version is one function call**.
A scatter chart in `graph_objects` requires you to construct `Scatter`
traces, set `marker` properties, and append everything to a `Figure`.
In Express, `px.scatter(df, x="a", y="b", color="c")` does the
equivalent in one line.

You give that up when you need fine control: stacked sub-plots, animations
across frames, mixed chart types in one figure. Express handles 90% of
dashboard charts. When you need the other 10%, the figure object that
`px` returns is the same object `graph_objects` produces — you can mutate
it freely. Lesson 04 shows that pattern (hiding axis ticks).

The companion choice was `render_mode="webgl"` for scatter plots with
many points. The default SVG renderer slows to a crawl past ~5,000
points; WebGL handles 50,000+ smoothly. The
[ticket-map page](../../scripts/dashboard/pages/06_Ticket_Map.py) opts
into WebGL because it draws all 6,728 dots.

## Try it

Open the Opportunities page in the dashboard, then in another terminal:

```bash
./scripts/run_dashboard.sh
# wait for "URL: http://localhost:8501"
open http://localhost:8501/Opportunities
```

In the bubble chart:

1. Hover any bubble — the tooltip shows the topic name and four extra
   fields.
2. Click and drag to define a rectangle — Plotly zooms into the
   selected region.
3. Double-click to reset the zoom.
4. Click on any color in the legend to hide the matching bubbles.
5. Click the camera icon in the toolbar to download the current view as
   a PNG. (You can have your interactive chart and your static export
   both — Plotly does the snapshot for you.)

Now in a Python shell, reproduce a Plotly chart standalone:

```bash
.venv/bin/python -c "
import pandas as pd, plotly.express as px
df = pd.read_csv('outputs/option2_20260502_150055/opportunity_backlog.csv')
fig = px.scatter(df.head(50), x='tickets', y='opportunity_score',
                 size='tickets', color='trust_money_risk',
                 hover_name='issue_label', log_x=True,
                 color_continuous_scale='Reds')
fig.write_html('/tmp/opportunity.html')
print('wrote /tmp/opportunity.html')
"
open /tmp/opportunity.html
```

That is the same chart the dashboard renders, served as a standalone HTML
file you can share by email — combining the interactivity of Plotly with
some of the portability of matplotlib.
