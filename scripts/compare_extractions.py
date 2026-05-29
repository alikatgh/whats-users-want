#!/usr/bin/env python3
"""Profile and diff LLM extraction CSVs — a model-agnostic QA harness.

Answers two questions WITHOUT human labeling and WITHOUT re-running the pipeline:

  1. Profile mode (one CSV): are a run's *graded* fields degenerate — collapsed
     onto a single value? This catches the exact failure we hit with Mistral:
     schema-valid output ("0 bad rows") whose 1-5 scores were pinned
     (money=1 in 93%, urgency=3 in 90%) — i.e. valid JSON, useless signal.

  2. Diff mode (two CSVs): how does a *candidate* extraction differ from a
     *baseline*, field by field, on the tickets they share? Categorical fields
     get an agreement %; graded fields get a distribution-shift + a flag for
     whether the candidate *spreads* a field the baseline collapsed.

This is the reusable spine for the "build on top of Mistral" plan: profile
Mistral now, and the instant DeepSeek V4 produces output, diff V4 vs Mistral to
see — for free, no labeling — whether V4 fixes the graded scores or pins them too.

It reads ONLY extraction CSVs (structured fields). It does not call any model,
does not read data_2may.csv, and never prints ticket text / UIDs / narrative
fields, so its output is safe to share.

Usage:
    python scripts/compare_extractions.py BASELINE.csv [CANDIDATE.csv]
        one arg  -> profile + degeneracy report for BASELINE
        two args -> profile both, then diff CANDIDATE against BASELINE

    --degenerate-share FLOAT   dominance threshold to flag degenerate (default 0.85)
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

CATEGORICAL_FIELDS = ["job_to_be_done", "user_emotion", "manager_note_quality", "needs_human_review"]
GRADED_FIELDS = ["money_risk_level", "trust_risk_level", "urgency_level", "safety_policy_risk_level", "confidence"]


def norm_entropy(counts: pd.Series) -> float:
    """Shannon entropy of a value-count distribution, normalised to [0, 1].

    1.0 = perfectly uniform (maximally discriminating); 0.0 = one value only
    (no signal). k is the number of *observed* distinct values, so a field that
    only ever emits one token scores 0 regardless of the schema's range.
    """
    total = counts.sum()
    if total <= 0 or len(counts) <= 1:
        return 0.0
    p = counts / total
    h = -(p * np.log(p)).sum()
    return float(h / math.log(len(counts)))


def coerce_source_row(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\.0$", "", regex=True).str.strip()


def present_fields(df: pd.DataFrame, fields: list[str]) -> list[str]:
    return [f for f in fields if f in df.columns]


def profile(df: pd.DataFrame, name: str, degenerate_share: float) -> None:
    n = len(df)
    status = df["_status"].value_counts().to_dict() if "_status" in df.columns else {}
    print(f"\n=== PROFILE: {name}  (rows={n}, status={status or 'n/a'}) ===")
    for kind, fields in (("CATEGORICAL", CATEGORICAL_FIELDS), ("GRADED / confidence", GRADED_FIELDS)):
        fs = present_fields(df, fields)
        if not fs:
            continue
        print(f"  {kind}")
        for f in fs:
            col = df[f].dropna()
            if col.empty:
                print(f"    {f:<26} (empty)")
                continue
            vc = col.astype(str).value_counts()
            dominance = vc.iloc[0] / vc.sum()
            ent = norm_entropy(vc)
            top_val = vc.index[0]
            degenerate = dominance >= degenerate_share or ent <= 0.35
            flag = "  ⚠ DEGENERATE" if degenerate else ""
            extra = ""
            if f == "confidence":
                cn = pd.to_numeric(col, errors="coerce").dropna()
                if not cn.empty:
                    extra = f"  mean={cn.mean():.2f} std={cn.std():.2f} range=[{cn.min():.2f},{cn.max():.2f}]"
            print(f"    {f:<26} {len(vc):>2} vals  top {top_val!r} {dominance:6.1%}  entropy {ent:.2f}{extra}{flag}")


def diff(base: pd.DataFrame, cand: pd.DataFrame, base_name: str, cand_name: str, degenerate_share: float) -> None:
    base = base.copy()
    cand = cand.copy()
    base["__sr"] = coerce_source_row(base["source_row"])
    cand["__sr"] = coerce_source_row(cand["source_row"])
    shared = sorted(set(base["__sr"]) & set(cand["__sr"]))
    print(f"\n=== DIFF: candidate={cand_name}  vs  baseline={base_name}  (shared source_rows={len(shared)}) ===")
    if not shared:
        print("  No shared source_rows — nothing to diff.")
        return
    b = base.set_index("__sr").loc[shared]
    c = cand.set_index("__sr").loc[shared]

    cat = present_fields(base, CATEGORICAL_FIELDS)
    cat = [f for f in cat if f in cand.columns]
    if cat:
        print("  CATEGORICAL agreement (on shared rows)")
        for f in cat:
            bv = b[f].astype(str)
            cv = c[f].astype(str)
            agree = float((bv.values == cv.values).mean())
            mism = pd.Series(list(zip(bv.values, cv.values)))[bv.values != cv.values]
            top_flip = ""
            if not mism.empty:
                (fb, fc), k = mism.value_counts().index[0], mism.value_counts().iloc[0]
                top_flip = f"   top flip: {fb}->{fc} x{k}"
            print(f"    {f:<26} agree {agree:6.1%}{top_flip}")

    grad = present_fields(base, GRADED_FIELDS)
    grad = [f for f in grad if f in cand.columns]
    if grad:
        print("  GRADED shift  (baseline -> candidate)")
        for f in grad:
            bn = pd.to_numeric(b[f], errors="coerce").dropna()
            cn = pd.to_numeric(c[f], errors="coerce").dropna()
            if bn.empty or cn.empty:
                continue
            b_dom = bn.astype(str).value_counts(normalize=True).iloc[0]
            c_dom = cn.astype(str).value_counts(normalize=True).iloc[0]
            b_ent = norm_entropy(bn.astype(str).value_counts())
            c_ent = norm_entropy(cn.astype(str).value_counts())
            verdict = ""
            base_degen = b_dom >= degenerate_share or b_ent <= 0.35
            cand_degen = c_dom >= degenerate_share or c_ent <= 0.35
            if base_degen and not cand_degen:
                verdict = "  ✓ candidate discriminates where baseline collapsed"
            elif not base_degen and cand_degen:
                verdict = "  ✗ candidate collapsed a field baseline spread"
            elif base_degen and cand_degen:
                verdict = "  — both degenerate"
            print(
                f"    {f:<26} mean {bn.mean():.2f}->{cn.mean():.2f}  "
                f"dominance {b_dom:4.0%}->{c_dom:4.0%}  entropy {b_ent:.2f}->{c_ent:.2f}{verdict}"
            )


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "source_row" not in df.columns:
        raise SystemExit(f"{path}: no source_row column — not an extraction CSV?")
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description="Profile/diff LLM extraction CSVs (QA harness).")
    ap.add_argument("baseline", help="Baseline extraction CSV (e.g. the Mistral run).")
    ap.add_argument("candidate", nargs="?", help="Optional candidate CSV to diff against baseline (e.g. a V4 run).")
    ap.add_argument("--degenerate-share", type=float, default=0.85, help="Dominance share that flags a field degenerate.")
    args = ap.parse_args()

    base = load(args.baseline)
    profile(base, Path(args.baseline).name, args.degenerate_share)
    if args.candidate:
        cand = load(args.candidate)
        profile(cand, Path(args.candidate).name, args.degenerate_share)
        diff(base, cand, Path(args.baseline).name, Path(args.candidate).name, args.degenerate_share)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
