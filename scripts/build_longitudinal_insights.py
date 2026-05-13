#!/usr/bin/env python3
"""Build macro/micro longitudinal insights from a completed Option 2 run.

This stage exists because counts alone are not management intelligence. The
AI/user-wants outputs tell us what each support record is about; this script
adds time and user continuity:

* What is rising or fading month by month?
* Which wants are likely to grow next month?
* Which users keep coming back, with what sequence of problems?
* Which repeat-user archetypes create unresolved or failed work?

Outputs are plain CSV/Markdown files so the dashboard, NotebookLM, or Excel can
inspect them. The difference is that these tables are not raw pivots; they are
created from the model-derived user-want layer plus chronological user history.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


RESOLVED_STATUSES = {"closed", "done"}
FAILED_STATUSES = {"failed", "no action"}
OPEN_STATUSES = {"in process"}


def _read_csv(path: Path, required: bool = True) -> pd.DataFrame | None:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing required file: {path}")
        return None
    return pd.read_csv(path)


def _clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def _source_row(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\.0$", "", regex=True)


def _collapse_sequence(values: list[object], limit: int = 8) -> str:
    """Return a readable path, removing only adjacent repeats."""
    out: list[str] = []
    for value in values:
        text = _clean(value)
        if text and (not out or out[-1] != text):
            out.append(text)
    if len(out) > limit:
        return " -> ".join(out[:limit]) + " -> ..."
    return " -> ".join(out)


def _top_values(values: pd.Series, limit: int = 4) -> str:
    cleaned = [_clean(v) for v in values.dropna().tolist() if _clean(v)]
    if not cleaned:
        return ""
    return ", ".join(f"{k} ({v})" for k, v in Counter(cleaned).most_common(limit))


def _status_bucket(status: object) -> str:
    text = _clean(status).lower()
    if text in RESOLVED_STATUSES:
        return "resolved"
    if text in FAILED_STATUSES:
        return "failed"
    if text in OPEN_STATUSES:
        return "open"
    return "unknown"


def _journey_pattern(row: pd.Series) -> str:
    wants = f"{row.get('want_path', '')} {row.get('top_wants', '')}".lower()
    questions = f"{row.get('first_question', '')} {row.get('last_question', '')}".lower()
    text = f"{wants} {questions}"
    if row.get("unique_wants", 0) >= 4 and row.get("records", 0) >= 5:
        return "multi_problem_power_user"
    if any(term in text for term in ["diamond", "dealer", "reseller", "money", "withdraw"]):
        return "money_or_dealer_dispute"
    if any(term in text for term in ["scam", "harassment", "abuse", "inappropriate", "report"]):
        return "safety_or_abuse_reporter"
    if any(term in text for term in ["access", "account", "unban", "blocked", "banned", "recover"]):
        return "account_recovery_loop"
    if any(term in text for term in ["group", "channel", "visibility", "member", "room"]):
        return "creator_or_group_operator"
    if any(term in text for term in ["svip", "status", "points", "level"]):
        return "status_or_privilege_loop"
    return "general_repeat_user"


def _recommended_action(pattern: str) -> str:
    return {
        "multi_problem_power_user": "Assign an owner and review full history before replying; repeated isolated handling is creating churn.",
        "money_or_dealer_dispute": "Route to a transaction/dealer evidence lane with proof checklist and decision SLA.",
        "safety_or_abuse_reporter": "Use an abuse-report triage path with actor, room, screenshot, and enforcement-status fields.",
        "account_recovery_loop": "Give a single recovery/appeal status trail: reason, required proof, owner, next decision date.",
        "creator_or_group_operator": "Create group/channel diagnostics for visibility, limits, room access, and member-growth blockers.",
        "status_or_privilege_loop": "Give SVIP/status users a verification path and plain explanation of points/reward state.",
        "general_repeat_user": "Monitor; review if unresolved, high-risk, or active over a long span.",
    }.get(pattern, "Review repeated tickets and decide whether support, policy, or product owns the loop.")


def _safe_div(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def _complete_months(df: pd.DataFrame) -> list[pd.Period]:
    counts = df["month_period"].value_counts().sort_index()
    if counts.empty:
        return []
    months = list(counts.index)
    if len(months) >= 3:
        median = float(counts.iloc[:-1].median()) if len(counts) > 1 else float(counts.median())
        if median and counts.iloc[-1] < median * 0.4:
            months = months[:-1]
    return months


def _load_model_layer(run_dir: Path) -> pd.DataFrame | None:
    status_path = run_dir / "llm_extraction_status.json"
    candidates: list[Path] = []
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            output_stem = _clean(status.get("output_stem"))
            if output_stem:
                candidates.append(run_dir / f"{output_stem}.csv")
        except Exception:
            pass
    candidates.extend([run_dir / "ollama_extractions.csv", run_dir / "llm_extractions.csv"])
    for path in candidates:
        if path.exists() and path.stat().st_size > 0:
            df = pd.read_csv(path)
            if "_status" in df.columns:
                df = df[df["_status"].fillna("").astype(str).eq("ok")].copy()
            return df
    return None


def build_longitudinal_insights(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.expanduser().resolve()
    assignments = _read_csv(run_dir / "user_wants_all_assignments.csv")
    enriched = _read_csv(run_dir / "enriched_tickets.csv")
    model = _load_model_layer(run_dir)

    assignments = assignments.copy()
    enriched = enriched.copy()
    assignments["source_row"] = _source_row(assignments["source_row"])
    enriched["source_row"] = _source_row(enriched["source_row"])

    enrich_cols = [
        "source_row",
        "date",
        "month",
        "role",
        "question",
        "is_resolved",
        "is_unresolved",
        "has_money_terms",
        "has_status_or_svip_terms",
        "has_ban_reason_language",
        "has_user_claim",
        "has_screenshot_evidence",
        "evidence_element_count",
    ]
    enrich_cols = [
        c
        for c in enrich_cols
        if c == "source_row" or (c in enriched.columns and c not in assignments.columns)
    ]
    data = assignments.merge(enriched[enrich_cols], on="source_row", how="left")

    if "date" not in data.columns:
        data["date"] = pd.to_datetime(data.get("date_raw"), errors="coerce", dayfirst=True)
    else:
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
    fallback_month = data["date"].dt.to_period("M").astype(str)
    if "month" not in data.columns:
        data["month"] = fallback_month
    else:
        data["month"] = (
            data["month"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace({"": pd.NA, "nan": pd.NA, "NaT": pd.NA})
            .fillna(fallback_month)
        )
    data["month_period"] = pd.PeriodIndex(data["month"], freq="M")
    data["uid"] = data["uid"].fillna("").astype(str).str.strip()
    data["want_title"] = data["want_title"].fillna(data["want_label"]).astype(str)
    data["status_bucket"] = data["status_en"].map(_status_bucket)
    data["resolved_flag"] = data["status_bucket"].eq("resolved")
    data["failed_or_open_flag"] = data["status_bucket"].isin(["failed", "open"])
    if "needs_llm_review" in data.columns:
        data["needs_llm_review"] = data["needs_llm_review"].fillna(False).astype(bool)
    else:
        data["needs_llm_review"] = False
    if "assignment_confidence" in data.columns:
        data["assignment_confidence"] = pd.to_numeric(data["assignment_confidence"], errors="coerce").fillna(0)
    else:
        data["assignment_confidence"] = 0.0

    if model is not None and not model.empty:
        model = model.copy()
        model["source_row"] = _source_row(model["source_row"])
        model_cols = [
            "source_row",
            "literal_request",
            "actual_user_want",
            "job_to_be_done",
            "user_emotion",
            "urgency_level",
            "trust_risk_level",
            "money_risk_level",
            "safety_policy_risk_level",
            "evidence_missing",
            "support_next_step",
            "product_opportunity",
        ]
        model_cols = [c for c in model_cols if c in model.columns]
        data = data.merge(model[model_cols].drop_duplicates("source_row"), on="source_row", how="left")

    data = data.sort_values(["uid", "date", "source_row"])

    # ---- Timeline and trend outputs -------------------------------------

    monthly = (
        data.groupby(["month_period", "assigned_want_id", "want_title"], as_index=False)
        .agg(
            records=("source_row", "count"),
            unique_users=("uid", pd.Series.nunique),
            failed_or_open_records=("failed_or_open_flag", "sum"),
            review_queue_records=("needs_llm_review", "sum"),
            avg_assignment_confidence=("assignment_confidence", "mean"),
        )
        .sort_values(["month_period", "records"], ascending=[True, False])
    )
    monthly["month"] = monthly["month_period"].astype(str)
    monthly["failed_or_open_share"] = monthly["failed_or_open_records"] / monthly["records"].clip(lower=1)
    monthly["review_queue_share"] = monthly["review_queue_records"] / monthly["records"].clip(lower=1)
    monthly = monthly.drop(columns=["month_period"])

    complete_months = _complete_months(data)
    recent_months = complete_months[-2:]
    prior_months = complete_months[-4:-2]
    next_month = str((complete_months[-1] + 1) if complete_months else "")

    trend_rows = []
    for (want_id, title), group in data[data["month_period"].isin(complete_months)].groupby(["assigned_want_id", "want_title"]):
        counts = group["month_period"].value_counts().sort_index()
        recent = float(counts[counts.index.isin(recent_months)].sum())
        prior = float(counts[counts.index.isin(prior_months)].sum())
        recent_avg = recent / max(len(recent_months), 1)
        prior_avg = prior / max(len(prior_months), 1)
        growth = _safe_div(recent_avg - prior_avg, prior_avg)
        y = np.array([float(counts.get(m, 0)) for m in complete_months], dtype=float)
        slope = float(np.polyfit(np.arange(len(y)), y, 1)[0]) if len(y) >= 3 else 0.0
        forecast = max(0.0, float(y[-3:].mean() + slope)) if len(y) >= 3 else recent_avg
        recent_group = group[group["month_period"].isin(recent_months)]
        trend_rows.append(
            {
                "assigned_want_id": int(want_id),
                "want_title": title,
                "recent_months": ", ".join(str(m) for m in recent_months),
                "prior_months": ", ".join(str(m) for m in prior_months),
                "recent_records": int(recent),
                "prior_records": int(prior),
                "recent_avg_per_month": round(recent_avg, 2),
                "prior_avg_per_month": round(prior_avg, 2),
                "growth_ratio": round(growth, 3),
                "monthly_slope": round(slope, 2),
                "forecast_next_month": round(forecast, 1),
                "forecast_month": next_month,
                "recent_failed_or_open_share": round(float(recent_group["failed_or_open_flag"].mean()) if len(recent_group) else 0.0, 3),
                "recent_review_queue_share": round(float(recent_group["needs_llm_review"].mean()) if len(recent_group) else 0.0, 3),
                "recent_unique_users": int(recent_group["uid"].nunique()) if len(recent_group) else 0,
            }
        )
    trend = pd.DataFrame(trend_rows)
    if not trend.empty:
        trend["momentum_score"] = (
            trend["forecast_next_month"]
            * (1 + trend["growth_ratio"].clip(lower=-0.5))
            * (1 + trend["recent_failed_or_open_share"])
        ).round(2)
        trend["trend_label"] = np.select(
            [
                trend["growth_ratio"].ge(0.35) & trend["recent_records"].ge(20),
                trend["growth_ratio"].le(-0.35) & trend["prior_records"].ge(20),
                trend["monthly_slope"].ge(5),
                trend["monthly_slope"].le(-5),
            ],
            ["rising", "falling", "slow_rise", "slow_decline"],
            default="stable",
        )
        trend = trend.sort_values(["momentum_score", "recent_records"], ascending=False)

    # ---- User journeys ---------------------------------------------------

    repeat = data[data["uid"].ne("")].copy()
    user_rows = []
    event_rows = []
    for uid, group in repeat.groupby("uid", sort=False):
        group = group.sort_values(["date", "source_row"]).copy()
        if len(group) < 2:
            continue
        first_date = group["date"].min()
        last_date = group["date"].max()
        active_days = int((last_date - first_date).days) if pd.notna(first_date) and pd.notna(last_date) else 0
        want_path = _collapse_sequence(group["want_title"].tolist(), limit=9)
        category_path = _collapse_sequence(group.get("category", pd.Series(dtype=str)).tolist(), limit=9)
        status_path = _collapse_sequence(group.get("status_en", pd.Series(dtype=str)).tolist(), limit=9)
        top_wants = _top_values(group["want_title"])
        first_q = _clean(group.iloc[0].get("question_flat"))
        last_q = _clean(group.iloc[-1].get("question_flat"))
        unresolved = int(group["failed_or_open_flag"].sum())
        unique_wants = int(group["assigned_want_id"].nunique())
        row = {
            "uid": uid,
            "records": int(len(group)),
            "first_date": first_date.date().isoformat() if pd.notna(first_date) else "",
            "last_date": last_date.date().isoformat() if pd.notna(last_date) else "",
            "active_days": active_days,
            "unique_wants": unique_wants,
            "unique_categories": int(group.get("category", pd.Series(dtype=str)).nunique()),
            "managers_touched": int(group.get("manager", pd.Series(dtype=str)).nunique()),
            "resolved_records": int(group["resolved_flag"].sum()),
            "failed_or_open_records": unresolved,
            "failed_or_open_share": round(float(group["failed_or_open_flag"].mean()), 3),
            "review_queue_records": int(group["needs_llm_review"].sum()),
            "avg_assignment_confidence": round(float(group["assignment_confidence"].mean()), 3),
            "top_wants": top_wants,
            "want_path": want_path,
            "category_path": category_path,
            "status_path": status_path,
            "latest_status": _clean(group.iloc[-1].get("status_en")),
            "latest_want": _clean(group.iloc[-1].get("want_title")),
            "first_question": first_q[:220],
            "last_question": last_q[:220],
        }
        row["journey_pattern"] = _journey_pattern(pd.Series(row))
        row["recommended_action"] = _recommended_action(row["journey_pattern"])
        row["severity_score"] = round(
            row["records"] * 1.0
            + row["unique_wants"] * 2.0
            + row["failed_or_open_records"] * 2.5
            + row["review_queue_records"] * 0.75
            + min(row["active_days"] / 30, 12),
            2,
        )
        user_rows.append(row)

        for idx, (_, event) in enumerate(group.iterrows(), start=1):
            event_rows.append(
                {
                    "uid": uid,
                    "event_index": idx,
                    "source_row": event["source_row"],
                    "date": event["date"].date().isoformat() if pd.notna(event["date"]) else "",
                    "days_since_first": int((event["date"] - first_date).days) if pd.notna(event["date"]) and pd.notna(first_date) else 0,
                    "want_title": _clean(event.get("want_title")),
                    "category": _clean(event.get("category")),
                    "status": _clean(event.get("status_en")),
                    "manager": _clean(event.get("manager")),
                    "confidence_band": _clean(event.get("confidence_band")),
                    "question": _clean(event.get("question_flat"))[:280],
                    "actual_user_want": _clean(event.get("actual_user_want"))[:180],
                    "support_next_step": _clean(event.get("support_next_step"))[:180],
                    "product_opportunity": _clean(event.get("product_opportunity"))[:180],
                }
            )

    journeys = pd.DataFrame(user_rows).sort_values("severity_score", ascending=False)
    events = pd.DataFrame(event_rows)

    if not journeys.empty:
        events_with_patterns = events.merge(
            journeys[["uid", "journey_pattern"]],
            on="uid",
            how="left",
        )
        archetype_rows = []
        for pattern, group in journeys.groupby("journey_pattern"):
            event_group = events_with_patterns[events_with_patterns["journey_pattern"].eq(pattern)]
            archetype_rows.append(
                {
                    "journey_pattern": pattern,
                    "users": int(group["uid"].nunique()),
                    "records": int(group["records"].sum()),
                    "median_records_per_user": float(group["records"].median()),
                    "median_active_days": float(group["active_days"].median()),
                    "avg_unique_wants": float(group["unique_wants"].mean()),
                    "failed_or_open_share": float(group["failed_or_open_share"].mean()),
                    "review_queue_records": int(group["review_queue_records"].sum()),
                    "top_wants": _top_values(event_group["want_title"]),
                    "recommended_action": _recommended_action(pattern),
                }
            )
        archetypes = pd.DataFrame(archetype_rows).sort_values(["records", "users"], ascending=False)
    else:
        archetypes = pd.DataFrame()

    # ---- Findings --------------------------------------------------------

    lines = [
        "# Longitudinal User Insights",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Run: `{run_dir.name}`",
        "",
        "## Macro Signals",
        "",
        f"- Analysis-ready support records: `{len(data):,}`.",
        f"- Complete months used for trend comparisons: `{', '.join(str(m) for m in complete_months)}`.",
        f"- Repeat users with 2+ records: `{len(journeys):,}`.",
        f"- Repeat users with 3+ records: `{int((journeys['records'] >= 3).sum()) if len(journeys) else 0:,}`.",
    ]
    if not trend.empty:
        lines += ["", "### Highest Momentum Wants", ""]
        for _, row in trend.head(8).iterrows():
            lines.append(
                f"- **{row['want_title']}**: forecast `{row['forecast_next_month']}` records in `{row['forecast_month']}`, "
                f"growth `{row['growth_ratio']:.1%}`, recent failed/open `{row['recent_failed_or_open_share']:.1%}`."
            )
    if not journeys.empty:
        lines += ["", "## Micro User Journeys", ""]
        for _, row in journeys.head(5).iterrows():
            lines.append(
                f"- **UID {row['uid']}**: `{row['records']}` records over `{row['active_days']}` days, "
                f"`{row['unique_wants']}` wants, pattern `{row['journey_pattern']}`. Path: {row['want_path']}"
            )
    if not archetypes.empty:
        lines += ["", "## Journey Archetypes", ""]
        for _, row in archetypes.iterrows():
            lines.append(
                f"- **{row['journey_pattern']}**: `{int(row['users'])}` users, `{int(row['records'])}` records, "
                f"failed/open `{row['failed_or_open_share']:.1%}`. Action: {row['recommended_action']}"
            )

    paths = {
        "monthly_trends": run_dir / "longitudinal_want_monthly_trends.csv",
        "emerging_wants": run_dir / "longitudinal_emerging_wants.csv",
        "user_journeys": run_dir / "longitudinal_user_journeys.csv",
        "journey_events": run_dir / "longitudinal_user_journey_events.csv",
        "journey_archetypes": run_dir / "longitudinal_journey_archetypes.csv",
        "findings": run_dir / "longitudinal_findings.md",
    }
    monthly.to_csv(paths["monthly_trends"], index=False)
    trend.to_csv(paths["emerging_wants"], index=False)
    journeys.to_csv(paths["user_journeys"], index=False)
    events.to_csv(paths["journey_events"], index=False)
    archetypes.to_csv(paths["journey_archetypes"], index=False)
    paths["findings"].write_text("\n".join(lines) + "\n", encoding="utf-8")

    metadata = {
        "run_dir": str(run_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": int(len(data)),
        "complete_months": [str(m) for m in complete_months],
        "repeat_users": int(len(journeys)),
        "repeat_users_3_plus": int((journeys["records"] >= 3).sum()) if len(journeys) else 0,
        "emerging_wants": int(len(trend)),
        "journey_events": int(len(events)),
        "outputs": {k: v.name for k, v in paths.items()},
    }
    (run_dir / "longitudinal_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build timeline, trend, forecast, and repeat-user journey insights.")
    parser.add_argument("run_dir", type=Path, help="outputs/option2_<timestamp>")
    return parser.parse_args()


def main() -> int:
    metadata = build_longitudinal_insights(parse_args().run_dir)
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
