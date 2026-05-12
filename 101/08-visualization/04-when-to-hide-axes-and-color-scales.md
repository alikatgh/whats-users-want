# 04 — When to hide axes and which color scale to pick

## What problem does this solve

Two common ways charts mislead viewers:

1. The X / Y axis numbers shown on the chart are **arbitrary** —
   they're coordinates from a math projection that don't map to real
   world quantities. Showing them invites the viewer to read meaning
   that isn't there.
2. The color scale runs **the wrong way**. A diverging scale used for
   strictly-positive data wastes half its range; a sequential scale
   used for signed data hides whether a value is positive or negative.

Both have specific fixes in this codebase. This lesson covers the
mechanics.

## Hiding axis numbers when they don't mean anything

The Ticket Map page draws a 2D scatter of every ticket using UMAP
coordinates. UMAP tries to preserve which points are *near* which other
points; the absolute X and Y values it produces have no real-world
interpretation. Two points at (3.2, -1.7) and (3.4, -1.5) are close to
each other; the values themselves are meaningless.

The first version of the page showed the default Plotly axis ticks. A
viewer would naturally read the numbers and think they meant something.
The fix is to hide them entirely.

[scripts/dashboard/pages/06_Ticket_Map.py](../../scripts/dashboard/pages/06_Ticket_Map.py):

```python
fig = px.scatter(
    plot_df,
    x="x",
    y="y",
    color=color_col,
    hover_data=hover_data,
    height=720,
    opacity=0.7,
    render_mode="webgl",
)
fig.update_layout(
    margin=dict(l=10, r=10, t=10, b=10),
    legend_title_text=color_label,
    xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, title=""),
    yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, title=""),
)
```

Four flags clear the axis decoration:

- **`showticklabels=False`** removes the numbers along the axis.
- **`showgrid=False`** removes the gridlines that go across the chart.
  Gridlines are signposts the viewer uses to estimate values; with no
  meaningful values to estimate, the gridlines are visual noise.
- **`zeroline=False`** removes the bold line drawn through axis value
  zero. UMAP's "zero" is wherever the algorithm landed, not a meaningful
  origin.
- **`title=""`** removes the axis title. A label like "x" tells the
  viewer nothing they don't already know.

Pair this with a caption *explaining* what proximity means:

```python
st.caption(
    "How to read this: each dot is one ticket. Close-together dots are "
    "tickets about similar things. The X/Y axis numbers themselves are "
    "not meaningful — they are just a layout the algorithm chose."
)
```

The caption does what the axis ticks would have done if the values had
meaning.

This pattern applies to every projection-based chart you'll ever draw —
PCA, t-SNE, MDS, any UMAP variant. The numbers are arbitrary; hide them
and explain proximity in words.

## Sequential vs diverging color scales

A color scale converts a numeric value into a color. There are three
families:

- **Sequential** scales go from light to dark in one direction. Used
  when zero is the meaningful baseline and bigger means more.
- **Diverging** scales go from one strong color through a neutral middle
  to another strong color. Used when zero is the meaningful midpoint and
  the sign of the value matters.
- **Categorical** (qualitative) scales use distinct hues with no
  ordering. Used for nominal categories.

The dashboard picks based on what each chart's color column actually
represents.

### Sequential: "Blues" for counts

[scripts/dashboard/pages/02_What_Users_Want.py](../../scripts/dashboard/pages/02_What_Users_Want.py)
heatmap of want × emotion:

```python
fig = px.imshow(
    ct.values,
    x=ct.columns,
    y=ct.index,
    aspect="auto",
    color_continuous_scale="Blues",
    text_auto=True,
)
```

The cell value is a count of tickets. The minimum is zero; bigger is
more interesting. Light blue = few; dark blue = many. There's no
meaningful "negative" — you can't have negative tickets in a cell.

