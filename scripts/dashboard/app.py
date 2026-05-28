"""Streamlit entry point for the analysis dashboard.

Launch:

    .venv/bin/streamlit run scripts/dashboard/app.py

This file is the **navigation dispatcher**. It defines the sidebar structure
(grouped sections), the labels each page shows, and the home page body. Each
page in ``pages/`` keeps its own logic.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import streamlit as st

# Local feature flags — see scripts/dashboard/settings.py
import settings as _settings
from style import apply_dashboard_style

# st.set_page_config must be the very first Streamlit call in the app.
st.set_page_config(
    page_title="What Users Want",
    page_icon=":material/insights:",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_dashboard_style()


def _extraction_is_live(outputs_dir: Path) -> bool:
    """True if any *_extractions.jsonl in any run has been written in the last 90 s."""
    cutoff = time.time() - 90
    for jsonl in outputs_dir.glob("option2_*/*extractions.jsonl"):
        try:
            if jsonl.stat().st_mtime > cutoff:
                return True
        except OSError:
            continue
    return False


def home_page() -> None:
    """Landing page: pitch, headline finding, top wants, where-to-go-next."""
    from lib import (
        attach_friendly_titles,
        discover_extraction_artifacts,
        file_mtime,
        file_size_bytes,
        human_size,
        jsonl_line_count,
        list_csvs,
        list_other_files,
        load_json,
        load_human_labels,
        maybe_load_csv,
        run_picker,
        safe_int,
    )

    # ---- Hero --------------------------------------------------------------

    st.title("What users actually want")
    st.markdown(
        "**A living multilingual support record becomes a map of user intent.** "
        "Use this dashboard to move from support records to "
        "the few recurring things users are actually trying to accomplish, plus "
        "the risks and support actions attached to each one."
    )

    # ---- Run picker --------------------------------------------------------

    run_dir = run_picker("Choose a run to view")
    if run_dir is None:
        st.error("No completed analysis runs were found. Load or select a completed run to view the briefing.")
        return
    st.session_state["run_dir"] = str(run_dir)

    run_meta = load_json(str(run_dir), "run_metadata.json") or {}
    extraction_info = discover_extraction_artifacts(run_dir)
    enriched = maybe_load_csv(run_dir, "enriched_tickets.csv")
    extraction_name = extraction_info.get("csv_name") or "llm_extractions.csv"
    extractions = maybe_load_csv(run_dir, extraction_name) if extraction_name else None
    taxonomy = maybe_load_csv(run_dir, "user_wants_taxonomy.csv")
    full_assignments = maybe_load_csv(run_dir, "user_wants_all_assignments.csv")
    full_summary = maybe_load_csv(run_dir, "user_wants_full_corpus_summary.csv")
    projection_meta = load_json(str(run_dir), "user_wants_projection_metadata.json") or {}
    backlog = (
        maybe_load_csv(run_dir, "refined_opportunity_backlog.csv")
        if maybe_load_csv(run_dir, "refined_opportunity_backlog.csv") is not None
        else maybe_load_csv(run_dir, "opportunity_backlog.csv")
    )

    raw_rows = safe_int(run_meta.get("rows_in_csv"), 0)
    clean_rows = safe_int(run_meta.get("rows_enriched"), len(enriched) if enriched is not None else 0)
    ai_rows = len(extractions) if extractions is not None else safe_int(extraction_info.get("rows"), 0)
    ai_target = safe_int(extraction_info.get("candidates"), ai_rows)
    ai_coverage = (ai_rows / clean_rows * 100) if clean_rows else 0
    full_rows = len(full_assignments) if full_assignments is not None else 0
    full_coverage = (full_rows / clean_rows * 100) if clean_rows else 0
    model_label = str(extraction_info.get("model") or "local rules").strip()
    backend_label = str(extraction_info.get("backend") or "").strip()

    # ---- Headline finding --------------------------------------------------

    st.subheader("The headline finding")
    st.markdown(
        "The dominant user want is **not** *“unban me.”* It is "
        "*“unban me **and tell me why.**”* Two of the top five discovered "
        "wants are about understanding the punishment, not just reversing it. "
        "Inside that picture, three patterns matter:"
    )
    st.markdown(
        "- **Recovery vs reporting tickets feel different.** Recovery users "
        "are anxious; reporting users are angry. The default support reply "
        "template fits one and not the other."
    )
    if _settings.SHOW_DIAMOND_DEALER_FINDING:
        st.markdown(
            "- **Diamond / dealer disputes** are the highest-risk cluster on "
            "money, trust and urgency at once. They deserve their own escalation lane."
        )
    if _settings.SHOW_MANAGER_COMPARISONS:
        st.markdown(
            "- **Long, evidence-rich notes are the input** every other layer of "
            "the analysis depends on. One manager (Albert) writes notes 2-3× richer "
            "than peers, controlling for ticket mix."
        )

    # ---- Top numbers -------------------------------------------------------

    st.subheader("At a glance")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        "Rows in source CSV",
        f"{raw_rows:,}" if raw_rows else "—",
    )
    c2.metric(
        "Analysis-ready records",
        f"{clean_rows:,}" if clean_rows else "—",
    )
    c3.metric(
        "Tickets read by AI",
        f"{ai_rows:,}" if ai_rows else "0",
        delta=f"of {ai_target:,} queued" if ai_target and ai_target != ai_rows else None,
    )
    if full_rows:
        c4.metric("Full corpus mapped", f"{full_rows:,}", delta=f"{full_coverage:.1f}% of records")
    else:
        c4.metric(
            "AI sample coverage",
            f"{ai_coverage:.1f}%" if ai_coverage else "—",
        )
    c5.metric(
        "Discovered wants",
        f"{(taxonomy['want_id'] != -1).sum() if 'want_id' in taxonomy.columns else len(taxonomy)}"
        if taxonomy is not None
        else "—",
    )

    if full_rows:
        st.info(
            f"Active AI extraction: **{extraction_info.get('csv_name') or 'not found'}**"
            + (f" using **{model_label}**" if model_label else "")
            + (f" via **{backend_label}**." if backend_label else ".")
            + f" The discovered taxonomy has been projected across **{full_rows:,}** analysis-ready support records"
            + (
                f" with an assignment threshold of **{projection_meta.get('assignment_threshold')}**."
                if projection_meta.get("assignment_threshold") is not None
                else "."
            ),
            icon=":material/hub:",
        )
    else:
        st.info(
            f"Active AI extraction: **{extraction_info.get('csv_name') or 'not found'}**"
            + (f" using **{model_label}**" if model_label else "")
            + (f" via **{backend_label}**." if backend_label else ".")
            + " This run's taxonomy is based on the AI-read sample above, while the base pipeline still processed the full support record.",
            icon=":material/psychology:",
        )

    if backlog is not None:
        st.caption(f"Ranked opportunity rows available: **{len(backlog):,}**.")

    # ---- Top wants ---------------------------------------------------------

    if taxonomy is not None and len(taxonomy):
        st.subheader("Top things users actually want")
        st.caption(
            "Each row below is a cluster of support records that share the same goal. "
            "Sizes show how many records land there; risk averages show how "
            "much money / trust / urgency is at stake."
        )
        human_labels = load_human_labels(run_dir)
        taxonomy = attach_friendly_titles(taxonomy, human_labels)
        if full_summary is not None and "assigned_want_id" in full_summary.columns:
            title_field = "want_display_title" if "want_display_title" in taxonomy.columns else "want_title"
            title_lookup = dict(zip(taxonomy["want_id"], taxonomy[title_field]))
            full_summary = full_summary.copy()
            full_summary["want_display_title"] = full_summary["assigned_want_id"].map(title_lookup).fillna(
                full_summary.get("want_title", full_summary.get("want_label", ""))
            )
        rename_map = {
            "want_display_title": "Want",
            "want_title": "Want",
            "want_summary": "What this is about",
            "estimated_tickets": "Mapped records",
            "estimated_share": "Share",
            "llm_confirmed_tickets": "Mistral-read examples",
            "size": "AI-read tickets",
            "top_jobs": "Top jobs",
            "top_emotions": "Top emotions",
            "avg_money_risk": "Money risk",
            "avg_trust_risk": "Trust risk",
            "avg_urgency": "Urgency",
        }
        table_source = full_summary if full_summary is not None and full_rows else taxonomy
        if "want_display_title" in table_source.columns:
            rename_map.pop("want_title", None)
        if "estimated_tickets" in table_source.columns:
            table_source = table_source.sort_values("estimated_tickets", ascending=False)
        elif "size" in table_source.columns:
            table_source = table_source.sort_values("size", ascending=False)
        cols_to_show = [c for c in rename_map if c in table_source.columns]
        sub = table_source[cols_to_show].head(10).copy()
        for share_col in ["share", "estimated_share"]:
            if share_col in sub.columns:
                sub[share_col] = (sub[share_col] * 100).round(1).astype(str) + "%"
        sub = sub.rename(columns=rename_map)
        st.dataframe(sub, width="stretch", hide_index=True)

    # ---- Deliverables ------------------------------------------------------

    deliverables = [
        (
            "Read the written findings",
            run_dir / "user_wants_findings.md",
            "Markdown summary of the discovered wants.",
            "text/markdown",
            ":material/article:",
        ),
        (
            "Download the workbook",
            run_dir / "user_wants_workbook.xlsx",
            "Spreadsheet with taxonomy and ticket assignments.",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ":material/table:",
        ),
        (
            "Review the raw AI extraction",
            run_dir / (extraction_info.get("csv_name") or "ollama_extractions.csv"),
            "One row per ticket read by the local/Ollama model.",
            "text/csv",
            ":material/data_object:",
        ),
        (
            "Download full-corpus assignment workbook",
            run_dir / "user_wants_full_corpus_workbook.xlsx",
            "Every analysis-ready support record mapped to the discovered wants, plus review queue.",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ":material/hub:",
        ),
    ]
    available = [item for item in deliverables if item[1].exists()]
    if available:
        st.subheader("Open the deliverables")
        cols = st.columns(len(available))
        for col, (label, path, caption, mime, icon) in zip(cols, available):
            with col:
                st.markdown(f"##### {label}")
                st.caption(caption)
                st.download_button(
                    "Download",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime=mime,
                    icon=icon,
                    key=f"download_{path.name}",
                )

    # ---- Where to go next --------------------------------------------------

    st.subheader("Where to go next")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("##### See the findings")
        lines = [
            "**Macro and micro reality** — timeline, forecast and repeat-user journeys.",
            "**What users actually want** — the full ranked taxonomy with filters and heatmaps.",
            "**Where to act first** — opportunities scored by impact.",
        ]
        if _settings.SHOW_MANAGER_COMPARISONS:
            lines.append("**How managers compare** — note quality leaderboard.")
        st.caption("<br><br>".join(lines), unsafe_allow_html=True)
    with col2:
        st.markdown("##### Explore the data")
        st.caption(
            "**Map of all records** — every support record as a dot, grouped by meaning.<br><br>"
            "**Find a specific record** — search across 6,728 source rows.<br><br>"
            "**Browse any data table** — auto-discovered CSVs from the run.",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown("##### Quality checks")
        st.caption(
            "**Compare AI models** — Gemma vs Qwen vs rules side-by-side.<br><br>"
            "**Run SQL queries** — power-user console over the local database.<br><br>"
            "**Live extraction monitor** — watches AI runs in real time.",
            unsafe_allow_html=True,
        )

    # ---- Export to PDF / printable summary --------------------------------

    if not _settings.SHOW_EXECUTIVE_EXPORT:
        return  # nothing more to render on the home page

    st.subheader("Take it to the meeting")
    st.caption(
        "Generates a one-page printable HTML summary of the headline findings, "
        "the top wants table, and the active run's KPIs. Open it in any browser "
        "and use **File → Print → Save as PDF** to share with the team."
    )

    def _build_summary_html() -> str:
        """Compose a self-contained one-page HTML executive summary."""
        n_tickets = len(enriched) if enriched is not None else 0
        n_users = (
            enriched["uid"].astype(str).str.strip().replace("", None).dropna().nunique()
            if enriched is not None and "uid" in enriched.columns
            else 0
        )
        n_extracted = len(extractions) if extractions is not None else 0
        n_wants = (
            (taxonomy["want_id"] != -1).sum() if taxonomy is not None and "want_id" in taxonomy.columns else 0
        )
        n_opp = len(backlog) if backlog is not None else 0

        rows = []
        summary_source = full_summary if full_summary is not None and full_rows else taxonomy
        if summary_source is not None and len(summary_source):
            if "estimated_tickets" in summary_source.columns:
                summary_source = summary_source.sort_values("estimated_tickets", ascending=False)
            elif "size" in summary_source.columns:
                summary_source = summary_source.sort_values("size", ascending=False)
            for _, r in summary_source.head(10).iterrows():
                title = (r.get("want_display_title") or r.get("want_title") or r.get("want_label") or "—").replace("<", "&lt;")
                size = int(r.get("estimated_tickets") or r.get("size") or 0)
                share = (r.get("estimated_share") if "estimated_share" in r else r.get("share")) or 0
                share = share * 100
                jobs = (r.get("top_jobs") or "").replace("<", "&lt;")
                emo = (r.get("top_emotions") or "").replace("<", "&lt;")
                money = r.get("avg_money_risk") or "—"
                trust = r.get("avg_trust_risk") or "—"
                rows.append(
                    f"<tr><td>{title}</td><td>{size}</td><td>{share:.1f}%</td>"
                    f"<td>{jobs}</td><td>{emo}</td><td>{money}</td><td>{trust}</td></tr>"
                )
        rows_html = "\n".join(rows) or "<tr><td colspan='7'>No taxonomy in this run.</td></tr>"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>What Users Want — Executive Summary</title>
<style>
  @page {{ size: A4; margin: 14mm; }}
  body {{ font-family: -apple-system, "Inter", "Segoe UI", sans-serif;
         color: #1f1f1f; line-height: 1.45; max-width: 920px; margin: 0 auto; padding: 1.5rem; }}
  h1 {{ font-size: 1.55rem; margin-bottom: 0.2rem; }}
  h2 {{ font-size: 1.05rem; margin-top: 1.4rem; border-bottom: 1px solid #e5e5e5;
        padding-bottom: 0.2rem; }}
  .lead {{ color: #444; font-size: 0.95rem; margin-bottom: 1rem; }}
  .meta {{ color: #888; font-size: 0.78rem; }}
  .kpi {{ display: flex; gap: 1rem; margin: 1rem 0; }}
  .kpi div {{ flex: 1; background: #f6f5fb; padding: 0.6rem 0.8rem; border-radius: 0.4rem; }}
  .kpi .v {{ font-size: 1.3rem; font-weight: 600; color: #4527a0; }}
  .kpi .l {{ font-size: 0.75rem; color: #555; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; margin-top: 0.6rem; }}
  th, td {{ text-align: left; padding: 0.35rem 0.5rem; vertical-align: top;
            border-bottom: 1px solid #ececec; }}
  th {{ background: #faf9fc; }}
  ul li {{ margin-bottom: 0.35rem; }}
  footer {{ margin-top: 1.6rem; color: #888; font-size: 0.72rem; border-top: 1px solid #eee;
            padding-top: 0.5rem; }}
  @media print {{ body {{ padding: 0; }} }}
</style></head>
<body>
<h1>What users actually want</h1>
<p class="lead">A structured map of what {n_tickets:,} support records revealed about
user intent, discovered from ticket text rather than the category column.</p>
<p class="meta">Run: {run_dir.name} &middot; Generated: {timestamp} &middot;
AI extraction: {model_label or "not available"}{(" via " + backend_label) if backend_label else ""}.</p>

<div class="kpi">
  <div><div class="v">{n_tickets:,}</div><div class="l">Records analyzed</div></div>
  <div><div class="v">{n_users:,}</div><div class="l">Unique users</div></div>
  <div><div class="v">{n_extracted:,}</div><div class="l">Read by AI</div></div>
  <div><div class="v">{n_wants}</div><div class="l">Discovered wants</div></div>
  <div><div class="v">{n_opp:,}</div><div class="l">Ranked opportunities</div></div>
</div>

<h2>The headline</h2>
<ul>
  <li>The dominant want is not <em>“unban me”</em> — it is <em>“unban me <strong>and tell me why.”</strong></em>
      Two of the top five discovered wants are about understanding the punishment, not just reversing it.</li>
  <li><strong>Recovery vs reporting tickets feel different.</strong> Recovery users are anxious;
      reporting users are angry. The default support reply template fits one and not the other.</li>
  <li><strong>Diamond / dealer disputes</strong> are the single highest-risk cluster across money,
      trust and urgency. They deserve their own escalation lane.</li>
</ul>

<h2>Top discovered user wants</h2>
<table>
  <thead><tr>
    <th>Want</th><th>Tickets</th><th>Share</th><th>Top jobs</th>
    <th>Top emotions</th><th>Money risk</th><th>Trust risk</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>

<footer>
Built with Python, sentence-transformers (multilingual MiniLM), HDBSCAN, BERTopic, and Ollama-compatible local model outputs.
Source code, engineering docs, and the 101 self-paced course are in the project repository.
</footer>
</body></html>
"""

    summary_html = _build_summary_html()
    st.download_button(
        label="Download printable executive summary (HTML)",
        data=summary_html.encode("utf-8"),
        file_name=f"what_users_want_{run_dir.name}.html",
        mime="text/html",
        icon=":material/download:",
    )

    # ---- Active run details (collapsed) -----------------------------------

    with st.expander(f"Run details: `{run_dir.name}`", expanded=False):
        run_dir_str = str(run_dir)
        csvs = list_csvs(run_dir_str)
        other = list_other_files(run_dir_str)
        st.write(
            f"**Data tables:** {len(csvs)} CSV files. "
            f"**Excel workbooks:** {len(other['xlsx'])}. "
            f"**Interactive maps:** {len(other['html'])}."
        )
        ext_jsonl = extraction_info.get("jsonl_path")
        if ext_jsonl is not None and ext_jsonl.exists():
            completed = jsonl_line_count(ext_jsonl)
            target = safe_int(extraction_info.get("candidates"), 0)
            if target:
                st.info(
                    f"Local AI has read **{completed:,} of {target:,}** rich tickets in this run."
                )
            else:
                st.info(f"Local AI has read **{completed:,}** tickets in this run.")

    # ---- Transparency footer ----------------------------------------------

    st.markdown("---")
    st.caption(
        "**About this dashboard.** It reads files from this project folder. "
        "No extra API calls happen while you browse. AI extraction outputs may "
        "come from a local machine or a rented GPU pod; this page only visualizes "
        "the saved run artefacts. The pipeline is open-source — see the "
        "engineering docs for how every number on this page is computed."
    )


