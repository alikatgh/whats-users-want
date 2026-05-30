#!/usr/bin/env python3
"""Side-by-side viewer: the ticket text vs each model's extraction.

Joins enriched_tickets.csv (the actual ticket text) with one or more extraction
CSVs on source_row and prints, per ticket: the ticket + each model's
job / want / money-trust-urgency / emotion. Use it to eyeball whether one model
reads tickets better than another (e.g. DeepSeek V4 vs Mistral) — the human
judgment that no silhouette or entropy number can give you.

PRINTS TICKET TEXT AND UIDs — run locally only; do not paste output into shared
chats or tickets. This is the privacy-sensitive, human-in-the-loop check.

Usage:
  python scripts/show_extractions.py <run_dir> [--n 8] [--source-row ROW] \
      [--csvs ollama_mistral-small3.2-24b_extractions.csv,deepseek_v4_sample.csv]

  # eyeball 8 tickets both models read:
  python scripts/show_extractions.py outputs/option2_20260513_030517

  # focus on the tickets where they DISAGREE on a graded score (pipe to less):
  python scripts/show_extractions.py outputs/option2_20260513_030517 --n 30 | less
"""
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser(description="Side-by-side ticket vs model extractions.")
    ap.add_argument("run_dir")
    ap.add_argument("--n", type=int, default=8, help="How many shared tickets to show.")
    ap.add_argument("--source-row", help="Show one specific source_row instead of a sample.")
    ap.add_argument("--csvs", default="ollama_mistral-small3.2-24b_extractions.csv,deepseek_v4_sample.csv",
                    help="Comma-separated extraction CSV names inside run_dir (first = baseline).")
    args = ap.parse_args()
    run = Path(args.run_dir)

    enr = pd.read_csv(run / "enriched_tickets.csv", dtype=str)
    enr["source_row"] = enr["source_row"].astype(str)
    text_col = "question_flat" if "question_flat" in enr.columns else "question"
    ticket = dict(zip(enr["source_row"], enr[text_col].fillna("")))

    models = []
    for name in [c.strip() for c in args.csvs.split(",") if c.strip()]:
        df = pd.read_csv(run / name, dtype=str).drop_duplicates("source_row")
        df["source_row"] = df["source_row"].astype(str)
        label = name.replace("_extractions.csv", "").replace(".csv", "")
        models.append((label, df.set_index("source_row")))

    shared = set(models[0][1].index)
    for _, df in models[1:]:
        shared &= set(df.index)
    rows = [args.source_row] if args.source_row else sorted(shared)[: args.n]

    for sr in rows:
        if sr not in shared:
            print(f"source_row {sr}: not shared across all models"); continue
        print("=" * 92)
        print(f"source_row {sr}")
        print("TICKET:", textwrap.shorten(str(ticket.get(sr, "(missing)")), width=440, placeholder=" …"))
        for label, df in models:
            r = df.loc[sr]
            print(f"  [{label[:24]:<24}] job={r.get('job_to_be_done','?'):<18} "
                  f"money={r.get('money_risk_level','?')} trust={r.get('trust_risk_level','?')} "
                  f"urg={r.get('urgency_level','?')}  emo={r.get('user_emotion','?'):<10} conf={r.get('confidence','?')}")
            print(f"      want: {textwrap.shorten(str(r.get('actual_user_want','')), width=120, placeholder=' …')}")
    print("=" * 92)
    print(f"shown {len(rows)} ticket(s) across {len(models)} model(s): {', '.join(m for m,_ in models)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
