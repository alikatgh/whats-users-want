# 09 — Streamlit dashboards

## Prerequisites

Modules [01-08](../README.md). Module 02 (pandas), 07 (DuckDB), and 08
(Plotly) are the most directly useful — the dashboard glues those three
together.

## What you can do after

- Build a multi-page Streamlit dashboard from a folder of CSVs.
- Tell `@st.cache_data` apart from `@st.cache_resource` and pick the right
  one.
- Wire sidebar widgets to filter a DataFrame in real time.
- Use `st.session_state` to persist user choices across page navigations.
- Lay out a page with `st.columns`, `st.tabs`, and `st.expander`.
- Auto-refresh a page that watches a long-running file.

## Lessons

| # | File | What it covers |
|---|---|---|
| 01 | [01-streamlit-mental-model.md](01-streamlit-mental-model.md) | Top-to-bottom rerun, `st.session_state`, the loop you don't have to write |
| 02 | [02-multipage-apps.md](02-multipage-apps.md) | The `pages/` folder convention, sidebar nav, naming rules |
| 03 | [03-widgets-and-state.md](03-widgets-and-state.md) | `st.slider`, `st.multiselect`, `st.selectbox`, return-value pattern |
| 04 | [04-caching.md](04-caching.md) | `@st.cache_data` vs `@st.cache_resource`, when each fits |
| 05 | [05-layouts.md](05-layouts.md) | `st.columns`, `st.tabs`, `st.expander`, sidebar |
| 06 | [06-dataframes-charts-and-downloads.md](06-dataframes-charts-and-downloads.md) | `st.dataframe`, `st.plotly_chart`, `st.download_button` |

What's next: [Module 10 — Pipeline design](../10-pipeline-design/README.md).
