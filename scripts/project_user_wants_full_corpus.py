#!/usr/bin/env python3
"""Stage 7 - project discovered user wants onto the full analysis-ready corpus.

This script is the "smart rest" after the expensive local-LLM read:

1. Take the LLM-confirmed ``user_wants_assignments.csv`` as ground truth.
2. Embed each confirmed want text and build one centroid per discovered want.
3. Embed every cleaned ticket from ``enriched_tickets.csv``.
4. Assign each ticket to the nearest discovered want with confidence bands.
5. Write a review queue for tickets that are risky, ambiguous, or weakly
   matched, so a follow-up LLM pass can focus on the tickets worth reading.

The result is not pretending every ticket was deeply read by the LLM. It
creates an auditable census:

* ``llm_confirmed`` rows were actually read by the local model.
* ``embedding_projection`` rows were mapped to the learned taxonomy.
* low-confidence rows are marked for review instead of being overclaimed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from build_user_wants_taxonomy import embed_texts


TEXT_COLUMNS = ["model_text", "question_flat", "question"]
RISK_FLAG_COLUMNS = [
    "has_money_terms",
    "has_status_or_svip_terms",
    "has_ban_reason_language",
    "has_user_claim",
    "is_unresolved",
    "has_screenshot_evidence",
]

DESIRE_TO_JOB_HINTS = {
    "recover_access": ["recover_access"],
    "clear_name_or_get_fairness": ["prove_innocence", "understand_punishment"],
    "earn_or_transact_money": ["buy_or_sell_diamonds", "restore_income"],
    "grow_audience_or_community": ["grow_channel", "restore_visibility"],
    "gain_status_or_privileges": ["gain_status"],
    "protect_from_abuse_or_scam": ["avoid_scam", "protect_community"],
    "fix_product_or_technical_flow": ["fix_product_flow"],
    "understand_rules_or_system_logic": ["understand_punishment"],
    "customize_identity_or_assets": ["customize_identity"],
}


def _read_csv(path: Path, required: bool = True) -> pd.DataFrame | None:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing required file: {path}")
        return None
    return pd.read_csv(path)


def _clean_string(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def _as_bool_series(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(str).str.lower().isin({"true", "1", "yes"})


def _source_row(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\.0$", "", regex=True)


def _normalize_matrix(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


def _ticket_text(row: pd.Series, max_chars: int) -> str:
    body = ""
    for col in TEXT_COLUMNS:
        if col in row:
            body = _clean_string(row.get(col))
            if body:
                break

    metadata = []
    for label, col in [
        ("category", "category"),
        ("status", "status_en"),
        ("desire", "primary_desire"),
        ("kind", "question_kind"),
    ]:
        value = _clean_string(row.get(col))
        if value:
            metadata.append(f"{label}: {value}")

    text = " | ".join(metadata + ([body] if body else []))
    return text[:max_chars]


def _load_human_labels(run_dir: Path) -> pd.DataFrame | None:
    labels = _read_csv(run_dir / "user_wants_human_labels.csv", required=False)
    if labels is None or labels.empty or "want_id" not in labels.columns:
        return None
    labels = labels.copy()
    labels["want_id"] = pd.to_numeric(labels["want_id"], errors="coerce").astype("Int64")
    return labels


def _attach_titles(taxonomy: pd.DataFrame, run_dir: Path) -> pd.DataFrame:
    taxonomy = taxonomy.copy()
    taxonomy["want_id"] = pd.to_numeric(taxonomy["want_id"], errors="coerce").astype("Int64")
    taxonomy["want_title"] = taxonomy.get("want_label", taxonomy["want_id"].astype(str)).astype(str)
    taxonomy["want_summary"] = taxonomy.get("want_label", taxonomy["want_title"]).astype(str)

    labels = _load_human_labels(run_dir)
    if labels is None:
        return taxonomy

    keep = [c for c in ["want_id", "human_title", "human_summary"] if c in labels.columns]
    taxonomy = taxonomy.merge(labels[keep], on="want_id", how="left")
    if "human_title" in taxonomy.columns:
        human_title = taxonomy["human_title"].fillna("").astype(str)
        taxonomy["want_title"] = human_title.where(human_title.str.len() > 0, taxonomy["want_title"])
    if "human_summary" in taxonomy.columns:
        human_summary = taxonomy["human_summary"].fillna("").astype(str)
        taxonomy["want_summary"] = human_summary.where(human_summary.str.len() > 0, taxonomy["want_summary"])
    return taxonomy.drop(columns=[c for c in ["human_title", "human_summary"] if c in taxonomy.columns])


def _load_cached_ticket_embeddings(
    run_dir: Path,
    enriched: pd.DataFrame,
) -> tuple[np.ndarray | None, np.ndarray | None, str]:
    """Load Stage 1 embeddings and align them to ``enriched_tickets.csv`` rows."""
    path = run_dir / "embeddings_local.npy"
    if not path.exists():
        return None, None, "sentence_transformer_live"

    raw = np.load(path)
    if raw.ndim != 2 or raw.shape[0] == 0:
        return None, None, "sentence_transformer_live"

    if raw.shape[0] == len(enriched):
        return _normalize_matrix(raw), np.ones(len(enriched), dtype=bool), "embeddings_local.npy"

    valid = enriched["model_text"].fillna("").astype(str).map(lambda s: len(s) >= 8).to_numpy()
    if raw.shape[0] == int(valid.sum()):
        aligned = np.zeros((len(enriched), raw.shape[1]), dtype=np.float32)
        aligned[valid] = raw.astype(np.float32)
        return _normalize_matrix(aligned), valid.astype(bool), "embeddings_local.npy_valid_model_text"

    return None, None, "sentence_transformer_live"


def _build_centroids_from_ticket_embeddings(
    assignments: pd.DataFrame,
    enriched: pd.DataFrame,
    ticket_embeddings: np.ndarray,
    has_embedding: np.ndarray,
) -> tuple[np.ndarray, list[int], pd.DataFrame]:
    enriched_keys = enriched[["source_row"]].copy()
    enriched_keys["_row_idx"] = np.arange(len(enriched_keys))
    valid = assignments.merge(enriched_keys, on="source_row", how="left")
    valid["want_id"] = pd.to_numeric(valid["want_id"], errors="coerce")
    valid = valid[valid["want_id"].notna() & valid["_row_idx"].notna()].copy()
    valid["_row_idx"] = valid["_row_idx"].astype(int)
    valid = valid[has_embedding[valid["_row_idx"].to_numpy()]].copy()
    if valid.empty:
        raise ValueError("No confirmed assignments have cached embeddings")

    centroids = []
    want_ids = []
    centroid_rows = []
    for want_id, group in valid.groupby(valid["want_id"].astype(int), sort=True):
        idx = group["_row_idx"].to_numpy(dtype=int)
        centroid = ticket_embeddings[idx].mean(axis=0)
        norm = np.linalg.norm(centroid) or 1.0
        centroid = centroid / norm
        centroids.append(centroid)
        want_ids.append(int(want_id))
        if "centroid_similarity" in group.columns:
            avg_confirmed_similarity = float(pd.to_numeric(group["centroid_similarity"], errors="coerce").mean())
        else:
            avg_confirmed_similarity = float("nan")
        centroid_rows.append(
            {
                "want_id": int(want_id),
                "confirmed_rows": int(len(group)),
                "confirmed_avg_centroid_similarity": avg_confirmed_similarity,
            }
        )

    return np.vstack(centroids).astype(np.float32), want_ids, pd.DataFrame(centroid_rows)


def _build_centroids_from_want_text(assignments: pd.DataFrame) -> tuple[np.ndarray, list[int], pd.DataFrame]:
    valid = assignments.copy()
    valid["want_id"] = pd.to_numeric(valid["want_id"], errors="coerce")
    valid["_want_text"] = valid["_want_text"].fillna("").astype(str)
    valid = valid[valid["want_id"].notna() & valid["_want_text"].str.len().gt(0)].copy()
    if valid.empty:
        raise ValueError("No usable rows in user_wants_assignments.csv")

    embeddings = embed_texts(valid["_want_text"].tolist())
    valid["_embedding_row"] = np.arange(len(valid))

    centroids = []
    want_ids = []
    centroid_rows = []
    for want_id, group in valid.groupby(valid["want_id"].astype(int), sort=True):
        idx = group["_embedding_row"].to_numpy(dtype=int)
        centroid = embeddings[idx].mean(axis=0)
        norm = np.linalg.norm(centroid) or 1.0
        centroid = centroid / norm
        centroids.append(centroid)
        want_ids.append(int(want_id))
        if "centroid_similarity" in group.columns:
            avg_confirmed_similarity = float(pd.to_numeric(group["centroid_similarity"], errors="coerce").mean())
        else:
            avg_confirmed_similarity = float("nan")
        centroid_rows.append(
            {
                "want_id": int(want_id),
                "confirmed_rows": int(len(group)),
                "confirmed_avg_centroid_similarity": avg_confirmed_similarity,
            }
        )

    return np.vstack(centroids).astype(np.float32), want_ids, pd.DataFrame(centroid_rows)


def _fallback_want_lookup(taxonomy: pd.DataFrame) -> tuple[int, dict[str, int]]:
    taxonomy = taxonomy.copy()
    taxonomy["want_id"] = pd.to_numeric(taxonomy["want_id"], errors="coerce")
    taxonomy["size"] = pd.to_numeric(taxonomy.get("size", 0), errors="coerce").fillna(0)
    taxonomy = taxonomy[taxonomy["want_id"].notna()].sort_values("size", ascending=False)
    if taxonomy.empty:
        raise ValueError("Taxonomy has no want_id values")
    default_want = int(taxonomy.iloc[0]["want_id"])

    by_job: dict[str, int] = {}
    for _, row in taxonomy.iterrows():
        want_id = int(row["want_id"])
        top_jobs = _clean_string(row.get("top_jobs"))
        for item in top_jobs.split(","):
            job = item.split(":")[0].strip()
            if job and job not in by_job:
                by_job[job] = want_id

    by_desire = {}
    for desire, jobs in DESIRE_TO_JOB_HINTS.items():
        for job in jobs:
            if job in by_job:
                by_desire[desire] = by_job[job]
                break
    return default_want, by_desire


def _risk_signal_count(enriched: pd.DataFrame) -> pd.Series:
    total = pd.Series(0, index=enriched.index, dtype="int64")
    for col in RISK_FLAG_COLUMNS:
        if col in enriched.columns:
            total = total + _as_bool_series(enriched[col]).astype(int)
    if "context_depth_score" in enriched.columns:
        total = total + (pd.to_numeric(enriched["context_depth_score"], errors="coerce").fillna(0) >= 24).astype(int)
    return total


def _confidence_band(
    method: str,
    score: float,
    margin: float,
    threshold: float,
    margin_threshold: float,
) -> str:
    if method == "llm_confirmed":
        return "confirmed"
    if score >= threshold + 0.10 and margin >= margin_threshold * 2:
        return "high"
    if score >= threshold and margin >= margin_threshold:
        return "medium"
    return "low"


def _review_reason(row: pd.Series, threshold: float, margin_threshold: float, min_text_chars: int) -> str:
    reasons = []
    if row["assignment_method"] == "llm_confirmed":
        return ""
    if row["assignment_confidence"] < threshold:
        reasons.append("low_similarity")
    if row["assignment_margin"] < margin_threshold:
        reasons.append("ambiguous_match")
    if row["risk_signal_count"] >= 2:
        reasons.append("high_risk_signal")
    if row["text_chars"] < min_text_chars:
        reasons.append("short_text")
    if not reasons:
        return ""
    return ", ".join(reasons)


def project_full_corpus(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = args.run_dir.expanduser().resolve()
    enriched = _read_csv(run_dir / "enriched_tickets.csv")
    taxonomy = _attach_titles(_read_csv(run_dir / "user_wants_taxonomy.csv"), run_dir)
    confirmed = _read_csv(run_dir / "user_wants_assignments.csv")

    for df in [enriched, confirmed]:
        if "source_row" not in df.columns:
            raise ValueError("Both enriched_tickets.csv and user_wants_assignments.csv need source_row")
        df["source_row"] = _source_row(df["source_row"])

    enriched = enriched.copy()
    enriched["_projection_text"] = enriched.apply(lambda row: _ticket_text(row, args.max_chars), axis=1)
    enriched["text_chars"] = enriched["_projection_text"].str.len()
    enriched["risk_signal_count"] = _risk_signal_count(enriched)

    ticket_embeddings, has_embedding, embedding_source = _load_cached_ticket_embeddings(run_dir, enriched)
    if ticket_embeddings is not None and has_embedding is not None:
        centroids, want_ids, centroid_meta = _build_centroids_from_ticket_embeddings(
            confirmed,
            enriched,
            ticket_embeddings,
            has_embedding,
        )
    else:
        centroids, want_ids, centroid_meta = _build_centroids_from_want_text(confirmed)
        ticket_embeddings = embed_texts(enriched["_projection_text"].fillna("").astype(str).tolist())
        has_embedding = np.ones(len(enriched), dtype=bool)

    want_index = {want_id: i for i, want_id in enumerate(want_ids)}
    default_want_id, desire_want_lookup = _fallback_want_lookup(taxonomy)

    scores = ticket_embeddings @ centroids.T
    best_idx = np.argmax(scores, axis=1)
    best_scores = scores[np.arange(len(scores)), best_idx]
    if scores.shape[1] > 1:
        sorted_scores = np.sort(scores, axis=1)
        second_scores = sorted_scores[:, -2]
    else:
        second_scores = np.zeros(len(scores), dtype=np.float32)
    margins = best_scores - second_scores

    assigned_want_ids = np.array([want_ids[i] for i in best_idx])
    confirmed_lookup = confirmed.drop_duplicates("source_row").set_index("source_row")
    confirmed_sources = set(confirmed_lookup.index.astype(str))

    confirmed_ticket_scores = []
    for i, row in enriched.iterrows():
        source = row["source_row"]
        if source not in confirmed_sources:
            continue
        want_id = int(pd.to_numeric(confirmed_lookup.loc[source, "want_id"], errors="coerce"))
        if want_id in want_index:
            confirmed_ticket_scores.append(float(scores[i, want_index[want_id]]))

    if args.assignment_threshold is not None:
        threshold = float(args.assignment_threshold)
    elif confirmed_ticket_scores:
        raw = float(np.quantile(confirmed_ticket_scores, args.threshold_quantile))
        threshold = min(args.max_threshold, max(args.min_threshold, raw - args.threshold_slack))
    else:
        threshold = args.min_threshold

    rows = []
    for i, row in enriched.iterrows():
        source = str(row["source_row"])
        method = "embedding_projection"
        want_id = int(assigned_want_ids[i]) if has_embedding[i] else int(
            desire_want_lookup.get(_clean_string(row.get("primary_desire")), default_want_id)
        )
        score = float(best_scores[i])
        margin = float(margins[i])

        if source in confirmed_sources:
            confirmed_row = confirmed_lookup.loc[source]
            method = "llm_confirmed"
            want_id = int(pd.to_numeric(confirmed_row.get("want_id"), errors="coerce"))
            score = float(scores[i, want_index[want_id]]) if want_id in want_index else score
        elif not has_embedding[i]:
            method = "rule_hint_only"
            score = 0.0
            margin = 0.0
        elif row["text_chars"] < args.min_text_chars:
            method = "short_text_projection" if score >= threshold and margin >= args.margin_threshold else "rule_hint_only"
        elif score < threshold or margin < args.margin_threshold:
            method = "low_confidence_projection"

        rows.append(
            {
                "source_row": source,
                "assigned_want_id": want_id,
                "assignment_method": method,
                "assignment_confidence": round(score, 4),
                "assignment_margin": round(margin, 4),
                "confidence_band": _confidence_band(method, score, margin, threshold, args.margin_threshold),
                "risk_signal_count": int(row["risk_signal_count"]),
                "text_chars": int(row["text_chars"]),
                "needs_llm_review": False,
                "review_reason": "",
            }
        )

    projected = pd.DataFrame(rows)
    projected["review_reason"] = projected.apply(
        lambda row: _review_reason(row, threshold, args.margin_threshold, args.min_text_chars),
        axis=1,
    )
    projected["needs_llm_review"] = projected["review_reason"].astype(str).str.len().gt(0)

    title_cols = taxonomy[["want_id", "want_label", "want_title", "want_summary"]].copy()
    title_cols["want_id"] = title_cols["want_id"].astype(int)
    projected = projected.merge(title_cols, left_on="assigned_want_id", right_on="want_id", how="left")
    projected = projected.drop(columns=["want_id"])

    context_cols = [
        "source_row",
        "date_raw",
        "manager",
        "uid",
        "category",
        "question_kind",
        "status_en",
        "primary_desire",
        "context_depth_score",
        "context_depth_band",
        "char_count",
        "question_flat",
    ]
    context_cols = [c for c in context_cols if c in enriched.columns]
    projected = projected.merge(enriched[context_cols], on="source_row", how="left")

    summary = (
        projected.groupby(["assigned_want_id", "want_label", "want_title"], dropna=False)
        .agg(
            estimated_tickets=("source_row", "count"),
            llm_confirmed_tickets=("assignment_method", lambda s: int((s == "llm_confirmed").sum())),
            projected_tickets=("assignment_method", lambda s: int((s != "llm_confirmed").sum())),
            avg_assignment_confidence=("assignment_confidence", "mean"),
            low_confidence_tickets=("confidence_band", lambda s: int((s == "low").sum())),
            review_queue_tickets=("needs_llm_review", "sum"),
            avg_risk_signal_count=("risk_signal_count", "mean"),
        )
        .reset_index()
        .sort_values("estimated_tickets", ascending=False)
    )
    summary["estimated_share"] = summary["estimated_tickets"] / max(1, len(projected))
    summary = summary.merge(centroid_meta, left_on="assigned_want_id", right_on="want_id", how="left").drop(
        columns=["want_id"], errors="ignore"
    )

    review = projected[projected["needs_llm_review"]].copy()
    review["uncertainty_score"] = (
        (threshold - review["assignment_confidence"]).clip(lower=0)
        + (args.margin_threshold - review["assignment_margin"]).clip(lower=0)
        + review["risk_signal_count"] * 0.05
    )
    review = review.sort_values(
        ["uncertainty_score", "risk_signal_count", "text_chars"],
        ascending=[False, False, False],
    ).head(args.review_limit)

    projected_path = run_dir / "user_wants_all_assignments.csv"
    summary_path = run_dir / "user_wants_full_corpus_summary.csv"
    review_path = run_dir / "user_wants_review_queue.csv"
    workbook_path = run_dir / "user_wants_full_corpus_workbook.xlsx"
    metadata_path = run_dir / "user_wants_projection_metadata.json"

    projected.to_csv(projected_path, index=False)
    summary.to_csv(summary_path, index=False)
    review.to_csv(review_path, index=False)
    with pd.ExcelWriter(workbook_path) as writer:
        summary.to_excel(writer, sheet_name="full_corpus_summary", index=False)
        projected.to_excel(writer, sheet_name="all_assignments", index=False)
        review.to_excel(writer, sheet_name="llm_review_queue", index=False)

    metadata = {
        "run_dir": str(run_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_rows": int(len(enriched)),
        "llm_confirmed_rows": int(len(confirmed_sources)),
        "projected_rows": int((projected["assignment_method"] != "llm_confirmed").sum()),
        "wants": int(len(want_ids)),
        "assignment_threshold": round(float(threshold), 4),
        "margin_threshold": float(args.margin_threshold),
        "threshold_method": "manual" if args.assignment_threshold is not None else "confirmed_ticket_quantile",
        "threshold_quantile": float(args.threshold_quantile),
        "embedding_source": embedding_source,
        "review_queue_rows": int(len(review)),
        "outputs": {
            "all_assignments": projected_path.name,
            "summary": summary_path.name,
            "review_queue": review_path.name,
            "workbook": workbook_path.name,
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project discovered user wants onto every cleaned ticket.")
    parser.add_argument("run_dir", type=Path, help="outputs/option2_<timestamp>")
    parser.add_argument("--max-chars", type=int, default=1600)
    parser.add_argument("--min-text-chars", type=int, default=40)
    parser.add_argument("--assignment-threshold", type=float, default=None)
    parser.add_argument("--threshold-quantile", type=float, default=0.10)
    parser.add_argument("--threshold-slack", type=float, default=0.03)
    parser.add_argument("--min-threshold", type=float, default=0.25)
    parser.add_argument("--max-threshold", type=float, default=0.55)
    parser.add_argument("--margin-threshold", type=float, default=0.03)
    parser.add_argument("--review-limit", type=int, default=800)
    return parser.parse_args()


def main() -> int:
    try:
        metadata = project_full_corpus(parse_args())
    except Exception as exc:
        print(f"Projection failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