# ---- Navigation ----------------------------------------------------------

executive = st.Page(
    "pages/11_Executive_Briefing.py",
    title="Executive briefing",
    icon=":material/leaderboard:",
    default=True,
    url_path="executive_briefing",
)

home = st.Page(
    home_page,
    title="Analyst overview",
    icon=":material/home:",
)

findings = [
    st.Page(
        "pages/12_Longitudinal_Reality.py",
        title="Macro and micro reality",
        icon=":material/timeline:",
        url_path="findings_longitudinal_reality",
    ),
    st.Page(
        "pages/02_What_Users_Want.py",
        title="What users actually want",
        icon=":material/lightbulb:",
        url_path="findings_what_users_want",
    ),
    st.Page(
        "pages/03_Opportunities.py",
        title="Where to act first",
        icon=":material/trending_up:",
        url_path="findings_opportunities",
    ),
    st.Page(
        "pages/05_Repeat_Customers.py",
        title="Customers who keep coming back",
        icon=":material/group:",
        url_path="findings_repeat_customers",
    ),
]
if _settings.SHOW_MANAGER_COMPARISONS:
    # Insert in the same position the page used to live (after Opportunities).
    findings.insert(
        2,
        st.Page(
            "pages/04_Manager_Note_Quality.py",
            title="How managers compare",
            icon=":material/edit_note:",
            url_path="findings_manager_quality",
        ),
    )

