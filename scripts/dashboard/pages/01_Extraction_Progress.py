"""Live monitor for any local-AI extraction run, past or in progress.

Shows: progress bar, ETA, valid / flagged / failed split, what jobs and
emotions have been extracted so far, recent rows, and a tail of the run log.

Auto-refreshes every 5 seconds when an extraction is detected as running.

Teaching
--------
This page is a "live dashboard" for a long-running local-AI job. Streamlit
has no native auto-refresh, so we inject a tiny inline ``<script>`` tag with
``st.markdown(..., unsafe_allow_html=True)`` that calls
``window.location.reload()`` on a 5-second timer. This is a hack but a
classic one — it works in any browser, requires no extra dependencies, and
it's fine to drop when the user unchecks the auto-refresh box.

Other ideas worth understanding line-by-line:

* **JSONL tail.** The extraction process writes one line per ticket to a
  ``.jsonl`` file. ``jsonl_line_count`` (counts lines) and ``tail_jsonl``
  (parses the last N) live in ``lib.py``. JSONL is append-friendly: a
  reader can count progress without parsing the whole file.

* **In-progress detection.** If the file's mtime is within 90 seconds of
  ``datetime.now()``, we assume the writer is still active. This is the
  cheapest way to ask "is the extraction still running?" without an IPC
  channel.

* **ETA computation.** We read ``generated_at`` from a status JSON file,
  compute ``elapsed = now - started``, derive a rate
  (``completed / elapsed``), and project ``remaining = (target - completed)
  / rate``. ``timedelta(seconds=int(remaining))`` formats the result as
  ``HH:MM:SS``.

* **Progress bar.** ``st.progress(pct, text=...)`` takes a float in
  ``[0, 1]`` and renders the familiar Streamlit progress bar.

* **``pd.json_normalize(records)``** flattens a list of nested dicts
  (one per JSONL line) into a tabular DataFrame. Nested keys like
  ``ticket.metadata.priority`` become flat columns
  ``ticket_metadata_priority``.

* **``st.tabs([...])`` + ``with col_or_tab:``.** Streamlit layout
  primitives are entered with the ``with`` statement; everything indented
  beneath ``with col1:`` ends up inside that column.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import (
    chart_picker,
    counts_df,
    file_mtime,
    file_size_bytes,
    human_size,
    jsonl_line_count,
    list_runs,
    load_json,
    run_picker,
    safe_int,
    status_badge,
    tail_jsonl,
)

st.title("Live extraction monitor")
st.info(
    "**This page answers:** what is the local AI doing right now, and what has "
    "it produced so far? It auto-refreshes every 5 seconds when a run is active. "
    "Each ticket is read end-to-end, parsed into JSON, validated against an enum "
    "schema, and appended to a JSONL file as soon as it's done.",
    icon=":material/help:",
)
st.caption(
    "Tracks the local AI (Gemma / Qwen) reading rich tickets and turning them into "
    "structured records. To start a new run, open the **Start an AI extraction** page."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

refresh = st.sidebar.checkbox("Auto-refresh every 5s", value=True)
n_tail = st.sidebar.slider("Recent rows to show", 5, 100, 25, step=5)

if refresh:
    st.markdown(
        """
        <script>setTimeout(function(){window.location.reload();}, 5000);</script>
        """,
        unsafe_allow_html=True,
    )

candidates = list(run_dir.glob("*extractions.jsonl"))
if not candidates:
    st.info(
        "No extraction logs in this run yet. "
        "When an extraction starts, this page will fill in automatically."
    )
    st.stop()

label_to_path = {p.name: p for p in sorted(candidates, reverse=True)}
selected = st.selectbox("Extraction file to monitor", list(label_to_path.keys()))
jsonl_path = label_to_path[selected]
csv_path = jsonl_path.with_suffix(".csv")

status_data = load_json(str(run_dir), "llm_extraction_status.json") or {}
candidates_target = safe_int(status_data.get("candidates"), fallback=0)

if not candidates_target:
    cand_csv = run_dir / "llm_extraction_candidates.csv"
    if cand_csv.exists():
        try:
            candidates_target = sum(1 for _ in cand_csv.open()) - 1
        except Exception:
            candidates_target = 0

completed = jsonl_line_count(jsonl_path)
mtime = file_mtime(jsonl_path)
size = file_size_bytes(jsonl_path)

in_progress = bool(mtime and (datetime.now() - mtime).total_seconds() < 90)

# ---- Top status row ------------------------------------------------------

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Status", status_badge("running" if in_progress else "idle"))
c2.metric("Tickets read", f"{completed:,}")
c3.metric("Target", f"{candidates_target:,}" if candidates_target else "unknown")
c4.metric(
    "Last write",
    mtime.strftime("%H:%M:%S") if mtime else "—",
    f"{(datetime.now() - mtime).total_seconds():.0f}s ago" if mtime else None,
)
c5.metric("File size", human_size(size))

if candidates_target:
    pct = min(completed / candidates_target, 1.0)
    st.progress(pct, text=f"{completed:,} of {candidates_target:,} ({pct*100:.1f}%)")
else:
    st.write(f"**{completed:,}** tickets read so far (target unknown)")

# ---- ETA -----------------------------------------------------------------

if completed > 1 and candidates_target and completed < candidates_target and mtime:
    started = status_data.get("generated_at")
    started_dt = None
    if started:
        try:
            started_dt = datetime.fromisoformat(started)
        except Exception:
            started_dt = None
    if started_dt:
        elapsed = max((datetime.now() - started_dt).total_seconds(), 1.0)
        rate = completed / elapsed
        remaining = (candidates_target - completed) / max(rate, 1e-6)
        eta = datetime.now() + timedelta(seconds=remaining)
        st.caption(
            f"Pace: {rate*60:.1f} tickets per minute · "
            f"Remaining: {timedelta(seconds=int(remaining))} · "
            f"Estimated finish: {eta.strftime('%H:%M:%S')}"
        )

# ---- Output health ------------------------------------------------------

if csv_path.exists():
    df = pd.read_csv(csv_path)
    st.subheader("Output health")
    sc1, sc2, sc3, sc4 = st.columns(4)
    if "_status" in df.columns:
        ok = (df["_status"] == "ok").sum()
        bad = (df["_status"] == "bad_output").sum()
        err = (df["_status"] == "error").sum()
        sc1.metric("Valid", f"{ok:,}")
        sc2.metric("Flagged for review", f"{bad:,}", delta=None if bad == 0 else f"{bad/len(df)*100:.1f}%")
        sc3.metric("Failed", f"{err:,}", delta=None if err == 0 else f"{err/len(df)*100:.1f}%")
    sc4.metric("Total rows", f"{len(df):,}")

    if "_quality_flag" in df.columns and df["_quality_flag"].notna().any():
        st.write("**Reasons rows were flagged for review:**")
        flag_labels = {
            "source_row_schema_echo": "Model echoed the schema instead of answering",
            "source_row_mismatch": "Model returned a different ticket number",
            "empty_required_fields": "Required fields were empty",
            "schema_echo": "Output contained schema descriptors, not real values",
            "invalid_job": "Job category was not in the allowed list",
            "invalid_emotion": "Emotion was not in the allowed list",
            "too_vague": "Free-text fields were too generic ('investigate', 'unknown')",
        }
        flags = df["_quality_flag"].fillna("").value_counts()
        flags = flags[flags.index != ""]
        if len(flags):
            df_flags = counts_df(flags, "Reason", "Tickets")
            df_flags["Reason"] = df_flags["Reason"].map(lambda s: flag_labels.get(s, s))
            fig = px.bar(df_flags, x="Tickets", y="Reason", orientation="h", height=240)
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

    j1, j2 = st.columns(2)
    if "job_to_be_done" in df.columns:
        with j1:
            st.write("**What jobs users were trying to accomplish**")
            jobs = df["job_to_be_done"].fillna("(missing)").value_counts().head(15)
            chart_picker(
                counts_df(jobs, "Job to be done", "Tickets"),
                label_col="Job to be done",
                value_col="Tickets",
                key_prefix="monitor_jobs",
                default="Horizontal bars",
                height=400,
            )
    if "user_emotion" in df.columns:
        with j2:
            st.write("**Emotional tone of users**")
            emos = df["user_emotion"].fillna("(missing)").value_counts()
            chart_picker(
                counts_df(emos, "Emotion", "Tickets"),
                label_col="Emotion",
                value_col="Tickets",
                key_prefix="monitor_emotions",
                default="Horizontal bars",
                height=400,
            )

    risk_cols = [
        ("urgency_level", "Urgency (1-5)"),
        ("trust_risk_level", "Trust risk (1-5)"),
        ("money_risk_level", "Money risk (1-5)"),
        ("safety_policy_risk_level", "Safety / policy risk (1-5)"),
    ]
    risk_cols = [(c, label) for c, label in risk_cols if c in df.columns]
    if risk_cols:
        st.write("**How serious the tickets are, by category**")
        rcols = st.columns(len(risk_cols))
        for (col, label), rcol in zip(risk_cols, rcols):
            with rcol:
                fig = px.histogram(df, x=col, nbins=5, height=200, title=label)
                fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), title_font_size=12, xaxis_title="", yaxis_title="Tickets")
                rcol.plotly_chart(fig, use_container_width=True)

# ---- Latest extraction in detail ----------------------------------------

st.subheader("Latest tickets in detail")
st.caption(
    "The 3 most recent tickets the AI processed, with the original ticket text "
    "on the left and what the model extracted on the right."
)

candidates_csv = run_dir / "llm_extraction_candidates.csv"
candidates_df = None
if candidates_csv.exists():
    try:
        candidates_df = pd.read_csv(candidates_csv)
        candidates_df["source_row"] = candidates_df["source_row"].astype(str)
    except Exception:
        candidates_df = None

recent = tail_jsonl(jsonl_path, n=max(3, n_tail))
if recent:
    last_three = list(reversed(recent[-3:]))
    for row in last_three:
        sr = str(row.get("source_row", ""))
        status = row.get("_status", "")
        status_label = {"ok": "Valid", "bad_output": "Flagged", "error": "Failed"}.get(status, status or "—")
        status_color = {
            "ok": "#2e7d32",
            "bad_output": "#ef6c00",
            "error": "#c62828",
        }.get(status, "#555")

        with st.container(border=True):
            head_left, head_right = st.columns([3, 1])
            head_left.markdown(f"### Ticket #{sr}")
            head_right.markdown(
                f"<div style='text-align:right;font-weight:600;color:{status_color}'>"
                f"{status_label}</div>",
                unsafe_allow_html=True,
            )

            tcol, ecol = st.columns(2)

            with tcol:
                st.markdown("**Original ticket text**")
                ticket_text = "(not available — ticket text was not in the candidates CSV)"
                if candidates_df is not None:
                    match = candidates_df[candidates_df["source_row"] == sr]
                    if len(match):
                        ticket_text = str(match.iloc[0].get("llm_input_text", ticket_text))
                # Trim insanely long tickets
                if len(ticket_text) > 1500:
                    ticket_text = ticket_text[:1500] + "\n\n…[truncated]"
                st.markdown(
                    f"<div style='background:#f6f5fb;padding:0.7rem 0.9rem;"
                    f"border-radius:0.4rem;font-size:0.83rem;line-height:1.4;"
                    f"max-height:340px;overflow-y:auto;white-space:pre-wrap;'>"
                    f"{ticket_text}</div>",
                    unsafe_allow_html=True,
                )

            with ecol:
                st.markdown("**What the AI extracted**")
                if status == "error":
                    st.error(f"Extraction failed: {row.get('_error', '(no message)')}")
                else:
                    fields = [
                        ("Job to be done", row.get("job_to_be_done")),
                        ("Emotion", row.get("user_emotion")),
                        ("Urgency / Trust / Money / Safety",
                         f"{row.get('urgency_level','—')} / "
                         f"{row.get('trust_risk_level','—')} / "
                         f"{row.get('money_risk_level','—')} / "
                         f"{row.get('safety_policy_risk_level','—')}"),
                        ("What the user literally said", row.get("literal_request")),
                        ("What the user actually wants", row.get("actual_user_want")),
                        ("Suggested support step", row.get("support_next_step")),
                        ("Product opportunity", row.get("product_opportunity")),
                        ("Model confidence", row.get("confidence")),
                    ]
                    md_lines = []
                    for label, value in fields:
                        v = "—" if value in (None, "", float("nan")) else str(value)
                        if len(v) > 280:
                            v = v[:280] + "…"
                        md_lines.append(f"- **{label}:** {v}")
                    if row.get("_quality_flag"):
                        md_lines.insert(0, f"- ⚠ **Quality flag:** `{row['_quality_flag']}`")
                    st.markdown("\n".join(md_lines))

# ---- Recent rows tail (compact) -----------------------------------------

st.subheader(f"All recent tickets — last {n_tail}")
st.caption(
    "Compact table of the most recent extractions. Sort by any column header. "
    "Use the panel above for the full per-ticket text view."
)
if recent:
    flat = pd.json_normalize(recent)
    show_cols = {
        "source_row": "Ticket #",
        "_status": "Status",
        "_quality_flag": "Quality flag",
        "job_to_be_done": "Job to be done",
        "user_emotion": "Emotion",
        "urgency_level": "Urgency",
        "trust_risk_level": "Trust risk",
        "money_risk_level": "Money risk",
        "literal_request": "What user said",
        "actual_user_want": "What user actually wants",
        "support_next_step": "Suggested support step",
        "product_opportunity": "Product opportunity",
        "confidence": "Model confidence",
    }
    keep = [c for c in show_cols if c in flat.columns]
    if keep:
        if "_status" in flat.columns:
            flat["_status"] = flat["_status"].map({"ok": "Valid", "bad_output": "Flagged", "error": "Failed"}).fillna(flat["_status"])
        rename_map = {c: show_cols[c] for c in keep}
        st.dataframe(flat[keep].rename(columns=rename_map), use_container_width=True, hide_index=True, height=380)

# ---- Log tail ------------------------------------------------------------

with st.expander("Show run log"):
    log_files = sorted(run_dir.glob("extraction_*.log"))
    if not log_files:
        st.write("No log files in this run.")
    else:
        chosen = st.selectbox("Log file", [p.name for p in log_files], key="log_select")
        log_path = run_dir / chosen
        text = log_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        st.code("\n".join(lines[-200:]), language="text")
