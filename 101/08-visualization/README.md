# 08 — Visualization

## Prerequisites

Modules [01-07](../README.md). You need pandas, you need to know what a
DataFrame is, and you need to have seen the cluster outputs from module 04.

## What you can do after

- Read every chart in this codebase and explain why it was built that way.
- Decide between matplotlib (static PNG) and Plotly (interactive HTML) by use case.
- Build heatmaps from `pd.crosstab` outputs.
- Hide axis numbers when they would mislead viewers.
- Pick the right color scale for risk, count, or signed delta data.

## Lessons

| # | File | What it covers |
|---|---|---|
| 01 | [01-static-charts-with-matplotlib.md](01-static-charts-with-matplotlib.md) | The three PNGs the pipeline emits, seaborn themes, save/close pattern |
| 02 | [02-interactive-charts-with-plotly.md](02-interactive-charts-with-plotly.md) | Plotly Express for the dashboard, scatter / bar / histogram / box |
| 03 | [03-heatmaps-and-crosstabs.md](03-heatmaps-and-crosstabs.md) | `pd.crosstab` → `px.imshow` for two-dimensional summaries |
| 04 | [04-when-to-hide-axes-and-color-scales.md](04-when-to-hide-axes-and-color-scales.md) | Hide UMAP coordinates; sequential vs diverging color scales |

What's next: [Module 09 — Streamlit dashboards](../09-streamlit-dashboards/README.md).
