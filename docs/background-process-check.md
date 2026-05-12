# Background Process Check

Use this when the laptop is heating up and you want to know whether this project, Ollama, Streamlit, or another dev server is running in the background.

PIDs change every time, so do not copy old PIDs blindly. Use the commands to find current PIDs first.

## 1. Check for This Project and Common Dev Processes

```bash
ps -axo pid,ppid,%cpu,%mem,etime,command | rg "2026-what-users|llm_extract_rich_tickets|streamlit run|mkdocs serve|ollama|option2_pipeline|bertopic_from_run|insight_layer|split_outlier_bucket|build_user_wants_taxonomy|run_dashboard|uvicorn|vite|npm run dev|mappster"
```

What to look for:

- `llm_extract_rich_tickets.py` means ticket extraction is running.
- `streamlit run` or `run_dashboard` means the dashboard is running.
- `mkdocs serve` means docs live preview is running.
- `option2_pipeline.py`, `bertopic_from_run.py`, `insight_layer.py`, `split_outlier_bucket.py`, or `build_user_wants_taxonomy.py` means an analysis stage is running.
- `ollama serve` alone is usually harmless if CPU is near `0.0`.
- `uvicorn`, `vite`, or `npm run dev` may be unrelated dev servers.

## 2. See the Top CPU Processes

```bash
ps -axo pid,ppid,%cpu,%mem,etime,command | sort -k3 -nr | head -30
```

What to look for:

- High `%CPU` is the main heat signal.
- Anything above `50` can noticeably heat the laptop.
- Browser renderers, GPU processes, antivirus, and dev servers often appear here.

## 3. Identify Where a Suspicious Process Came From

Replace `PID_HERE` with the process ID from the earlier output:

```bash
lsof -a -p PID_HERE -d cwd
```

Examples:

```bash
lsof -a -p 75744 -d cwd
lsof -a -p 42768 -d cwd
lsof -a -p 1916 -d cwd
```

This shows the process working directory. That is how you tell whether a server belongs to this project or another repo.

## 4. Stop a Process

Only kill processes you recognize and do not need.

```bash
kill PID_HERE
```

To stop several related processes at once:

```bash
kill PID1 PID2 PID3
```

If a normal `kill` does not work, wait a few seconds and check again before using stronger options.

## 5. Confirm It Stopped

Run the filter again:

```bash
ps -axo pid,ppid,%cpu,%mem,etime,command | rg "2026-what-users|llm_extract_rich_tickets|streamlit run|mkdocs serve|ollama|option2_pipeline|bertopic_from_run|insight_layer|split_outlier_bucket|build_user_wants_taxonomy|run_dashboard|uvicorn|vite|npm run dev|mappster"
```

Then re-check top CPU:

```bash
ps -axo pid,ppid,%cpu,%mem,etime,command | sort -k3 -nr | head -15
```

## What I Saw on 2026-05-12

No BIGO analysis process was running:

- No `llm_extract_rich_tickets.py`
- No Streamlit dashboard
- No MkDocs server
- No pipeline, BERTopic, insight, outlier split, or taxonomy script

Ollama was running but idle:

- `ollama serve`
- PID at the time: `1916`
- CPU: `0.0`
- Working directory: `/opt/homebrew/var`

The main unrelated dev workload was from another project:

- `uvicorn main:app --reload --port 8000`
- PID at the time: `75744`
- CPU was around `36-48%`
- Working directory: `/Users/s_avelova/Documents/projects/mappster/backend`

Also running from the same unrelated project:

- `npm run dev --host 127.0.0.1 --port 5174 --strictPort`
- `vite --host 127.0.0.1 --port 5174 --strictPort`
- `esbuild`
- Working directory: `/Users/s_avelova/Documents/projects/mappster`

I stopped those with:

```bash
kill 75744 42768 42865 42866
```

After that, no BIGO project analysis was running. The remaining heat looked mostly like app/UI load:

- Google Chrome renderer
- Codex GPU/renderer processes
- `WindowServer`
- VS Code GPU process
- Kaspersky
- `coreaudiod`

## Optional: Stop Ollama

Do this only if Ollama is actually consuming CPU or you do not need it.

```bash
kill $(pgrep -f "ollama serve")
```

If `pgrep` is blocked by macOS permissions, find the Ollama PID with:

```bash
ps -axo pid,ppid,%cpu,%mem,etime,command | rg "ollama serve"
```

Then stop it:

```bash
kill PID_HERE
```