explore = [
    st.Page(
        "pages/06_Ticket_Map.py",
        title="Map of all tickets",
        icon=":material/map:",
        url_path="explore_ticket_map",
    ),
    st.Page(
        "pages/07_Find_a_Ticket.py",
        title="Find a specific ticket",
        icon=":material/search:",
        url_path="explore_find_ticket",
    ),
    st.Page(
        "pages/13_No_Ban_Mentions.py",
        title="No-ban mentions",
        icon=":material/gpp_maybe:",
        url_path="explore_no_ban_mentions",
    ),
    st.Page(
        "pages/08_Browse_Data_Tables.py",
        title="Browse any data table",
        icon=":material/table_view:",
        url_path="explore_browse_tables",
    ),
]

quality = [
    st.Page(
        "pages/09_Compare_Local_Models.py",
        title="Compare AI models",
        icon=":material/compare:",
        url_path="quality_compare_models",
    ),
]

_outputs_dir = Path(__file__).resolve().parents[2] / "outputs"
_live = _extraction_is_live(_outputs_dir)
_monitor_title = "Live extraction monitor — running now" if _live else "Live extraction monitor"
_monitor_icon = ":material/play_circle:" if _live else ":material/monitor_heart:"

tools = [
    st.Page(
        "pages/00_Start_Extraction.py",
        title="Start an AI extraction",
        icon=":material/smart_toy:",
        url_path="tools_start_extraction",
    ),
    st.Page(
        "pages/01_Extraction_Progress.py",
        title=_monitor_title,
        icon=_monitor_icon,
        url_path="tools_extraction_monitor",
    ),
    st.Page(
        "pages/10_Run_SQL_Queries.py",
        title="Run SQL queries",
        icon=":material/database:",
        url_path="tools_sql_console",
    ),
]

_nav: dict[str, list] = {
    "": [executive, home],
    "Findings": findings,
    "Explore the data": explore,
    "Quality checks": quality,
}
if _settings.SHOW_TOOLS_SECTION:
    _nav["Tools"] = tools

pg = st.navigation(_nav)
pg.run()
