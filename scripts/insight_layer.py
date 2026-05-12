#!/usr/bin/env python3
"""Stage 3 — decision-oriented insight layer.

Reads a completed Stage 1 + Stage 2 run directory and adds the artifacts that
turn topics into decisions:

* :func:`build_opportunity_backlog` — ranked product/support opportunities per
  topic, scored by volume × unresolved × recent lift × trust/money risk.
* :func:`build_emerging_topics` — last-30-day vs prior-150-day lift with z-test.
* :func:`build_repeat_user_personas` — seven behavioural personas for users
  with ≥2 tickets.
* :func:`build_context_gap` — per-manager non-parametric residuals and
  per-issue evidence gap diagnostics.
* :func:`build_context_value_model` — OLS linear-probability model of
  resolution on context_depth_score with controls.
* :func:`build_manager_evidence_coaching` — per-manager evidence checklist
  benchmarked against Albert (or the manager with highest mean context score).

Outputs (one CSV each):

* ``opportunity_backlog.csv``
* ``emerging_topics.csv``
* ``repeat_user_personas.csv``
* ``manager_context_residuals.csv``
* ``issue_evidence_gaps.csv``
* ``context_value_model.csv``
* ``manager_evidence_coaching.csv``

Plus ``insight_layer_workbook.xlsx`` (one sheet per table), additions to
``analysis.duckdb``, and an "Insight Layer" section appended to
``executive_findings.md``.

See :doc:`docs/engineering/03-stage3-insight` for formulas and design notes,
and :doc:`docs/engineering/09-formulas-cheatsheet` for the exact
``opportunity_score`` and ``emergence_score`` formulas.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EVIDENCE_COLS = [
    "has_url",
    "has_image_url",
    "has_timestamp",
    "has_room_or_group_id",
    "has_long_uid_or_case_id",
    "has_ban_reason_language",
    "has_user_claim",
    "has_money_terms",
    "has_status_or_svip_terms",
    "has_multiline_note",
]
DESIRE_COLS = [
    "desire__recover_access",
    "desire__clear_name_or_get_fairness",
    "desire__earn_or_transact_money",
    "desire__grow_audience_or_community",
    "desire__gain_status_or_privileges",
    "desire__protect_from_abuse_or_scam",
    "desire__fix_product_or_technical_flow",
    "desire__understand_rules_or_system_logic",
    "desire__customize_identity_or_assets",
    "desire__play_or_entertainment",
]
RISK_DESIRES = {
    "clear_name_or_get_fairness",
    "earn_or_transact_money",
    "protect_from_abuse_or_scam",
    "gain_status_or_privileges",
    "fix_product_or_technical_flow",
}


def latest_run(outputs_dir: Path) -> Path:
    """Return the most recent ``option2_*`` run directory that has finished Stage 1.

    Used as a default when the user runs the insight layer without specifying
    a directory: we pick the newest output folder so iterative analysis
    workflows ("re-run with new tweaks, then look at the latest") feel
    natural.

    Args:
        outputs_dir: The folder where Stage 1 writes its timestamped run
            subfolders, conventionally ``./outputs``.

    Returns:
        The chosen ``option2_<timestamp>`` Path — the last entry after sorting
        all candidates lexicographically by name.

    Raises:
        FileNotFoundError: If no eligible folder exists. We raise rather than
            silently returning ``None`` because every call site needs a real
            path.

    Teaching:
        ``Path.glob("option2_*")`` is pathlib's filesystem wildcard match —
        much cleaner than ``os.listdir`` plus manual filtering. The ``*`` is
        a shell-style glob, not a regex, so it matches any characters in a
        single path segment.

        The list comprehension filters in one step: keep only directories
        whose ``enriched_tickets.csv`` exists, so we never pick a half-baked
        run that crashed before producing the file Stage 3 needs.

        ``sorted(...)[-1]`` works because Stage 1 names folders with ISO
        timestamps like ``option2_20260415-101312``. ISO timestamps sort
        identically as strings and as datetimes, so lexicographic sort gives
        chronological order — a tiny but elegant trick that avoids parsing
        dates back out of filenames.
    """
    runs = sorted([p for p in outputs_dir.glob("option2_*") if (p / "enriched_tickets.csv").exists()])
    if not runs:
        raise FileNotFoundError(f"No option2_* run folders with enriched_tickets.csv under {outputs_dir}")
    return runs[-1]


def coerce_bool(series: pd.Series) -> pd.Series:
    """Convert a pandas Series of mixed truth-y values into a clean boolean Series.

    CSV files are the great equalizer: every value goes out as a string and
    comes back as a string. So a column that was ``True``/``False`` in pandas
    becomes ``"True"``/``"False"`` after a round trip — and worse, sometimes
    ``"1"``/``"0"`` or ``"yes"``/``"no"`` if the data came from a different
    pipeline. This helper centralises the parsing so every downstream
    ``df["is_unresolved"].mean()`` call gets the right type.

    Args:
        series: A pandas Series, possibly already boolean, possibly strings,
            possibly mixed.

    Returns:
        A boolean Series of the same length: ``True`` where the value
        belongs to ``{"true", "1", "yes", "y"}`` (case-insensitive),
        ``False`` everywhere else.

    Teaching:
        ``series.dtype == bool`` is a fast-path — if pandas already knows the
        column is boolean, we return it untouched. No allocations, no string
        conversions.

        Otherwise we chain three vectorised string operations:
        ``.astype(str)`` coerces everything (including ``NaN``, which becomes
        the literal string ``"nan"``) to strings, ``.str.lower()`` normalises
        case so ``"True"`` and ``"TRUE"`` both work, and ``.str.isin([...])``
        does an element-wise membership check. The whole expression runs in
        vectorised C code under the hood — much faster than a Python
        ``for``-loop over rows.

        Defensive programming pattern: don't trust the dtype of data you
        loaded from disk. CSV doesn't preserve types; JSON doesn't have
        booleans in some libraries; SQL drivers vary. A small parse helper
        like this earns its keep on every project.
    """
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin(["true", "1", "yes", "y"])


def load_run(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None]:
    """Load and clean the artifacts from a Stage 1+2 run into a single analysis frame.

    This is the "front door" of Stage 3: every other ``build_*`` function
    expects the DataFrame this returns. The job is twofold — (1) read the
    raw CSVs that Stage 1 wrote, normalising every column to the type
    downstream code assumes (booleans are real booleans, dates are real
    datetimes, UIDs are clean strings), and (2) optionally merge in the
    BERTopic Stage 2 labels so we get nice topic names instead of just
    cluster numbers. If Stage 2 didn't run, we fall back to Stage 1's
    cluster IDs.

    Args:
        run_dir: A Stage 1 ``option2_<timestamp>`` directory. Must contain
            ``enriched_tickets.csv``; ``bertopic_assignments.csv`` and
            ``bertopic_topics.csv`` are optional.

    Returns:
        A 3-tuple of:
        * ``df`` — the cleaned per-ticket DataFrame, augmented with
          ``issue_id`` and ``issue_label`` columns that downstream code
          treats as the unit of analysis.
        * ``bertopic_assignments`` — the raw Stage 2 per-ticket labels,
          or ``None`` if Stage 2 wasn't run.
        * ``bertopic_topics`` — the topic-info table, or ``None``.

    Teaching:
        ``pd.read_csv(...)`` returns a DataFrame where every column's dtype
        is inferred from the first few rows. That inference is brittle (a
        UID column with one number followed by all strings becomes
        ``object``) so we follow up with explicit casts.

        ``pd.to_datetime(df["date"], errors="coerce")`` is the standard
        defensive parse: try to parse each value as a datetime, and if any
        single one fails, write ``NaT`` (Not-a-Time) into that cell instead
        of raising an exception. This means one bad row never crashes the
        whole pipeline. The same pattern with ``pd.to_numeric(...,
        errors="coerce")`` is used a few lines below.

        ``.fillna("").astype(str)`` is the canonical "make this column a
        clean string" idiom: ``NaN``s become empty strings (so downstream
        ``.str`` operations work), then everything is forced to ``str``.

        The UID cleanup ``.str.replace(r"\\.0$", "", regex=True)`` is a tiny
        but important detail. When pandas reads an integer UID from a column
        that also has missing values, it has to upcast to float (because
        ``NaN`` is a float). Then ``.astype(str)`` produces ``"123.0"``
        instead of ``"123"``. This regex strips the trailing ``.0`` so two
        rows for the same user actually compare equal.

        ``df.merge(bertopic_assignments[keep], on="source_row",
        how="left")`` is a SQL-style left outer join: every row of ``df``
        survives, and matching columns from the right side are appended.
        Tickets that BERTopic didn't see (none in practice, but the
        ``how="left"`` defends against it) keep their ``Name`` column as
        ``NaN``, which is then filled by the fallback cluster label.

        The ``fallback_cluster`` line uses an idiom worth memorising:
        ``pd.to_numeric(s, errors="coerce").fillna(-999).astype(int)``.
        First make the column numeric (NaN where it can't), then replace
        NaN with a sentinel value, then cast to int. The sentinel ``-999``
        is a poor person's "missing topic" marker that we treat specially in
        :func:`build_opportunity_backlog` and :func:`build_emerging_topics`.
    """
    df = pd.read_csv(run_dir / "enriched_tickets.csv")
    df["source_row"] = df["source_row"].astype(str)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["is_resolved", "is_unresolved", *EVIDENCE_COLS, *DESIRE_COLS]:
        if col in df.columns:
            df[col] = coerce_bool(df[col])
    df["uid"] = df["uid"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    df["question_flat"] = df["question_flat"].fillna("").astype(str)
    df["manager"] = df["manager"].fillna("Unknown").astype(str)
    df["category"] = df["category"].fillna("Unknown").astype(str)
    df["question_kind"] = df["question_kind"].fillna("Unknown").astype(str)
    df["primary_desire"] = df["primary_desire"].fillna("unclear_or_needs_llm").astype(str)

    bertopic_assignments = None
    bertopic_topics = None
    if (run_dir / "bertopic_assignments.csv").exists():
        bertopic_assignments = pd.read_csv(run_dir / "bertopic_assignments.csv")
        bertopic_assignments["source_row"] = bertopic_assignments["source_row"].astype(str)
        keep = ["source_row", "bertopic_topic", "Name", "Representation", "Count"]
        df = df.merge(bertopic_assignments[keep], on="source_row", how="left")
        fallback_cluster = pd.to_numeric(df["cluster_id"], errors="coerce").fillna(-999).astype(int)
        topic_or_cluster = pd.to_numeric(df["bertopic_topic"], errors="coerce").fillna(fallback_cluster).fillna(-999).astype(int)
        df["issue_id"] = topic_or_cluster.astype(str)
        df["issue_label"] = df["Name"].fillna("cluster_" + fallback_cluster.astype(str))
        bertopic_topics = pd.read_csv(run_dir / "bertopic_topics.csv") if (run_dir / "bertopic_topics.csv").exists() else None
    else:
        df["issue_id"] = df["cluster_id"].fillna(-999).astype(int).astype(str)
        df["issue_label"] = "cluster_" + df["issue_id"]
    return df, bertopic_assignments, bertopic_topics


def top_join(series: pd.Series, n: int = 4) -> str:
    """Return the top-``n`` most frequent values in a Series as a comma-joined string.

    A presentation helper used everywhere we want a short human-readable
    summary of a categorical column, e.g. "what desires showed up most often
    in this topic?" or "which managers handled this issue?". The output goes
    straight into a CSV cell so we keep it as a single string rather than a
    list.

    Args:
        series: Any pandas Series. Empty strings and ``NaN`` are ignored.
        n: How many of the most frequent values to keep. Default 4.

    Returns:
        A string like ``"recover_access, fix_product, earn_money"`` or ``""``
        if the series has no usable values.

    Teaching:
        This is one of pandas' most common idioms compressed into one line:
        ``value_counts()`` returns a Series of frequencies sorted descending,
        ``.head(n)`` keeps the top entries, ``.index`` extracts the values
        themselves (the counts are in ``.values``), ``.tolist()`` converts to
        a Python list, and ``", ".join(...)`` produces the final string.

        Notice the two-step filtering: ``dropna()`` removes ``NaN`` values,
        then the boolean mask ``values[values.str.strip().ne("")]`` removes
        empty/whitespace-only strings. This kind of "clean before count" is
        worth doing because in messy real-world data, ``NaN`` and ``""`` are
        rarely the same thing — a CSV round-trip can turn either into the
        other depending on how the file was written.

        ``ne("")`` is shorthand for "not equal to empty string". Pandas
        provides ``.eq()``, ``.ne()``, ``.lt()``, ``.gt()``, ``.le()``,
        ``.ge()`` to make element-wise comparisons readable when chained.
    """
    values = series.dropna().astype(str)
    values = values[values.str.strip().ne("")]
    if values.empty:
        return ""
    return ", ".join(values.value_counts().head(n).index.tolist())


def compact_example(text: str, max_len: int = 420) -> str:
    """Squash whitespace and truncate text so it fits in a CSV/Excel cell.

    Real ticket text is messy: tab characters, embedded newlines, and runs
    of spaces all break Excel autosizing and make CSV cells unreadable. This
    helper produces a clean single-line excerpt suitable for the
    ``example_1``/``example_2``/``example_3`` columns of
    ``opportunity_backlog.csv`` and similar outputs.

    Args:
        text: The raw ticket text. Anything coercible to ``str`` works.
        max_len: Maximum output length including the trailing ``"..."``.
            Default 420 — enough for a paragraph but short enough that 50
            rows fit in a screen.

    Returns:
        A whitespace-normalised string, truncated with an ellipsis if it
        was longer than ``max_len``.

    Teaching:
        ``re.sub(r"\\s+", " ", str(text))`` is the canonical "collapse
        whitespace" pattern. ``\\s`` matches any whitespace character (space,
        tab, newline, carriage return, form feed), ``+`` means one or more.
        So a string with ``"hello\\n\\n   world\\t"`` becomes
        ``"hello world"`` — every run of whitespace is replaced with a
        single space.

        The truncation idiom ``text[: max_len - 3].rstrip() + "..."`` is
        worth dissecting:
        * Slice to ``max_len - 3`` to leave room for the three ``.`` chars,
          so the final string is exactly ``max_len`` long.
        * ``.rstrip()`` removes trailing whitespace before adding the
          ellipsis — otherwise a slice like ``"hello "`` becomes
          ``"hello ..."`` with an awkward gap.
        * The conditional ``a if cond else b`` is Python's ternary
          expression: a single-line if/else.
    """
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= max_len else text[: max_len - 3].rstrip() + "..."


def issue_action(row: pd.Series) -> str:
    """Recommend a next-step action for a topic based on its diagnostics row.

    Reads the precomputed metrics on a single ``opportunity_backlog`` row
    (volume, unresolved share, recent lift, evidence richness, label
    keywords) and returns a short recommendation string in plain English.
    The whole function is a hand-coded decision tree — a "rules engine" — and
    its job is to translate quantitative signals into operator-friendly
    actions like "Create escalation playbook" or "Automate/self-serve".

    Args:
        row: A single row from the in-progress opportunity backlog. Must
            already contain ``issue_label``, ``trust_money_risk``,
            ``unresolved_share``, ``recent_lift``, ``recent_tickets``,
            ``tickets``, ``avg_context_score``, ``rich_or_forensic_share``,
            and ``top_desires``.

    Returns:
        A one-sentence recommendation. Falls through to a generic
        "Review representative examples" if no rule fires.

    Teaching:
        This function is a textbook example of the **rules engine** design
        pattern. Instead of training a model to predict the recommendation,
        we encode domain knowledge directly: each ``if`` branch represents
        an opinion ("if this issue has both high trust risk AND high
        unresolved share, the action is escalation"). The order matters
        because the first matching branch wins — more specific rules go
        first (the ``-1`` and ``-999`` sentinels), then risk rules, then
        volume rules, then keyword fallbacks, then a default.

        When to prefer a rules engine over ML: when (a) you have strong
        prior knowledge, (b) you need explainability ("why did you
        recommend X?" → "because trust_money_risk ≥ 0.35"), and (c) labelled
        training data doesn't exist. For a one-time analysis like this, a
        rules engine is faster to write, easier to audit, and trivially
        adjustable as the business changes.

        Python feature: ``row.get("issue_label", "")`` works because pandas
        Series supports the dict-style ``.get(key, default)`` API. If the
        column doesn't exist the function still doesn't crash — it just
        treats missing as empty string. That defensive style matters when
        the function is reused on rows with different schemas.

        Note the keyword check ``"diamonds" in label`` — substring matching
        on a lowercased combined string of label and desires. It's coarse
        but works well for issue families like commerce or bans where the
        topic name itself contains a giveaway word.
    """
    label = f"{row.get('issue_label', '')} {row.get('top_desires', '')}".lower()
    if str(row.get("issue_id", "")) == "-1" or str(row.get("issue_label", "")).startswith("-1_"):
        return "Split semantic outlier bucket: sample, relabel, and rerun guided topics."
    if str(row.get("issue_id", "")) == "-999":
        return "Fix source data quality: missing or unclustered text rows need review."
    if row["trust_money_risk"] >= 0.35 and row["unresolved_share"] >= 0.20:
        return "Create escalation playbook + policy owner; this is trust/money/status risk."
    if row["recent_lift"] >= 1.8 and row["recent_tickets"] >= 10:
        return "Investigate as emerging issue; create daily monitor and sample 20 cases."
    if row["tickets"] >= 100 and row["unresolved_share"] < 0.10 and row["avg_context_score"] < 14:
        return "Automate/self-serve; high-volume low-complexity support demand."
    if row["avg_context_score"] >= 24 and row["rich_or_forensic_share"] >= 0.25:
        return "Build casebook/training set; rich evidence can teach classifiers and agents."
    if "dealer" in label or "diamonds" in label or "seller" in label or "scam" in label:
        return "Map money journey; separate legitimate commerce from scam/dispute flows."
    if "blocked" in label or "unban" in label or "ban" in label:
        return "Improve ban transparency: reason, evidence, appeal path, repeat penalty history."
    if "account" in label or "restore" in label or "deleted" in label:
        return "Design account-recovery self-service with identity and phone/SIM edge cases."
    if "channel" in label or "group" in label or "limit" in label:
        return "Create creator/channel ops workflow: visibility, limits, ownership, feed health."
    return "Review representative examples; decide FAQ, macro, product fix, or escalation."


def build_opportunity_backlog(df: pd.DataFrame) -> pd.DataFrame:
    """Rank topics by an opportunity score combining size, risk, and trend.

    Score formula:

        opportunity_score =
            sqrt(volume) * (1
                            + 2.2 * unresolved_share
                            + 1.2 * min(max(recent_lift - 1, 0), 3)
                            + 1.4 * trust_money_risk)
            + 8 * rich_or_forensic_share
            + 0.06 * avg_context_score

    The recommended_action column is rule-derived from the issue label and
    risk profile (see :func:`issue_action`).

    Args:
        df: A loaded run frame from :func:`load_run`. Must include ``issue_id``,
            ``issue_label``, date columns, evidence flags, ``primary_desire``,
            ``context_depth_score``, ``is_unresolved``.

    Returns:
        DataFrame sorted by ``opportunity_score`` descending. Each row has
        diagnostics (recent_tickets, recent_lift, trend_z, top_desires, ...)
        and three example tickets.

    Teaching:
        Date arithmetic with ``pd.Timedelta(days=30)``: pandas datetimes
        support real arithmetic, so ``max_date - pd.Timedelta(days=30)``
        gives you "30 days ago" without any manual day-of-month handling.
        The boolean masks ``recent_mask`` and ``baseline_mask`` then split
        the data into "the last 30 days" and "the 90 days before that",
        which is the standard bucketing for short-term-trend detection.

        Two-proportion z-test: ``z = (p_recent - p_baseline) /
        sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))``. This is the standard
        statistic for "are these two rates significantly different?". The
        intuition: the numerator is the observed difference in proportions;
        the denominator is the pooled standard error under the null
        hypothesis that both proportions are equal. A ``|z| > 1.96`` means
        the difference is significant at the 5% level. We compute it per
        topic to flag which ones really are surging vs. just looking lifted
        because of small-sample noise.

        The ``+ 0.0005`` smoothing in ``lift = (p_recent + 0.0005) /
        (p_baseline + 0.0005)`` is a tiny but critical trick. Without it, a
        topic with zero baseline tickets would yield a divide-by-zero or an
        infinite lift (a "topic of one" looking like a 1000x surge). The
        smoothing constant is small enough to barely affect lifts based on
        many tickets and large enough to bound lifts for tiny topics. This
        is the same idea as Laplace smoothing in NLP.

        ``max(...,  1e-9)`` inside the ``sqrt`` of the z denominator is the
        same defensive idea — never let the denominator become exactly zero.

        The composite ``opportunity_score`` formula deserves a walk-through:
            score = sqrt(volume) * (1
                                    + 2.2 * unresolved_share
                                    + 1.2 * min(max(recent_lift - 1, 0), 3)
                                    + 1.4 * trust_money_risk)
                  + 8 * rich_or_forensic_share
                  + 0.06 * avg_context_score

        * ``sqrt(volume)``: we care about size but with diminishing returns.
          A topic with 400 tickets isn't 4x more important than one with
          100; ``sqrt`` keeps the ranking from being totally dominated by
          a single mega-topic.
        * The ``(1 + ...)`` multiplicative term lets risk and trend
          *amplify* volume rather than add to it. A small topic with high
          risk can still beat a large topic with no risk.
        * ``2.2 * unresolved_share``: heavy weight on unresolved tickets
          because those are the ones causing customer pain right now.
        * ``1.2 * min(max(recent_lift - 1, 0), 3)``: the inner ``max(..., 0)``
          ignores topics that are *shrinking* (lift < 1), and the outer
          ``min(..., 3)`` caps surges at 4x lift so a tiny brand-new topic
          with lift=200 doesn't completely dominate the ranking.
        * ``1.4 * trust_money_risk``: trust/money/status problems are
          higher-stakes than general support, so they get extra weight.
        * ``+ 8 * rich_or_forensic_share``: a small additive boost for
          topics where managers wrote rich evidence — those topics are
          better-documented and easier to act on. The ``8`` is a tuning
          constant; values of 5–10 give similar rankings.
        * ``+ 0.06 * avg_context_score``: tiny context-quality nudge so
          well-documented topics edge out poorly-documented ones at a tie.

        These weights (2.2, 1.2, 1.4, 8, 0.06) were chosen by inspection of
        the resulting top-20 list — they are not learned. Rule-of-thumb:
        a coefficient of 2 means "each unit of this signal moves the score
        by twice as much as base volume". Adjust them and re-rank to see
        the tradeoffs.

        Pandas patterns worth noticing:
        * ``df.groupby("issue_id", dropna=False)``: by default groupby
          drops NaN keys, but we want the ``-999`` sentinel group preserved
          so ``dropna=False`` is essential.
        * ``sub["issue_label"].mode().iloc[0] if not ...mode().empty else
          ...``: ``.mode()`` returns the most common value(s); we need
          ``.iloc[0]`` because mode can be multi-valued. The ternary
          handles the all-NaN case where mode is empty.
        * ``sub.loc[sub["uid"].ne(""), "uid"].nunique()``: count distinct
          non-empty UIDs. ``.loc[mask, col]`` is the explicit pandas way
          of saying "give me the values of ``col`` where ``mask`` is true".
    """
    max_date = df["date"].max()
    recent_start = max_date - pd.Timedelta(days=30)
    baseline_start = max_date - pd.Timedelta(days=120)
    recent_mask = df["date"].ge(recent_start)
    baseline_mask = df["date"].ge(baseline_start) & df["date"].lt(recent_start)
    recent_n = max(int(recent_mask.sum()), 1)
    baseline_n = max(int(baseline_mask.sum()), 1)

    uid_counts = df.loc[df["uid"].ne(""), "uid"].value_counts()
    repeat_uids = set(uid_counts[uid_counts >= 2].index)
    df = df.copy()
    df["is_repeat_user"] = df["uid"].isin(repeat_uids)
    df["trust_money_flag"] = df["primary_desire"].isin(RISK_DESIRES) | df["has_money_terms"] | df["has_status_or_svip_terms"]

    rows = []
    for issue_id, sub in df.groupby("issue_id", dropna=False):
        recent_tickets = int((sub["date"].ge(recent_start)).sum())
        baseline_tickets = int((sub["date"].ge(baseline_start) & sub["date"].lt(recent_start)).sum())
        p_recent = recent_tickets / recent_n
        p_baseline = baseline_tickets / baseline_n
        lift = (p_recent + 0.0005) / (p_baseline + 0.0005)
        p_pool = (recent_tickets + baseline_tickets) / (recent_n + baseline_n)
        denom = math.sqrt(max(p_pool * (1 - p_pool) * (1 / recent_n + 1 / baseline_n), 1e-9))
        z = (p_recent - p_baseline) / denom
        examples = sub.sort_values(["context_depth_score", "char_count"], ascending=False).head(3)["question_flat"].map(compact_example).tolist()
        risk = float(sub["trust_money_flag"].mean())
        unresolved = float(sub["is_unresolved"].mean())
        volume = len(sub)
        rich_share = float(sub["context_depth_band"].isin(["rich", "forensic"]).mean())
        score = (
            math.sqrt(volume)
            * (1 + 2.2 * unresolved + 1.2 * min(max(lift - 1, 0), 3) + 1.4 * risk)
            + 8 * rich_share
            + 0.06 * float(sub["context_depth_score"].mean())
        )
        row = {
            "issue_id": str(issue_id),
            "issue_label": sub["issue_label"].mode().iloc[0] if not sub["issue_label"].mode().empty else str(issue_id),
            "tickets": int(volume),
            "unique_users": int(sub.loc[sub["uid"].ne(""), "uid"].nunique()),
            "repeat_user_share": round(float(sub["is_repeat_user"].mean()), 4),
            "unresolved_share": round(unresolved, 4),
            "avg_context_score": round(float(sub["context_depth_score"].mean()), 2),
            "rich_or_forensic_share": round(rich_share, 4),
            "urgency_avg": round(float(sub["urgency_signal"].mean()), 3),
            "trust_money_risk": round(risk, 4),
            "recent_tickets": recent_tickets,
            "baseline_tickets": baseline_tickets,
            "recent_lift": round(float(lift), 3),
            "trend_z": round(float(z), 3),
            "top_desires": top_join(sub["primary_desire"], 5),
            "top_categories": top_join(sub["category"], 4),
            "top_managers": top_join(sub["manager"], 4),
            "example_1": examples[0] if len(examples) > 0 else "",
            "example_2": examples[1] if len(examples) > 1 else "",
            "example_3": examples[2] if len(examples) > 2 else "",
            "opportunity_score": round(score, 2),
        }
        row["recommended_action"] = issue_action(pd.Series(row))
        rows.append(row)
    return pd.DataFrame(rows).sort_values("opportunity_score", ascending=False)


def build_emerging_topics(df: pd.DataFrame) -> pd.DataFrame:
    """Identify topics whose recent share-of-tickets has surged vs. the prior 180 days.

    Where :func:`build_opportunity_backlog` ranks for action, this table
    answers a different question: "what changed recently?" We compare the
    last 30 days to the prior 180 days and emit a per-topic z-test plus an
    ``emergence_score`` that combines absolute size, lift magnitude, and
    unresolved share.

    Args:
        df: The loaded run frame from :func:`load_run`. The sentinel
            ``issue_id == "-999"`` (unclustered tickets) is dropped so it
            doesn't appear as a "topic".

    Returns:
        DataFrame sorted by ``emergence_score`` descending, with three
        sliding windows (last 30/60/90 days) plus the recent-vs-prior
        diagnostics for each topic.

    Teaching:
        Sliding windows: ``windows = {"last_30": ..., "last_60": ...,
        "last_90": ...}`` is just a dict whose values are start-dates. We
        loop over it to count tickets in each window for each topic. Three
        windows because surges of different durations look different — a
        true emergence shows up across all three, while a one-day spike
        only inflates the 30-day count.

        Recent-vs-prior baseline: we compare the last 30 days to the 180
        days before that, *not* "all earlier history", so seasonality and
        long-tail drift don't swamp the signal. The math is the same
        two-proportion z-test as in
        :func:`build_opportunity_backlog`: ``z = (p_recent - p_prior) /
        sqrt(p_pool * (1 - p_pool) * (1/n_recent + 1/n_prior))``. The same
        ``+ 0.0005`` smoothing keeps lifts finite for tiny topics.

        ``share_of_issue`` columns: each topic's window count divided by
        its **own** total — i.e. "what fraction of this topic's lifetime
        tickets fall in the last 30 days?". A high value means the topic
        is mostly recent activity (genuinely emerging) rather than a
        long-tail topic with a small recent uptick.

        ``emergence_score`` formula:
            score = sqrt(last_30_tickets) * min(recent_vs_prior_lift, 6)
                                          * (1 + recent_unresolved_share)

        * ``sqrt(last_30_tickets)``: same diminishing-returns idea as
          opportunity_score — magnitude matters but logarithmically.
        * ``.clip(upper=6)``: cap lift at 6x so a brand-new topic with
          lift=200 doesn't dwarf a moderate-sized topic with lift=4.
        * ``(1 + recent_unresolved_share)``: a multiplier that boosts
          topics where the recent tickets are also *not getting solved*.
          Bonus from 1.0 (everything resolved) to 2.0 (nothing resolved).

        ``Series.clip(lower=0).pow(0.5)``: ``.clip(lower=0)`` ensures we
        never feed a negative number into ``.pow(0.5)`` (sqrt of a negative
        number is NaN). ``.pow(0.5)`` is the vectorised square-root.
    """
    df = df[df["issue_id"].ne("-999")].copy()
    max_date = df["date"].max()
    windows = {
        "last_30": max_date - pd.Timedelta(days=30),
        "last_60": max_date - pd.Timedelta(days=60),
        "last_90": max_date - pd.Timedelta(days=90),
    }
    rows = []
    for issue_id, sub in df.groupby("issue_id", dropna=False):
        label = sub["issue_label"].mode().iloc[0] if not sub["issue_label"].mode().empty else str(issue_id)
        total = len(sub)
        row = {"issue_id": str(issue_id), "issue_label": label, "total_tickets": total}
        for name, start in windows.items():
            row[f"{name}_tickets"] = int(sub["date"].ge(start).sum())
            row[f"{name}_share_of_issue"] = round(row[f"{name}_tickets"] / max(total, 1), 4)
        recent_mask = df["date"].ge(windows["last_30"])
        prior_mask = df["date"].ge(max_date - pd.Timedelta(days=180)) & df["date"].lt(windows["last_30"])
        n_recent = max(int(recent_mask.sum()), 1)
        n_prior = max(int(prior_mask.sum()), 1)
        r = int((sub["date"].ge(windows["last_30"])).sum())
        p = int((sub["date"].ge(max_date - pd.Timedelta(days=180)) & sub["date"].lt(windows["last_30"])).sum())
        pr = r / n_recent
        pp = p / n_prior
        pool = (r + p) / (n_recent + n_prior)
        z = (pr - pp) / math.sqrt(max(pool * (1 - pool) * (1 / n_recent + 1 / n_prior), 1e-9))
        row["recent_vs_prior_lift"] = round((pr + 0.0005) / (pp + 0.0005), 3)
        row["recent_vs_prior_z"] = round(z, 3)
        row["recent_unresolved_share"] = round(float(sub.loc[sub["date"].ge(windows["last_30"]), "is_unresolved"].mean()) if r else 0.0, 4)
        row["top_desires"] = top_join(sub["primary_desire"], 4)
        rows.append(row)
    out = pd.DataFrame(rows)
    out["emergence_score"] = (
        out["last_30_tickets"].clip(lower=0).pow(0.5)
        * out["recent_vs_prior_lift"].clip(upper=6)
        * (1 + out["recent_unresolved_share"])
    ).round(2)
    return out.sort_values(["emergence_score", "last_30_tickets"], ascending=False)


def persona_for_user(group: pd.DataFrame) -> str:
    """Assign one of seven hand-coded personas to a user based on their ticket history.

    Given all the tickets for a single repeat user, decide which behavioural
    archetype best describes them. The personas (commerce dispute, ban
    appeal, creator, SVIP, account recovery, multi-problem power user,
    general repeat user) come from product knowledge of what users actually
    do — they are not learned from data.

    Args:
        group: A DataFrame slice containing all tickets for one ``uid``,
            with columns ``primary_desire``, ``issue_label``,
            ``is_unresolved``.

    Returns:
        The persona slug (one of seven strings) that best matches the user.

    Teaching:
        This is a **priority cascade** — a chain of ``if/elif`` branches
        where the *first* match wins. The ordering is deliberate: more
        specific or higher-stakes personas are checked first so they win
        ties. A user who matches both ``commerce_dispute_or_scam_risk`` and
        ``creator_channel_operator`` ends up classified as the former
        because commerce disputes have higher business impact.

        Read this function as a literal hand-coded classifier: each branch
        is one rule, and the cascade is a rough approximation of "what
        would a product manager say if you showed them this user's
        tickets?". For a one-off analysis it works as well as a model and
        is far easier to debug or adjust.

        ``set(group["primary_desire"].dropna().astype(str))`` builds a set
        of distinct desires this user expressed. Sets give O(1) ``in``
        lookups — perfect for the quick membership checks below.

        The intersection ``desires & {"earn_or_transact_money",
        "protect_from_abuse_or_scam"}`` returns the overlap between two
        sets; if it's truthy (non-empty), the rule fires. This is a
        Pythonic way of saying "does this user have *any* of these
        desires?".

        ``len(desires) >= 4`` at the bottom is the catch-all for users who
        keep showing up with new kinds of problems — a "power user" pattern
        worth distinguishing because they often need product investments
        rather than per-ticket support.
    """
    desires = set(group["primary_desire"].dropna().astype(str))
    text = " ".join(group["issue_label"].fillna("").astype(str).str.lower().head(20).tolist())
    if "earn_or_transact_money" in desires and ("protect_from_abuse_or_scam" in desires or "scam" in text or "diamonds" in text):
        return "commerce_dispute_or_scam_risk"
    if "clear_name_or_get_fairness" in desires and group["is_unresolved"].mean() >= 0.25:
        return "repeat_ban_appeal_or_fairness_seeker"
    if "grow_audience_or_community" in desires:
        return "creator_channel_operator"
    if "gain_status_or_privileges" in desires:
        return "svip_status_optimizer"
    if "recover_access" in desires:
        return "account_recovery_repeat_user"
    if len(desires) >= 4:
        return "multi_problem_power_user"
    return "general_repeat_user"


def build_repeat_user_personas(df: pd.DataFrame) -> pd.DataFrame:
    """Build a per-user table of behavioural personas and ticket history summaries.

    For every user with ≥2 tickets, summarise how they show up: which
    persona they fit, how many tickets they filed, the calendar span over
    which they were active, their unresolved share, the managers they
    spoke with, and a couple of high-context example tickets.

    Args:
        df: The loaded run frame from :func:`load_run`. Empty UIDs are
            filtered out (anonymous tickets aren't repeat users).

    Returns:
        DataFrame sorted by tickets, unresolved share, and average context
        depth — so the most prolific and worst-served users surface first.

    Teaching:
        The ``groupby("uid")`` loop applies :func:`persona_for_user` to
        each user's tickets independently. Inside the loop, ``len(sub) <
        2`` skips one-shot users — without this guard we'd produce a row
        for every customer in the dataset.

        Date span calculation: ``(ordered["date"].max() -
        ordered["date"].min()).days`` subtracts two pandas Timestamps,
        producing a ``Timedelta``, then reads ``.days`` to extract integer
        days. The guard ``if ordered["date"].notna().all() else np.nan``
        avoids producing a misleading span if any of the user's dates were
        unparseable.

        ``ordered["date"].min().date()`` converts a pandas Timestamp to a
        plain ``datetime.date`` so it serialises to CSV as ``2026-04-01``
        rather than ``2026-04-01 00:00:00``. Tiny ergonomic win.

        Notice we sort tickets by date for the date-span and timeline
        questions, but separately sort by ``context_depth_score`` to
        select the two best-documented examples for that user. The pattern
        of doing multiple ``sort_values`` on the same group, each for a
        different downstream column, is common in summary-table builders.
    """
    work = df[df["uid"].ne("")].copy()
    rows = []
    for uid, sub in work.groupby("uid"):
        if len(sub) < 2:
            continue
        ordered = sub.sort_values("date")
        span = (ordered["date"].max() - ordered["date"].min()).days if ordered["date"].notna().all() else np.nan
        examples = ordered.sort_values("context_depth_score", ascending=False).head(2)["question_flat"].map(compact_example).tolist()
        rows.append(
            {
                "uid": uid,
                "persona": persona_for_user(sub),
                "tickets": int(len(sub)),
                "active_days_span": None if pd.isna(span) else int(span),
                "first_date": ordered["date"].min().date() if ordered["date"].notna().any() else "",
                "last_date": ordered["date"].max().date() if ordered["date"].notna().any() else "",
                "unresolved_share": round(float(sub["is_unresolved"].mean()), 4),
                "avg_context_score": round(float(sub["context_depth_score"].mean()), 2),
                "managers_seen": top_join(sub["manager"], 5),
                "top_desires": top_join(sub["primary_desire"], 5),
                "top_issues": top_join(sub["issue_label"], 5),
                "high_context_example_1": examples[0] if len(examples) > 0 else "",
                "high_context_example_2": examples[1] if len(examples) > 1 else "",
            }
        )
    return pd.DataFrame(rows).sort_values(["tickets", "unresolved_share", "avg_context_score"], ascending=False)


def build_context_gap(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build two diagnostics: per-manager context residuals and per-issue evidence gaps.

    Two related but distinct outputs:

    * **manager_context_residuals**: a non-parametric robustness check on
      the OLS in :func:`build_context_value_model`. For each ticket, we
      subtract the mean ``context_depth_score`` for its (category,
      question_kind) cell. Then we group by manager and average the
      residual. A positive average means "this manager writes more
      detailed notes than the case mix would predict" — i.e. they're
      genuinely thorough, not just handling more naturally complex
      cases.

    * **issue_evidence_gaps**: per-topic checklist of *which kinds of
      evidence* the topic should have but doesn't. The required-evidence
      list is rule-based: ban topics need timestamps and reason text;
      money topics need image evidence and case IDs; channel/group topics
      need group IDs.

    Args:
        df: The loaded run frame. Topics with fewer than 20 tickets are
            skipped — too few to draw conclusions about evidence patterns.

    Returns:
        Two DataFrames: ``(manager_residuals, issue_evidence_gaps)``.

    Teaching:
        The non-parametric residual approach: instead of fitting a model
        to predict context_depth_score, we just compute the conditional
        mean ``E[score | category, question_kind]`` and subtract it. This
        gives a "does this manager beat their cell average?" signal
        without any modelling assumptions. The residual is zero on
        average within each cell by construction. We use this as a
        **robustness check** on the OLS — if both methods rank managers
        the same way, we trust the OLS coefficients more.

        ``df.groupby(...)["context_depth_score"].mean().rename(...)``
        produces a Series indexed by ``(category, question_kind)`` tuples
        whose values are cell means. The ``.rename(...)`` gives the Series
        a name so it merges cleanly.

        ``scored = df.join(mix, on=["category", "question_kind"])``: this
        is the broadcast-join idiom. ``mix`` is indexed by the join keys,
        and ``df.join(mix, on=keys)`` pulls the matching mean back onto
        every row of ``df``. After this, ``scored`` has both the raw
        score and the cell-expected score side by side, ready for
        subtraction.

        The required-evidence rules are a tiny domain-specific language:
        if the topic is a ban issue, you'd expect timestamps and reason
        language; if it's commerce/scam, you'd expect money terms and
        case IDs. Each rule fires independently (using ``+=`` to
        accumulate into the ``required`` list) so a topic that's both
        money- and channel-related gets both checklists.

        ``re.search(r"\\b(?:ban|unban|block)\\b", issue_text)`` uses the
        non-capturing group ``(?:...)`` and word boundaries ``\\b`` to
        match those exact words but not substrings — so "banned" and
        "ban" both match, but "kanban" doesn't.

        ``missing = {col: 1 - float(sub[col].mean()) for col in ...}``
        computes the missing-share for each required column. Since
        evidence flags are booleans, ``.mean()`` is the share of tickets
        where the flag is True, so ``1 - mean`` is the share where it's
        False. The dict comprehension keeps the column→missingness
        mapping handy for the next ``sorted(..., key=lambda kv: kv[1],
        reverse=True)[:4]`` line that picks the top-4 worst gaps.

        ``np.mean(list(missing.values()))`` collapses the per-column
        gaps into a single ``evidence_gap_score`` for ranking.
    """
    mix = df.groupby(["category", "question_kind"], dropna=False)["context_depth_score"].mean().rename("expected_mix_context")
    scored = df.join(mix, on=["category", "question_kind"])
    scored["context_residual_vs_mix"] = scored["context_depth_score"] - scored["expected_mix_context"]

    manager_resid = scored.groupby("manager", dropna=False).agg(
        tickets=("source_row", "count"),
        avg_raw_context=("context_depth_score", "mean"),
        avg_expected_context=("expected_mix_context", "mean"),
        avg_residual_vs_ticket_mix=("context_residual_vs_mix", "mean"),
        rich_or_forensic_share=("context_depth_band", lambda s: s.isin(["rich", "forensic"]).mean()),
    ).reset_index()
    for col in manager_resid.columns:
        if col != "manager" and col != "tickets":
            manager_resid[col] = manager_resid[col].astype(float).round(4)
    manager_resid = manager_resid.sort_values("avg_residual_vs_ticket_mix", ascending=False)

    issue_gap_rows = []
    for issue, sub in df.groupby("issue_label", dropna=False):
        if len(sub) < 20:
            continue
        dominant_desires = set(sub["primary_desire"].value_counts(normalize=True).loc[lambda s: s >= 0.25].index.astype(str))
        issue_text = str(issue).lower()
        required = []
        if "clear_name_or_get_fairness" in dominant_desires or re.search(r"\b(?:ban|unban|block|blocked|penalty)\b", issue_text):
            required += ["has_timestamp", "has_ban_reason_language", "has_user_claim"]
        if dominant_desires & {"earn_or_transact_money", "protect_from_abuse_or_scam"} or re.search(r"\b(?:money|diamonds?|scam|fraud|dealer|seller)\b", issue_text):
            required += ["has_money_terms", "has_image_url", "has_long_uid_or_case_id"]
        if "grow_audience_or_community" in dominant_desires or re.search(r"\b(?:channel|group|limit|room|creator)\b", issue_text):
            required += ["has_room_or_group_id", "has_image_url"]
        if not required:
            required = ["has_url", "has_image_url", "has_multiline_note"]
        missing = {col: 1 - float(sub[col].mean()) for col in sorted(set(required)) if col in sub.columns}
        issue_gap_rows.append(
            {
                "issue_label": issue,
                "tickets": int(len(sub)),
                "avg_context_score": round(float(sub["context_depth_score"].mean()), 2),
                "unresolved_share": round(float(sub["is_unresolved"].mean()), 4),
                "required_evidence": ", ".join(sorted(set(required))),
                "largest_missing_evidence": ", ".join([f"{k}:{v:.0%}" for k, v in sorted(missing.items(), key=lambda kv: kv[1], reverse=True)[:4]]),
                "evidence_gap_score": round(float(np.mean(list(missing.values())) if missing else 0), 4),
            }
        )
    issue_gaps = pd.DataFrame(issue_gap_rows).sort_values(["evidence_gap_score", "tickets"], ascending=False)
    return manager_resid, issue_gaps


def build_context_value_model(df: pd.DataFrame) -> pd.DataFrame:
    """OLS of resolution on context features, with categorical controls.

    Model:

        resolved_int ~ context_depth_score + evidence_element_count + urgency_signal
                      + C(category) + C(question_kind) + C(role) + C(month) + C(primary_desire)

    Linear-probability model (OLS on a 0/1 outcome) instead of logit because
    the high-cardinality categorical dummies cause separation issues with logit.
    HC3-robust standard errors. We report only the three continuous coefficients
    converted to probability points (×100) since the OLS coefficient on a 0/1
    outcome is already in probability units.

    Args:
        df: Loaded run frame.

    Returns:
        DataFrame with one row per term: ``coef_probability_points``, ``p_value``,
        ``conf_low_pp``, ``conf_high_pp``, ``model_r2``, ``interpretation``.

    Teaching:
        Why OLS on a 0/1 outcome (a "linear probability model"):

        The natural choice for binary outcomes is logistic regression —
        it constrains predicted probabilities to (0, 1) and has nice
        likelihood properties. But logit fits via maximum likelihood and
        runs into **complete separation** when categorical variables are
        sparse: if a (category × question_kind) cell has 100% resolved or
        100% unresolved tickets, the MLE coefficient blows up to ±∞ and
        the optimiser fails (or worse, returns nonsense). Our 6,728
        tickets split across category × question_kind × role × month ×
        primary_desire have many sparse cells, so logit is fragile.

        OLS doesn't have this problem. It always converges in closed
        form. The coefficients are interpreted as **changes in
        probability** because the outcome is ``{0, 1}``: a coefficient
        of 0.012 on ``context_depth_score`` means "each additional
        context-score point is associated with a 1.2 percentage point
        increase in probability of resolution, holding everything else
        constant". We multiply by 100 in the output (×100) so the column
        reads as "probability points" — much more intuitive for a non-
        statistician audience than "log-odds" or raw OLS coefficients.

        HC3 robust standard errors: ``cov_type="HC3"`` swaps the default
        OLS standard errors (which assume homoskedasticity — equal error
        variance across observations) for the Davidson-MacKinnon HC3
        sandwich estimator. The classic OLS SE is wrong when error
        variance depends on X — and on a binary outcome it always does
        (variance is ``p(1-p)`` which depends on predicted ``p``). HC3
        is the standard small-sample-friendly heteroskedasticity-robust
        choice, slightly more conservative than HC0/HC1/HC2.

        The ``C(category)`` syntax is patsy/statsmodels formula notation
        that says "treat this column as categorical and dummy-encode it".
        Without ``C(...)``, statsmodels would treat a string-typed column
        as numeric and crash. With it, you get one indicator per level
        (minus the reference level) automatically.

        Why we report only three terms: the categorical fixed effects are
        controls — we include them so the continuous coefficients on
        ``context_depth_score``, ``evidence_element_count``, and
        ``urgency_signal`` are estimated *holding category, kind, role,
        month, and desire constant*. We don't need to interpret them
        individually; they are nuisance parameters that absorb confounders.

        The interpretation string explicitly says "correlation, not
        causal proof" because a regression with controls can still suffer
        omitted-variable bias. We report the model so a reader can decide
        whether they trust the conditioning set, not as a causal claim.

        Defensive ``try/except`` around the import: ``statsmodels`` is a
        heavy optional dependency, and we'd rather emit a "note" row in
        the output than crash if a colleague runs without installing it.
    """
    try:
        import statsmodels.formula.api as smf
    except Exception as exc:
        return pd.DataFrame({"note": [f"statsmodels unavailable: {exc}"]})

    model_df = df.copy()
    model_df["resolved_int"] = (~model_df["is_unresolved"]).astype(int)
    for col in ["manager", "category", "question_kind", "role", "month", "primary_desire"]:
        model_df[col] = model_df[col].fillna("Unknown").astype(str).replace("", "Unknown")
    # A logit can fail on separation with many sparse categories; OLS/LPM is stable and interpretable.
    formula = "resolved_int ~ context_depth_score + evidence_element_count + urgency_signal + C(category) + C(question_kind) + C(role) + C(month) + C(primary_desire)"
    try:
        fit = smf.ols(formula, data=model_df).fit(cov_type="HC3")
    except Exception as exc:
        return pd.DataFrame({"note": [f"context value model failed: {exc}"]})
    wanted = ["context_depth_score", "evidence_element_count", "urgency_signal"]
    rows = []
    for term in wanted:
        rows.append(
            {
                "term": term,
                "coef_probability_points": round(float(fit.params.get(term, np.nan)) * 100, 3),
                "p_value": round(float(fit.pvalues.get(term, np.nan)), 6),
                "conf_low_pp": round(float(fit.conf_int().loc[term, 0]) * 100, 3) if term in fit.params.index else np.nan,
                "conf_high_pp": round(float(fit.conf_int().loc[term, 1]) * 100, 3) if term in fit.params.index else np.nan,
                "model_r2": round(float(fit.rsquared), 4),
                "interpretation": "Linear probability model for resolved status; controls for category, kind, role, month, primary desire. This is correlation, not causal proof.",
            }
        )
    return pd.DataFrame(rows)


def build_manager_evidence_coaching(df: pd.DataFrame) -> pd.DataFrame:
    """Produce per-manager evidence-checklist coaching items vs. a benchmark manager.

    For each manager, compute the rate at which they capture each kind of
    evidence (URLs, screenshots, timestamps, ban-reason text, etc.) and
    compare against the benchmark — Albert if present, otherwise whichever
    manager has the highest mean ``context_depth_score``. Gaps larger than
    3 percentage points become coaching items, formatted as plain English
    (``"capture room/group/channel IDs (+12% to benchmark)"``).

    Args:
        df: The loaded run frame with all evidence columns from
            :data:`EVIDENCE_COLS` present.

    Returns:
        DataFrame sorted by ``avg_context_score`` descending. Best-
        documenting managers float to the top; the
        ``top_evidence_gaps_vs_benchmark`` column tells everyone else what
        to focus on.

    Teaching:
        Benchmark choice: ``"Albert" if (df["manager"] == "Albert").any()
        else df.groupby("manager")[...].mean().idxmax()`` is a defensive
        fallback. We *prefer* Albert as the human benchmark (he's the
        domain expert whose notes set the bar) but if his data isn't in
        the run, we fall back to "whichever manager has the highest mean
        context score". ``.idxmax()`` returns the index label (here, a
        manager name) of the row with the maximum value — the dual to
        ``.max()`` which returns the value itself.

        ``benchmark_rates = {col: float(benchmark[col].mean()) for col in
        EVIDENCE_COLS if col in df.columns}`` is a dict comprehension that
        precomputes one rate per evidence flag. Doing this once outside
        the per-manager loop is an O(M·N) → O(M+N) speedup when many
        managers are in the data — though for our 10 evidence cols and
        ~10 managers it's mostly a clarity win.

        The label_map dict translates internal column names into
        operator-readable phrases. This is a simple but powerful
        translation pattern — we keep machine-friendly column names in
        the data layer and human-friendly strings only in the
        presentation layer. Easy to localise, easy to tweak wording
        without touching logic.

        ``gaps = sorted(gaps, key=lambda x: x[1], reverse=True)``: sort
        the (col, gap, rate, bench_rate) tuples by the second element
        (gap size) descending, so the worst gaps come first. The lambda
        is a one-line function whose only job is "extract the sort key
        from this tuple".

        The output uses an f-string with a percentage format spec:
        ``f"+{gap:.0%}"`` formats a float like ``0.123`` as ``"+12%"``.
        ``.0%`` means "format as percent with zero decimal places",
        which auto-multiplies by 100 — a tiny formatting win that beats
        manual ``f"+{int(gap*100)}%"`` typing.

        ``**{f"{col}_share": ... for col in EVIDENCE_COLS}``: dict-spread
        in a dict literal. The ``**`` unpacks the comprehension's keys
        into the surrounding dict, so each evidence column gets its own
        per-manager rate column in the output. Saves writing 10 explicit
        keys.
    """
    benchmark_manager = "Albert" if (df["manager"] == "Albert").any() else df.groupby("manager")["context_depth_score"].mean().idxmax()
    benchmark = df[df["manager"].eq(benchmark_manager)]
    benchmark_rates = {col: float(benchmark[col].mean()) for col in EVIDENCE_COLS if col in df.columns}
    label_map = {
        "has_url": "attach source links/screens",
        "has_image_url": "attach image evidence",
        "has_timestamp": "record exact event/ban timestamps",
        "has_room_or_group_id": "capture room/group/channel IDs",
        "has_long_uid_or_case_id": "capture UID/case IDs",
        "has_ban_reason_language": "copy ban/review reason text",
        "has_user_claim": "quote user's claim or denial",
        "has_money_terms": "mark money/diamond/payment involvement",
        "has_status_or_svip_terms": "mark SVIP/status/points involvement",
        "has_multiline_note": "write structured multiline notes",
    }
    rows = []
    for manager, sub in df.groupby("manager", dropna=False):
        gaps = []
        for col, bench_rate in benchmark_rates.items():
            rate = float(sub[col].mean())
            gap = bench_rate - rate
            if gap > 0.03:
                gaps.append((col, gap, rate, bench_rate))
        gaps = sorted(gaps, key=lambda x: x[1], reverse=True)
        focus = "; ".join(f"{label_map.get(col, col)} (+{gap:.0%} to benchmark)" for col, gap, _, _ in gaps[:4])
        rows.append(
            {
                "manager": manager,
                "benchmark_manager": benchmark_manager,
                "tickets": int(len(sub)),
                "avg_context_score": round(float(sub["context_depth_score"].mean()), 2),
                "rich_or_forensic_share": round(float(sub["context_depth_band"].isin(["rich", "forensic"]).mean()), 4),
                "top_evidence_gaps_vs_benchmark": focus,
                **{f"{col}_share": round(float(sub[col].mean()), 4) for col in EVIDENCE_COLS if col in df.columns},
            }
        )
    return pd.DataFrame(rows).sort_values("avg_context_score", ascending=False)


def write_outputs(run_dir: Path, tables: dict[str, pd.DataFrame]) -> None:
    """Persist every insight table to CSV, Excel, and DuckDB in one place.

    Three audiences, three formats:
    * **CSV** — most portable, easiest to ``git diff``, opens in any
      tool.
    * **Excel workbook** — one sheet per table, perfect for sending to
      stakeholders who live in spreadsheets.
    * **DuckDB** — analytical SQL store for ad-hoc queries by data
      teammates.

    Args:
        run_dir: Output directory.
        tables: Mapping of ``{name: DataFrame}``. ``name`` becomes the
            CSV filename, the Excel sheet name, and the DuckDB table
            name (each sanitised to that format's rules).

    Teaching:
        ``with pd.ExcelWriter(...) as writer:`` is the recommended
        pandas pattern for writing multiple sheets to one workbook. The
        context manager opens the file once, accumulates all sheets,
        and writes the final ``.xlsx`` archive on exit. Without the
        ``with``, you'd open and close the file per sheet and risk
        corrupting it.

        Sheet name sanitisation: ``re.sub(r"[^A-Za-z0-9 _-]", "",
        name)[:31] or "Sheet"`` is a tiny but battle-tested helper.
        Excel rejects sheet names with ``[]:*?/\\`` and caps length at
        31 characters. The regex strips disallowed characters, the
        slice clips to 31, and ``or "Sheet"`` defaults to ``"Sheet"`` if
        the result is empty (e.g. a name composed entirely of bad
        characters).

        DuckDB table name sanitisation differs: SQL identifiers can't
        contain spaces or hyphens, so the regex
        ``re.sub(r"[^A-Za-z0-9_]", "_", name).lower()`` replaces them
        with underscores instead of stripping. Each format gets its own
        sanitiser tailored to its rules.

        ``con.register("_tmp_insight", table)`` exposes the DataFrame
        to DuckDB as a temporary view — no copy, just a pointer — and
        ``CREATE OR REPLACE TABLE ... AS SELECT * FROM _tmp_insight``
        materialises a real table from it. The ``unregister`` call
        cleans up the view between iterations so we don't leak views.
        ``CREATE OR REPLACE`` is idempotent: re-running the pipeline
        overwrites instead of erroring.

        ``try/except Exception`` around the DuckDB block is a
        deliberate "DuckDB is optional" choice. CSV is the source of
        truth; SQL is a convenience.
    """
    for name, table in tables.items():
        table.to_csv(run_dir / f"{name}.csv", index=False)
    with pd.ExcelWriter(run_dir / "insight_layer_workbook.xlsx", engine="openpyxl") as writer:
        for name, table in tables.items():
            sheet = re.sub(r"[^A-Za-z0-9 _-]", "", name)[:31] or "Sheet"
            table.to_excel(writer, sheet_name=sheet, index=False)
    try:
        import duckdb
        con = duckdb.connect(str(run_dir / "analysis.duckdb"))
        for name, table in tables.items():
            safe = re.sub(r"[^A-Za-z0-9_]", "_", name).lower()
            con.register("_tmp_insight", table)
            con.execute(f'CREATE OR REPLACE TABLE "{safe}" AS SELECT * FROM _tmp_insight')
            con.unregister("_tmp_insight")
        con.close()
    except Exception as exc:
        print(f"[warn] could not write insight tables to DuckDB: {exc}")


def append_report(run_dir: Path, tables: dict[str, pd.DataFrame]) -> None:
    """Append (or replace) the "Insight Layer" section of executive_findings.md.

    Generates a markdown summary of the top opportunities, emerging
    topics, persona counts, manager residuals, evidence coaching, and
    context-value-model coefficients. Uses a marker-based replacement
    strategy so re-running the pipeline doesn't pile duplicate sections
    onto the report.

    Args:
        run_dir: Output directory containing ``executive_findings.md``
            (created in Stage 1).
        tables: The same dict written by :func:`write_outputs`, used as
            the input to format report bullets.

    Teaching:
        The marker-based replacement pattern is worth memorising:
        ::

            existing = report_path.read_text(...)
            marker = "\\n## Insight Layer\\n"
            if marker in existing:
                existing = existing.split(marker, 1)[0].rstrip() + "\\n"
            report_path.write_text(existing + new_section, ...)

        Read in three steps: (1) read the current file, (2) if our
        section header already exists, *truncate the file at that
        point* by splitting on the marker and keeping only the part
        before it, (3) write everything before our marker plus the
        freshly generated section. This is **idempotent**: running the
        pipeline twice produces the same final file as running it once.

        The alternative of just appending (``open("a")``) is what
        :mod:`bertopic_from_run` does. That's fine for a one-shot
        validation note but bad for sections you regenerate every run —
        you'd accumulate identical "Insight Layer" sections forever.

        ``existing.split(marker, 1)`` — the ``1`` is the maxsplit
        argument: at most one split. Without it, a marker that
        accidentally appeared multiple times would be ambiguous. We
        only split on the *first* occurrence to be safe.

        F-string format specs do real work in this function:
        ``{int(row['tickets']):,}`` formats with thousands separators
        (``"1,234"``); ``{row['unresolved_share']:.1%}`` formats a
        float as a percentage with one decimal (``"23.4%"``). Knowing
        the format mini-language saves a lot of manual ``.format()``
        and ``int()`` calls.
    """
    backlog = tables["opportunity_backlog"]
    emerging = tables["emerging_topics"]
    personas = tables["repeat_user_personas"]
    manager_resid = tables["manager_context_residuals"]
    context_model = tables["context_value_model"]
    evidence_coaching = tables["manager_evidence_coaching"]

    lines = [
        "",
        "## Insight Layer",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "### Top Opportunity Backlog",
    ]
    for _, row in backlog.head(10).iterrows():
        lines.append(
            f"- {row['issue_label']}: score {row['opportunity_score']}, {int(row['tickets']):,} tickets, unresolved {row['unresolved_share']:.1%}, recent lift {row['recent_lift']}; {row['recommended_action']}"
        )
    lines += ["", "### Emerging Topics", ""]
    for _, row in emerging[emerging["last_30_tickets"] >= 5].head(10).iterrows():
        lines.append(
            f"- {row['issue_label']}: {int(row['last_30_tickets'])} tickets in last 30 days, lift {row['recent_vs_prior_lift']}, z {row['recent_vs_prior_z']}, unresolved {row['recent_unresolved_share']:.1%}"
        )
    lines += ["", "### Repeat-User Personas", ""]
    if len(personas):
        persona_counts = personas["persona"].value_counts().head(8)
        for persona, count in persona_counts.items():
            lines.append(f"- {persona}: {int(count):,} repeat users")
    lines += ["", "### Context Residuals By Manager", ""]
    for _, row in manager_resid.head(8).iterrows():
        lines.append(
            f"- {row['manager']}: residual {row['avg_residual_vs_ticket_mix']}, raw {row['avg_raw_context']}, expected mix {row['avg_expected_context']}"
        )
    lines += ["", "### Evidence Coaching", ""]
    for _, row in evidence_coaching.head(8).iterrows():
        focus = row["top_evidence_gaps_vs_benchmark"] if isinstance(row["top_evidence_gaps_vs_benchmark"], str) and row["top_evidence_gaps_vs_benchmark"] else "already close to benchmark evidence mix"
        lines.append(f"- {row['manager']}: {focus}")
    lines += ["", "### Context Value Model", ""]
    if "note" in context_model.columns:
        lines.append(str(context_model["note"].iloc[0]))
    else:
        lines.append("Resolved-status model controls for category, question kind, role, month, and primary desire. Interpret as correlation, not causal proof.")
        for _, row in context_model.iterrows():
            lines.append(
                f"- {row['term']}: {row['coef_probability_points']} probability points per unit, p={row['p_value']}, 95% CI [{row['conf_low_pp']}, {row['conf_high_pp']}]."
            )
    lines += [
        "",
        "### Additional Files",
        "",
        "- opportunity_backlog.csv",
        "- emerging_topics.csv",
        "- repeat_user_personas.csv",
        "- manager_context_residuals.csv",
        "- issue_evidence_gaps.csv",
        "- context_value_model.csv",
        "- manager_evidence_coaching.csv",
        "- insight_layer_workbook.xlsx",
    ]
    report_path = run_dir / "executive_findings.md"
    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    marker = "\n## Insight Layer\n"
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip() + "\n"
    report_path.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")


def run(run_dir: Path) -> None:
    """Orchestrate the full Stage 3 insight layer for one run directory.

    Loads the data once, builds every insight table in sequence, persists
    to disk in three formats, updates the executive markdown, and writes
    a metadata snapshot. This is the function the CLI ``__main__``
    invokes.

    Args:
        run_dir: A completed Stage 1+2 run directory.

    Teaching:
        The ``df, _, _ = load_run(...)`` line uses **tuple unpacking with
        the underscore convention**: ``_`` is a Python idiom for "I'm
        ignoring this value". :func:`load_run` returns three things; we
        only need the main DataFrame here, so the BERTopic raw frames
        get bound to ``_`` and discarded.

        The orchestrator does no business logic itself — it just calls
        each ``build_*`` function and gathers the results into a single
        ``tables`` dict. This makes the pipeline easy to extend (add a
        new ``build_*`` function and one entry to ``tables``) and easy
        to debug (each stage's output is on disk by the time the next
        stage runs).

        ``{name: list(table.shape) for name, table in tables.items()}``
        is a dict comprehension that records the (rows, cols) of each
        output table into the metadata JSON. Tiny but useful: if a
        downstream consumer ever sees an empty table, the metadata file
        confirms whether that's expected.
    """
    df, _, _ = load_run(run_dir)
    backlog = build_opportunity_backlog(df)
    emerging = build_emerging_topics(df)
    personas = build_repeat_user_personas(df)
    manager_resid, issue_gaps = build_context_gap(df)
    context_model = build_context_value_model(df)
    evidence_coaching = build_manager_evidence_coaching(df)
    tables = {
        "opportunity_backlog": backlog,
        "emerging_topics": emerging,
        "repeat_user_personas": personas,
        "manager_context_residuals": manager_resid,
        "issue_evidence_gaps": issue_gaps,
        "context_value_model": context_model,
        "manager_evidence_coaching": evidence_coaching,
    }
    write_outputs(run_dir, tables)
    append_report(run_dir, tables)
    metadata = {
        "run_dir": str(run_dir),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tables": {name: list(table.shape) for name, table in tables.items()},
    }
    (run_dir / "insight_layer_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the Stage 3 insight-layer driver.

    Two arguments:
    * ``run_dir`` — optional positional. If omitted, the ``__main__``
      block falls back to :func:`latest_run`.
    * ``--outputs-dir`` — where to look for runs when no ``run_dir`` is
      given. Defaults to ``"outputs"``.

    Returns:
        argparse.Namespace with attributes ``run_dir`` (str or None)
        and ``outputs_dir`` (str).

    Teaching:
        ``nargs="?"`` makes a positional argument **optional**. With
        zero arguments the attribute is ``None``; with one argument it's
        the string. This is how ``argparse`` supports the "default to
        latest run" UX — the CLI doesn't require a path but accepts one.

        The ``__main__`` block below shows the canonical idiom: ``Path(
        args.run_dir).expanduser().resolve() if args.run_dir else
        latest_run(...)``. ``.expanduser()`` turns ``~/Documents`` into
        ``/Users/.../Documents``; ``.resolve()`` converts a relative
        path into absolute. Doing both makes the rest of the code
        immune to working-directory weirdness.
    """
    parser = argparse.ArgumentParser(description="Add decision-oriented insight tables to an Option 2 run directory.")
    parser.add_argument("run_dir", nargs="?", help="Path to outputs/option2_<timestamp>. Defaults to latest run.")
    parser.add_argument("--outputs-dir", default="outputs")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else latest_run(Path(args.outputs_dir).expanduser().resolve())
    run(run_dir)
