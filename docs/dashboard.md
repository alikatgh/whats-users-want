# Dashboard

Interactive web UI over every CSV, every chart, every extraction in `outputs/`. Auto-discovers run directories, auto-discovers any new CSV that lands. Everything runs locally — no external services.

## Launch

```bash
./scripts/run_dashboard.sh
# then open http://localhost:8501
```

The launcher uses port 8501 by default; pass another port as the first argument.

## Stack

- **[Streamlit](https://streamlit.io/)** — Python multipage UI; one command to launch; hot-reloads on save.
- **[DuckDB](https://duckdb.org/)** — local SQL engine over the run's `analysis.duckdb` for fast queries against ticket and topic tables.
- **[Plotly Express](https://plotly.com/python/plotly-express/)** — interactive charts (heatmaps, scatter, bar, histogram, box).

## Pages

| Page | What it shows |
|---|---|
| **Home / Overview** | Top numbers for the run, the headline taxonomy, file inventory. |
| **Live extraction monitor** | Watches the local Ollama model process tickets in real time. Progress bar, ETA, valid / flagged / failed split, what jobs and emotions have been extracted so far, recent rows, log tail. Auto-refreshes every 5 seconds. |
| **What users actually want** | Filterable explorer for the discovered want clusters. Want × emotion, want × money risk, want × manager heatmaps. Drill into any cluster. |
| **Opportunities ranked by impact** | Filter by recommended action, risk, lift, volume. Score-vs-volume scatter. Drill into any topic. Topics growing in the last 30 days. |
| **Manager note quality** | Per-manager note evidence stats. Adjusted statistical comparison vs benchmark manager. Robustness check. Per-manager coaching list. |
| **Repeat customers** | Profiles for users who file multiple tickets. Tickets-per-customer histogram, profile × unresolved and profile × note evidence boxplots. |
| **Ticket map by meaning** | Interactive 2D map of every ticket; tickets close together talk about similar things, even across English / Russian / Chinese. |
| **Find a ticket** | Full-text and structured search over every ticket via DuckDB. Filters by manager, desire, category, status, evidence level. CSV download. |
| **Browse data tables** | **Auto-discovers every CSV in the run.** Pick any file — see column types, sort and filter rows, get automatic charts. Works for any new output without changes. |
| **Compare local model outputs** | Side-by-side comparison of any two locally-run extraction files (rule-based, Mistral, GPT-OSS, Aya, Llama, Gemma, Qwen, hybrid). Per-ticket diff for shared rows. No external services. |
| **Run SQL queries** | Power-user console over the run's local database. Schema browser. Pre-built queries. Free SQL with CSV download. |

## Run-folder picker

Every page has a sidebar selector to switch between any `outputs/option2_*` folder. Defaults to the latest. Re-running any pipeline stage produces a new folder — it appears in the dropdown automatically.

## How automation works

- **No hardcoded paths.** Pages read from whatever run folder the sidebar picker selects.
- **No hardcoded CSV list.** The data-table browser, the model comparison page, and the SQL console all enumerate files at request time.
- **No DataFrame schema assumptions.** Each page checks for the columns it needs and falls back gracefully (informative warnings instead of crashes).
- **Caching.** Streamlit's `@st.cache_data` keys on `(run_dir, file)` so switching runs invalidates correctly and switching back reuses memory.
- **Local database is read-only.** The SQL console cannot mutate tables.

## Adding a new page

Create a file at `scripts/dashboard/pages/NN_Title_Words.py`. Streamlit picks it up automatically — no configuration. Convention used here:

```python
"""One-line module docstring."""
import sys
from pathlib import Path
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import maybe_load_csv, run_picker

st.set_page_config(page_title="Page Title", layout="wide")
st.title("Plain-English title")

run_dir = run_picker()
if run_dir is None:
    st.stop()

df = maybe_load_csv(run_dir, "your_file.csv")
if df is None:
    st.warning("Missing input.")
    st.stop()

# ... your page logic, with friendly column renames before display
```

## Stop the dashboard

```bash
pkill -f "streamlit run"
```
