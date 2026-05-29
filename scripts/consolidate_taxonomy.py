#!/usr/bin/env python3
"""Consolidate an over-split want taxonomy into a 2-level (parent -> sub-type) tree.

Stage 6 runs flat KMeans with a fixed k, which over-splits dominant themes into
near-duplicate clusters — e.g. on the May-13 Mistral run, 7 look-alike "recovery"
wants and a 0.92-similar pair of "protect community" wants, overall silhouette
~0.15. This pass merges clusters whose CENTROIDS are within --merge-threshold
cosine similarity (average linkage), yielding fewer, better-separated PARENT
themes, each keeping its original clusters as sub-types.

It re-embeds _want_text with the same model the taxonomy used, so the geometry
matches the real clustering. No model API, no pipeline run, no DeepSeek/V4 needed:
it reads only an existing run's user_wants_taxonomy.csv + user_wants_assignments.csv,
and prints a BEFORE/AFTER (flat-k vs consolidated) with a silhouette for each.

The point: the taxonomy can be tightened on the clustering side, today, for free —
independent of which model did the extraction.

Usage:
    python scripts/consolidate_taxonomy.py <run_dir> [--merge-threshold 0.80] [--write]
        --write  also save user_wants_taxonomy_consolidated.csv into <run_dir>
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def parent_label(child_labels: list[str], top_n: int = 4) -> str:
    """Derive a parent label from the most common tokens across child labels."""
    toks: Counter[str] = Counter()
    for lab in child_labels:
        for t in str(lab).split("_"):
            if len(t) > 2:
                toks[t] += 1
    return "_".join(t for t, _ in toks.most_common(top_n)) or "theme"


def main() -> int:
    ap = argparse.ArgumentParser(description="Consolidate an over-split want taxonomy into parent themes.")
    ap.add_argument("run_dir")
    ap.add_argument("--merge-threshold", type=float, default=0.80, help="Merge clusters with centroid cosine sim above this.")
    ap.add_argument("--write", action="store_true", help="Write user_wants_taxonomy_consolidated.csv into the run dir.")
    args = ap.parse_args()
    run = Path(args.run_dir)

    tax = pd.read_csv(run / "user_wants_taxonomy.csv")
    asg = pd.read_csv(run / "user_wants_assignments.csv").dropna(subset=["_want_text"])
    asg["want_id"] = pd.to_numeric(asg["want_id"], errors="coerce")
    asg = asg[asg["want_id"].notna()]
    asg["want_id"] = asg["want_id"].astype(int)
    size = asg["want_id"].value_counts().to_dict()
    label = {int(r.want_id): str(r.want_label) for r in tax.itertuples()}

    from sentence_transformers import SentenceTransformer

    emb = SentenceTransformer(MODEL).encode(
        asg["_want_text"].astype(str).tolist(), batch_size=64, normalize_embeddings=True, show_progress_bar=False
    )
    want_ids = asg["want_id"].to_numpy()

    ids = sorted(set(want_ids))
    centroids = np.vstack([normalize(emb[want_ids == i].mean(0).reshape(1, -1))[0] for i in ids])

    dist = 1.0 - args.merge_threshold
    try:
        agg = AgglomerativeClustering(n_clusters=None, distance_threshold=dist, metric="cosine", linkage="average")
        parent_of_idx = agg.fit_predict(centroids)
    except TypeError:  # older sklearn
        agg = AgglomerativeClustering(n_clusters=None, distance_threshold=dist, affinity="cosine", linkage="average")
        parent_of_idx = agg.fit_predict(centroids)

    want_to_parent = {ids[k]: int(parent_of_idx[k]) for k in range(len(ids))}
    ticket_parent = np.array([want_to_parent[w] for w in want_ids])

    sil_before = silhouette_score(emb, want_ids, metric="cosine")
    n_parents = len(set(parent_of_idx))
    sil_after = silhouette_score(emb, ticket_parent, metric="cosine") if n_parents > 1 else float("nan")

    # group children by parent
    parents: dict[int, list[int]] = {}
    for w, p in want_to_parent.items():
        parents.setdefault(p, []).append(w)
    ordered = sorted(parents.items(), key=lambda kv: -sum(size.get(w, 0) for w in kv[1]))

    total = sum(size.values())
    print(f"BEFORE: {len(ids)} flat wants     silhouette {sil_before:.3f}")
    print(f"AFTER : {n_parents} parent themes  silhouette {sil_after:.3f}   (merge sim > {args.merge_threshold}, avg linkage)\n")

    rows = []
    for pi, (_, children) in enumerate(ordered, 1):
        children = sorted(children, key=lambda w: -size.get(w, 0))
        psize = sum(size.get(w, 0) for w in children)
        plab = parent_label([label.get(w, "") for w in children])
        tag = f"{len(children)} sub-types" if len(children) > 1 else "single"
        print(f"PARENT {pi:>2}: {plab[:40]:<40} {psize:>4}  {psize/total*100:4.1f}%  [{tag}]")
        for w in children:
            mark = "   └─" if len(children) > 1 else "     "
            print(f"{mark} {label.get(w,'')[:46]:<46} {size.get(w,0):>4}")
            rows.append({"parent_id": pi, "parent_label": plab, "parent_size": psize,
                         "want_id": w, "want_label": label.get(w, ""), "want_size": size.get(w, 0)})

    if args.write:
        out = run / "user_wants_taxonomy_consolidated.csv"
        pd.DataFrame(rows).to_csv(out, index=False)
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