Reds, Greens, Greys, Viridis, and YlOrRd are also sequential. Pick the
hue based on context: blue for neutral counts, red for risk, green for
positive (when there's no negative side).

### Diverging: "RdBu" for signed deltas

[scripts/dashboard/pages/04_Manager_Note_Quality.py](../../scripts/dashboard/pages/04_Manager_Note_Quality.py)
shows the OLS-adjusted delta vs the benchmark manager. That delta can
be **positive** (the manager writes richer notes than benchmark) or
**negative** (less rich):

```python
fig = px.bar(
    adjusted.sort_values("adjusted_context_delta_vs_baseline"),
    x="adjusted_context_delta_vs_baseline",
    y="manager",
    orientation="h",
    color="adjusted_context_delta_vs_baseline",
    color_continuous_scale="RdBu",
    color_continuous_midpoint=0,
    height=max(360, 28 * len(adjusted)),
    labels={"adjusted_context_delta_vs_baseline": "Gap vs benchmark", "manager": "Manager"},
)
```

Two flags work together:

- **`color_continuous_scale="RdBu"`** — red on one end, blue on the
  other, white in the middle.
- **`color_continuous_midpoint=0`** — pin the white midpoint to value
  zero. Without this, Plotly auto-scales the midpoint to the data's
  median, which would produce a chart where "white" means "average for
  the team" instead of "no difference." For a delta vs baseline, the
  meaningful zero is **literal zero**, and we tell Plotly so.

After this, every red bar is below the benchmark and every blue bar is
above. White bars are right at parity. The viewer doesn't have to read
numbers to see the story.

The same pattern is used for the non-parametric residual chart on the
same page. Same colors, same midpoint, same intent.

### When to skip color encoding entirely

If a chart has only one variable, color is decoration. The
`manager_context_depth.png` matplotlib chart from lesson 01 uses a
single muted blue (`color="#2E6F95"`) — no scale. A single-color bar
chart of ten managers is more readable than a rainbow palette.

The rule: **color encodes a variable**. If you don't have a variable
to encode, don't have a color scale.

## Three combinations, four lessons

| What you're showing | Hide axes? | Color scale | Example in repo |
|---|---|---|---|
| UMAP / projection scatter | yes | discrete (categorical) | [pages/06_Ticket_Map.py](../../scripts/dashboard/pages/06_Ticket_Map.py) |
| Counts in a 2D table | no | sequential (Blues) | [pages/02_What_Users_Want.py](../../scripts/dashboard/pages/02_What_Users_Want.py) tab 1 |
| Risk in a 2D table | no | sequential (Reds) | [pages/02_What_Users_Want.py](../../scripts/dashboard/pages/02_What_Users_Want.py) tab 2 |
| Signed delta vs baseline | no | diverging (RdBu, midpoint=0) | [pages/04_Manager_Note_Quality.py](../../scripts/dashboard/pages/04_Manager_Note_Quality.py) |

The lesson buried in the table: **let the data shape pick the chart, and
let the chart pick the colors**. Axis ticks track meaningful values;
sequential goes from zero to "more"; diverging goes from "less" through
zero to "more"; categorical encodes named groups.

## Try it

Open the Manager Note Quality page in the dashboard. Find the OLS-adjusted
delta chart. Note that Albert is at zero (he is the baseline), every
other manager is left of zero, and the chart's colors confirm this
visually before you read the numbers.

Now in a Python shell, render a deliberately bad version that uses a
sequential scale on signed data:

```bash
.venv/bin/python -c "
import pandas as pd, plotly.express as px
df = pd.read_csv('outputs/option2_20260502_150055/adjusted_manager_context_model.csv')
fig = px.bar(df, x='adjusted_context_delta_vs_baseline', y='manager',
             orientation='h', color='adjusted_context_delta_vs_baseline',
             color_continuous_scale='Blues')
fig.write_html('/tmp/bad.html')
"
open /tmp/bad.html
```

The chart is wrong: Albert (delta=0) is the lightest blue and Aziz
(delta=-16.4) is the darkest. The viewer would assume Aziz is "the
most" of something, not "the most below baseline."

Now redraw the right way:

```bash
.venv/bin/python -c "
import pandas as pd, plotly.express as px
df = pd.read_csv('outputs/option2_20260502_150055/adjusted_manager_context_model.csv')
fig = px.bar(df.sort_values('adjusted_context_delta_vs_baseline'),
             x='adjusted_context_delta_vs_baseline', y='manager',
             orientation='h', color='adjusted_context_delta_vs_baseline',
             color_continuous_scale='RdBu', color_continuous_midpoint=0)
fig.write_html('/tmp/good.html')
"
open /tmp/good.html
```

White at zero, red below, blue above. The chart now tells the truth
about the data without anyone having to read numbers.
