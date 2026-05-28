"""Interactive map of all tickets, placed by meaning.

Each dot is one ticket. Tickets that talk about similar things land near each
other, even when written in different languages.

Teaching
--------
This page is a *2-D scatter plot of all 6,728 tickets*. In Stage 1 each
ticket was embedded into a high-dimensional vector and then projected to
two dimensions with UMAP; the (x, y) coordinates live in
``semantic_cluster_assignments.csv``. The whole page is one ``px.scatter``
of those coordinates, decorated with filters and a cluster summary.

* **Crucial intuition: the X and Y numbers are not meaningful.** Only
  *relative position* matters — which dots are close to which. A point at
  (3.2, -1.7) tells you nothing on its own; what matters is "this dot
  sits in the cloud of account-recovery tickets, far from the cloud of
  payment disputes." That's why we hide ticks and axis titles — keeping
  them would invite users to read meaning where there is none.

* **``DESIRE_LABELS`` and ``humanize_desire``.** These come from ``lib``
  and translate snake_case codes (``"recover_access"``) into UI strings
  (``"Recover account access"``). The legend, the filter dropdown, and
  the hover tooltip all use the friendly version; the underlying column
  stays in code form so filtering remains exact.

* **``px.scatter(plot_df, x="x", y="y", color=color_col,
  render_mode="webgl")``.** The default (SVG) renderer slows to a crawl
  past a few thousand points. ``render_mode="webgl"`` switches to
  hardware-accelerated rendering; you can pan and zoom 6,728 dots with
  zero lag. This single argument is the biggest performance win on this
  page.

* **Sample-size slider.** ``sample_n`` lets users draw fewer dots if
  their machine is slow. We use ``f.sample(sample_n, random_state=42)``
  so the same seed produces the same subset across reruns —
  reproducibility on demand.

* **Hiding axis decoration.** The full incantation to wipe an axis is::

      fig.update_layout(
          xaxis=dict(showticklabels=False, showgrid=False,
                     zeroline=False, title=""),
          yaxis=dict(...),
      )

  ``showticklabels=False`` removes the numbers, ``showgrid=False`` removes
  the gridlines, ``zeroline=False`` removes the dark line through 0, and
  ``title=""`` clears the axis label. Use this every time you draw a
  UMAP/t-SNE/PCA plot.

* **``hover_data=[...]`` for tooltips.** Pass a list of column names
  (display names, since we already renamed the DataFrame) and Plotly
  shows them in the tooltip when the user mouses over a point. The page
  prepends the friendly ``"Primary desire"`` so the legend and tooltip
  agree.

* **Coloring by a continuous vs categorical column.** When you pass
  ``color="context_depth_score"`` (numeric), Plotly draws a continuous
  colorbar; when you pass ``color="manager"`` (string), it draws a
  discrete legend. The page lets users flip between these via a
  ``color_options`` dropdown.

* **The cluster summary table.** Below the scatter, ``semantic_clusters.csv``
  is rendered as a table with top words per cluster, average evidence
  score, and an example ticket. This supports drill-down: spot an
  interesting blob on the map, find the matching cluster ID, read the
  example.

* **Standalone HTML link.** If a ``semantic_ticket_map.html`` exists in
  the run directory, the page surfaces a caption linking to it. That HTML
  was produced by the build pipeline as a fully self-contained Plotly
  artefact and can be shared without running the dashboard.

* **Why a map at all?** Cross-tabs and lists answer *which* tickets fall
  into a category; a map answers *which categories are similar*. Account
  recovery and password reset cluster next to each other; commerce
  disputes form their own island. Looking at the map is faster than
  reading any number of summary tables when you're trying to develop
  a mental model of the dataset.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import DESIRE_LABELS, humanize_desire, maybe_load_csv, run_picker

st.title("Ticket map by meaning")
st.caption(
    "Every dot is one support ticket. The X / Y numbers themselves do not have a "
    "meaning — only distance between dots does. Tickets that land near each other "
    "are about similar things, even when written in different languages. Use the "
    "sidebar to filter or change what colors the dots."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

assignments = maybe_load_csv(run_dir, "semantic_cluster_assignments.csv")
clusters = maybe_load_csv(run_dir, "semantic_clusters.csv")

if assignments is None:
    st.warning("`semantic_cluster_assignments.csv` is missing. Re-run Stage 1.")
    st.stop()
if "x" not in assignments.columns or "y" not in assignments.columns:
    st.warning("Map coordinates were not produced for this run.")
    st.stop()

st.caption(f"Showing **{len(assignments):,}** tickets in this run.")

# ---- Filters -------------------------------------------------------------

color_options = {
    "primary_desire": "Primary desire",
    "cluster_id": "Topic cluster",
    "context_depth_score": "Note evidence score",
}
color_options = {k: v for k, v in color_options.items() if k in assignments.columns}

with st.sidebar:
    st.header("Filters")
    if "primary_desire" in assignments.columns:
        desire_codes = sorted(assignments["primary_desire"].fillna("unclear_or_needs_llm").unique())
        desire_label_map = {humanize_desire(d): d for d in desire_codes}
        sel_desire_labels = st.multiselect(
            "Primary desire",
            list(desire_label_map.keys()),
            default=list(desire_label_map.keys()),
        )
        sel_desires = [desire_label_map[label] for label in sel_desire_labels]
    else:
        sel_desires = None
    color_label = st.selectbox("Color dots by", list(color_options.values()))
    color_by = next(k for k, v in color_options.items() if v == color_label)
    n_assignments = len(assignments)
    if n_assignments <= 500:
        st.caption(f"Run is small ({n_assignments} tickets) — showing all of them.")
        sample_n = n_assignments
    else:
        sample_n = st.slider(
            "How many dots to show (smaller = faster)",
            min_value=500,
            max_value=n_assignments,
            value=min(3000, n_assignments),
            step=500,
        )

f = assignments.copy()
if sel_desires is not None and "primary_desire" in f.columns:
    f = f[f["primary_desire"].fillna("unclear_or_needs_llm").isin(sel_desires)]
if "primary_desire" in f.columns:
    f = f.copy()
    f["Primary desire"] = f["primary_desire"].map(humanize_desire)
if len(f) > sample_n:
    f = f.sample(sample_n, random_state=42)

st.metric("Tickets shown on map", f"{len(f):,}")

# ---- Map -----------------------------------------------------------------

hover_rename = {
    "source_row": "Ticket #",
    "category": "Category",
    "primary_desire": "Primary desire (raw)",
    "context_depth_score": "Note evidence score",
}
hover_cols = [c for c in hover_rename.keys() if c in f.columns]
plot_df = f.rename(columns=hover_rename)
hover_data = [hover_rename[c] for c in hover_cols]
if "Primary desire" in plot_df.columns:
    hover_data = ["Primary desire"] + [c for c in hover_data if c != "Primary desire (raw)"]

# When coloring by primary_desire, use the friendly column we mapped above.
color_col = (
    "Primary desire"
    if color_by == "primary_desire" and "Primary desire" in plot_df.columns
    else hover_rename.get(color_by, color_by)
)

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
# X and Y come from a UMAP projection — the numbers themselves are arbitrary;
# only relative position matters. Hide ticks and titles so viewers don't read meaning into them.
fig.update_layout(
    margin=dict(l=10, r=10, t=10, b=10),
    legend_title_text=color_label,
    xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, title=""),
    yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, title=""),
)
st.plotly_chart(fig, width="stretch")
st.caption(
    "How to read this: each dot is one ticket. Close-together dots are tickets about "
    "similar things. The X/Y axis numbers themselves are not meaningful — they are just "
    "a layout the algorithm chose."
)

# ---- Cluster summary ----------------------------------------------------

if clusters is not None:
    st.subheader("Topic clusters")
    rename_map = {
        "cluster_id": "Cluster #",
        "tickets": "Tickets",
        "share": "Share",
        "avg_context_score": "Avg note evidence score",
        "unresolved_share": "Unresolved %",
        "top_terms": "Top terms",
        "top_desires": "Top desires",
        "example_1": "Example ticket",
    }
    keep = [c for c in rename_map.keys() if c in clusters.columns]
    disp = clusters[keep].copy()
    if "share" in disp.columns:
        disp["share"] = (disp["share"] * 100).round(1).astype(str) + "%"
    if "unresolved_share" in disp.columns:
        disp["unresolved_share"] = (disp["unresolved_share"] * 100).round(1).astype(str) + "%"
    st.dataframe(disp.rename(columns=rename_map), width="stretch", hide_index=True, height=420)

# ---- Link to original Plotly HTML --------------------------------------

map_html = run_dir / "semantic_ticket_map.html"
if map_html.exists():
    st.caption(
        f"Standalone HTML version is at `{map_html.relative_to(run_dir.parent.parent)}` "
        f"({map_html.stat().st_size // 1024:,} KB)."
    )
