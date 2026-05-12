"""Start an AI extraction run from the dashboard.

Picks a model, ticket count, sampling strategy, and launches
`scripts/llm_extract_rich_tickets.py` as a background subprocess. The output
JSONL appears in the active run directory and the Live extraction monitor
page shows progress as the model works.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import run_picker

MODEL_OPTIONS = [
    "mistral-small3.2:24b",
    "gpt-oss:20b",
    "aya-expanse:32b",
    "llama3.3:70b",
    "gpt-oss:120b",
    "gemma3:4b",
    "qwen3:4b",
    "gemma3:1b",
    "gemma3:270m",
    "Custom Ollama model...",
]

MODEL_SECONDS_PER_TICKET = {
    "mistral-small3.2:24b": 20,
    "gpt-oss:20b": 24,
    "aya-expanse:32b": 32,
    "llama3.3:70b": 80,
    "gpt-oss:120b": 120,
    "gemma3:4b": 32,
    "qwen3:4b": 35,
    "gemma3:1b": 18,
    "gemma3:270m": 8,
}

st.title("Start an AI extraction")
st.info(
    "**This page launches** the local AI to read rich support tickets and "
    "extract structured fields (job to be done, emotion, urgency / trust / "
    "money / safety risk levels, what the user actually wants, suggested "
    "next step, product opportunity). After clicking **Start**, switch to "
    "the **Live extraction monitor** page to watch progress in real time.",
    icon=":material/smart_toy:",
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

# ---- Form -----------------------------------------------------------------

st.subheader("Configuration")

col1, col2 = st.columns(2)
with col1:
    backend = st.selectbox(
        "Backend",
        ["ollama", "ollama_hybrid", "rules"],
        index=0,
        help=(
            "**ollama** — local LLM via Ollama (recommended).\n\n"
            "**ollama_hybrid** — deterministic rules for structured fields plus the "
            "LLM only for narrative interpretation. Robust on smaller models.\n\n"
            "**rules** — pure regex baseline, no LLM. Free, instant, weakest output."
        ),
    )
    model_choice = st.selectbox(
        "Model",
        MODEL_OPTIONS,
        index=0,
        help=(
            "Which Ollama model to call. mistral-small3.2:24b is the new "
            "default for better instruction-following and structured output."
        ),
        disabled=(backend == "rules"),
    )
    custom_model = st.text_input(
        "Custom model tag",
        value="",
        placeholder="e.g. command-r:35b",
        disabled=(backend == "rules" or model_choice != "Custom Ollama model..."),
    )
    model = custom_model.strip() if model_choice == "Custom Ollama model..." and custom_model.strip() else model_choice
    custom_model_missing = backend != "rules" and model_choice == "Custom Ollama model..." and not custom_model.strip()
    if custom_model_missing:
        st.warning("Enter an Ollama model tag before starting.", icon=":material/edit:")
with col2:
    limit = st.slider(
        "How many tickets to read",
        min_value=10,
        max_value=1000,
        value=50,
        step=10,
        help="Runtime depends heavily on the selected model and GPU.",
    )
    strategy = st.selectbox(
        "Sampling strategy",
        ["risk_balanced", "highest_context", "issue_balanced"],
        index=0,
        help=(
            "**risk_balanced** — favor high-risk + evidence-rich tickets (used in current run).\n\n"
            "**highest_context** — pick top tickets by note evidence score.\n\n"
            "**issue_balanced** — round-robin across topic clusters."
        ),
    )

resume = st.checkbox(
    "Resume from previous run (skip rows already extracted)",
    value=True,
    help=(
        "When enabled, the extraction reads the existing JSONL file for this "
        "model and skips any source_row already there. Disable to start over."
    ),
)

# ---- ETA preview ----------------------------------------------------------

est_seconds = limit * MODEL_SECONDS_PER_TICKET.get(model, 45)
est_min = est_seconds // 60
st.caption(
    f"Estimated time at full speed: **~{est_min} minutes** for {limit} tickets "
    f"with `{model}`. Actual time depends on ticket length, quantization, GPU, "
    f"and thermal state."
)

# ---- Build command --------------------------------------------------------

project_root = Path(__file__).resolve().parents[3]
venv_python = project_root / ".venv" / "bin" / "python"

cmd = [
    str(venv_python),
    "scripts/llm_extract_rich_tickets.py",
    str(run_dir),
    "--backend", backend,
    "--model", model,
    "--limit", str(limit),
    "--strategy", strategy,
]
if not resume:
    cmd.append("--no-resume")

with st.expander("Show the exact command this will run"):
    st.code(" ".join(shlex.quote(c) for c in cmd), language="bash")

# ---- Detect already-running extractions -----------------------------------

import re

def _running_extractions() -> list[dict]:
    """Find any python processes currently running llm_extract_rich_tickets."""
    try:
        out = subprocess.run(
            ["pgrep", "-af", "llm_extract_rich_tickets"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip().splitlines()
    except Exception:
        return []
    procs = []
    for line in out:
        m = re.match(r"(\d+)\s+(.+)", line)
        if m:
            procs.append({"pid": int(m.group(1)), "cmd": m.group(2)})
    return procs


running = _running_extractions()
if running:
    st.warning(
        f"**An extraction is already running** (PID {running[0]['pid']}). "
        "Starting another one will queue your request behind it. "
        "Watch progress on the Live extraction monitor, or stop the existing "
        "run with the button below.",
        icon=":material/warning:",
    )
    if st.button("Stop the running extraction", type="secondary"):
        for p in running:
            try:
                subprocess.run(["kill", str(p["pid"])])
            except Exception:
                pass
        st.success("Stopped. Refresh in a few seconds.")
        time.sleep(1)
        st.rerun()

# ---- Start button ---------------------------------------------------------

st.subheader("Launch")
launch_col1, launch_col2 = st.columns([1, 3])
with launch_col1:
    start_clicked = st.button(
        "Start extraction",
        type="primary",
        icon=":material/play_arrow:",
        disabled=bool(running) or custom_model_missing,
    )

with launch_col2:
    st.caption(
        "Once started, the run continues even if you close this page. "
        "Output appears in the run folder as a JSONL file with one line per "
        "completed ticket, plus a CSV alias the rest of the dashboard uses."
    )

if start_clicked:
    log_basename = (
        f"extraction_{backend}_{model.replace(':', '-')}_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    log_path = run_dir / log_basename
    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            cwd=str(project_root),
            start_new_session=True,
        )
    time.sleep(0.5)  # let the process actually start before we render
    st.success(
        f"**Extraction started.** PID `{proc.pid}` writing to `{log_path.name}`. "
        f"Open the Live extraction monitor to watch progress."
    )
    st.markdown(
        '<a href="/tools_extraction_monitor" target="_self">'
        '➤ Go to Live extraction monitor</a>',
        unsafe_allow_html=True,
    )
