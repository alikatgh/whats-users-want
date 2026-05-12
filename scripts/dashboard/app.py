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

# st.set_page_config must be the very first Streamlit call in the app.
st.set_page_config(
    page_title="What Users Want",
    page_icon=":material/insights:",
    layout="wide",
    initial_sidebar_state="expanded",
)


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
        file_mtime,
        file_size_bytes,
        human_size,
        jsonl_line_count,
        list_csvs,
        list_other_files,
        load_human_labels,
        maybe_load_csv,
        run_picker,
        safe_int,
    )

    # ---- Hero --------------------------------------------------------------

    st.title("What users actually want")
    st.markdown(
        "**The team had 6,728 messy support tickets in three languages "
        "and a category column nobody trusted.** This dashboard is what came "
        "out the other end: a list of what users are *actually* trying to "
        "accomplish, ranked by how much it costs us not to fix it."
    )

    # ---- Run picker --------------------------------------------------------

    run_dir = run_picker("Choose a run to view")
    if run_dir is None:
        st.error("No analysis runs found yet. Run `scripts/option2_pipeline.py` first.")
        return
    st.session_state["run_dir"] = str(run_dir)

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

    enriched = maybe_load_csv(run_dir, "enriched_tickets.csv")
    extractions = (
        maybe_load_csv(run_dir, "ollama_gemma3-4b_extractions.csv")
        if maybe_load_csv(run_dir, "ollama_gemma3-4b_extractions.csv") is not None
        else maybe_load_csv(run_dir, "llm_extractions.csv")
    )
    taxonomy = maybe_load_csv(run_dir, "user_wants_taxonomy.csv")
    backlog = (
        maybe_load_csv(run_dir, "refined_opportunity_backlog.csv")
        if maybe_load_csv(run_dir, "refined_opportunity_backlog.csv") is not None
        else maybe_load_csv(run_dir, "opportunity_backlog.csv")
    )

    st.subheader("At a glance")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        "Tickets analyzed",
        f"{len(enriched):,}" if enriched is not None else "—",
    )
    c2.metric(
        "Unique users",
        f"{enriched['uid'].astype(str).str.strip().replace('', None).dropna().nunique():,}"
        if enriched is not None and "uid" in enriched.columns
        else "—",
    )
    c3.metric(
        "Tickets read by AI",
        f"{len(extractions):,}" if extractions is not None else "0",
    )
    c4.metric(
        "Discovered wants",
        f"{(taxonomy['want_id'] != -1).sum() if 'want_id' in taxonomy.columns else len(taxonomy)}"
        if taxonomy is not None
        else "—",
    )
    c5.metric(
        "Ranked opportunities",
        f"{len(backlog):,}" if backlog is not None else "—",
    )

    # ---- Top wants ---------------------------------------------------------

    if taxonomy is not None and len(taxonomy):
        st.subheader("Top things users actually want")
        st.caption(
            "Each row below is a cluster of tickets that share the same goal. "
            "Sizes show how many tickets land there; risk averages show how "
            "much money / trust / urgency is at stake."
        )
        human_labels = load_human_labels(run_dir)
        taxonomy = attach_friendly_titles(taxonomy, human_labels)
        rename_map = {
            "want_title": "Want",
            "want_summary": "What this is about",
            "size": "Tickets",
            "share": "Share",
            "top_jobs": "Top jobs",
            "top_emotions": "Top emotions",
            "avg_money_risk": "Money risk",
            "avg_trust_risk": "Trust risk",
            "avg_urgency": "Urgency",
        }
        cols_to_show = [c for c in rename_map if c in taxonomy.columns]
        sub = taxonomy[cols_to_show].head(10).copy()
        if "share" in sub.columns:
            sub["share"] = (sub["share"] * 100).round(1).astype(str) + "%"
        sub = sub.rename(columns=rename_map)
        st.dataframe(sub, use_container_width=True, hide_index=True)

    # ---- Where to go next --------------------------------------------------

    st.subheader("Where to go next")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("##### See the findings")
        st.caption(
            "**What users actually want** — the full ranked taxonomy with "
            "filters and heatmaps.<br><br>"
            "**Where to act first** — opportunities scored by impact.<br><br>"
            "**How managers compare** — note quality leaderboard.",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown("##### Explore the data")
        st.caption(
            "**Map of all tickets** — every ticket as a dot, grouped by meaning.<br><br>"
            "**Find a specific ticket** — search across 6,728 tickets.<br><br>"
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
        if taxonomy is not None and len(taxonomy):
            for _, r in taxonomy.head(10).iterrows():
                title = (r.get("want_title") or r.get("want_label") or "—").replace("<", "&lt;")
                size = int(r.get("size") or 0)
                share = (r.get("share") or 0) * 100
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
<p class="lead">A structured map of what {n_tickets:,} support tickets revealed about
user intent, discovered from ticket text rather than the category column.</p>
<p class="meta">Run: {run_dir.name} &middot; Generated: {timestamp} &middot;
All processing local; no data was sent to any external service.</p>

<div class="kpi">
  <div><div class="v">{n_tickets:,}</div><div class="l">Tickets analyzed</div></div>
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
  <li><strong>Long, evidence-rich notes</strong> are the input every layer of the analysis
      depends on. One manager (Albert) writes notes 2–3× richer than peers, controlling for case mix.</li>
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
Built locally with Python, sentence-transformers (multilingual MiniLM), HDBSCAN, BERTopic, and local Ollama models.
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
        extraction_files = sorted(run_dir.glob("ollama_*_extractions.jsonl"), key=lambda p: p.stat().st_mtime)
        ext_jsonl = extraction_files[-1] if extraction_files else None
        if ext_jsonl is not None and ext_jsonl.exists():
            completed = jsonl_line_count(ext_jsonl)
            status_path = run_dir / "llm_extraction_status.json"
            target = None
            if status_path.exists():
                import json as _json
                try:
                    target = safe_int(
                        _json.loads(status_path.read_text(encoding="utf-8")).get("candidates")
                    )
                except Exception:
                    target = None
            if target:
                st.info(
                    f"Local AI has read **{completed:,} of {target:,}** rich tickets in this run."
                )
            else:
                st.info(f"Local AI has read **{completed:,}** tickets in this run.")

    # ---- Transparency footer ----------------------------------------------

    st.markdown("---")
    st.caption(
        "**About this dashboard.** All data is local. No tickets, prompts, or "
        "model outputs leave the laptop running this dashboard. The AI model "
        "runs on the same machine via Ollama. The pipeline is "
        "open-source — see the engineering docs for how every number on this "
        "page is computed."
    )


# ---- Navigation ----------------------------------------------------------

home = st.Page(
    home_page,
    title="Start here",
    icon=":material/home:",
    default=True,
)

findings = [
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
    "": [home],
    "Findings": findings,
    "Explore the data": explore,
    "Quality checks": quality,
}
if _settings.SHOW_TOOLS_SECTION:
    _nav["Tools"] = tools

pg = st.navigation(_nav)
pg.run()
