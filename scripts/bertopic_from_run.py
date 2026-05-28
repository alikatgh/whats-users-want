#!/usr/bin/env python3
"""Stage 2 — validate Stage 1 clusters with BERTopic / c-TF-IDF.

Runs BERTopic on the cached local sentence-transformer embeddings produced by
:mod:`option2_pipeline`. Because we hand BERTopic precomputed embeddings via
``embedding_model=None``, this stage does not download or run any new model —
it only adds a topic-naming layer.

The result is 53 named topics like ``1_diamonds_buy_buy diamonds_money`` plus
the noise topic ``-1`` (1,381 tickets). The noise topic is split in
:mod:`split_outlier_bucket`.

UMAP and HDBSCAN parameters are tuned for support-text density:

* UMAP: ``n_neighbors=25``, ``n_components=8``, ``min_dist=0.0``,
  ``metric="cosine"``, ``random_state=42``.
* HDBSCAN: ``min_cluster_size=35`` (CLI override), ``min_samples=max(5, mc//3)``,
  ``metric="euclidean"``.

Required inputs in the run directory:

* ``semantic_cluster_assignments.csv`` (provides ``model_text`` per ticket)
* ``embeddings_local.npy`` (Stage 1 must have used ``--embedding-backend local``)

Outputs:

* ``bertopic_topics.csv`` — one row per topic with ``Topic``, ``Count``,
  ``Name``, ``Representation``.
* ``bertopic_assignments.csv`` — per-ticket assignment merged with
  Stage 1 metadata.
* ``bertopic_barchart.html`` — top-words-per-topic chart (Plotly).
* ``bertopic_metadata.json`` — run config snapshot.
* Appends a "BERTopic Validation" section to ``executive_findings.md``.

See :doc:`docs/engineering/02-stage2-bertopic` for tuning notes.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


def run(run_dir: Path, min_topic_size: int) -> None:
    """Run BERTopic on the cached embeddings and write topic outputs.

    BERTopic is a topic-modelling pipeline that stitches four ideas together:
    (1) sentence embeddings turn text into dense vectors that capture meaning,
    (2) UMAP squashes those high-dimensional vectors down to a few dimensions
    while preserving neighborhood structure, (3) HDBSCAN groups the squashed
    points into density-based clusters (and a ``-1`` "noise" bucket), and
    (4) c-TF-IDF labels each cluster with the words that distinguish it from
    the others. We hand BERTopic our own pre-cached embeddings via
    ``embedding_model=None`` so this stage is fast and reproducible — no model
    download, no GPU, just clustering plus labelling on top of vectors that
    Stage 1 already paid for.

    Args:
        run_dir: Path to an existing ``outputs/option2_<timestamp>`` directory.
            Must contain ``semantic_cluster_assignments.csv`` and
            ``embeddings_local.npy``.
        min_topic_size: HDBSCAN ``min_cluster_size``. 35 is the empirically
            tuned default; smaller values produce too many tiny topics, larger
            values miss small but real topics.

    Raises:
        FileNotFoundError: If required inputs are missing. The error message
            tells the user how to regenerate.
        ValueError: If embeddings/document count mismatch.

    Teaching:
        c-TF-IDF (class-based TF-IDF) is the heart of BERTopic's labelling.
        Plain TF-IDF asks "how rare is this word across documents?" — it
        weights term frequency (tf) by inverse document frequency
        ``idf = log(N_docs / df_word)``. c-TF-IDF instead concatenates every
        ticket inside a cluster into one mega-document, then asks "how rare is
        this word across **clusters**?" — i.e.
        ``tf_class * log(avg_class_length / freq_word_across_classes)``. The
        result: words that are common inside this cluster but rare in other
        clusters bubble to the top, so each topic gets a label that genuinely
        distinguishes it.

        UMAP parameters explained: ``n_components=8`` reduces 384-D
        sentence-transformer vectors to 8 dimensions — high enough to keep
        useful structure but low enough that HDBSCAN's distance computations
        are meaningful. ``min_dist=0.0`` is critical for clustering: it lets
        UMAP pack near-neighbors right on top of each other, producing tight
        density blobs that HDBSCAN can recognise. (For visualisation you'd
        use ``min_dist=0.1`` to spread points apart, but we want clumps.)
        ``metric="cosine"`` matches how sentence embeddings encode semantic
        similarity (angle, not magnitude). ``random_state=42`` makes the
        stochastic algorithm reproducible across runs.

        HDBSCAN parameters explained: density-based clustering looks for
        regions where points are close together separated by sparser regions.
        ``min_cluster_size=35`` says "a topic must contain at least 35 tickets
        to count as a real topic" — anything smaller becomes noise (the ``-1``
        bucket). For our 6,728 tickets that yields ~53 topics plus 1,381 noise
        tickets. Unlike k-means, HDBSCAN doesn't need you to pre-specify ``k``
        and is happy to leave hard-to-classify points in the noise bucket
        instead of forcing them into a wrong cluster.

        ``fit_transform(docs, embeddings)`` returns ``(topics, probs)``: a
        list of integer topic IDs (one per document, with ``-1`` for noise)
        and an optional probability matrix. We set
        ``calculate_probabilities=False`` because soft assignments are
        expensive and we only need the hard topic ID for downstream merges.

        ``get_topic_info()`` returns a small DataFrame with one row per topic
        (Topic, Count, Name, Representation), and ``visualize_barchart``
        produces a Plotly figure of top words per topic which we save as a
        standalone HTML file with the Plotly JS loaded from CDN
        (``include_plotlyjs="cdn"`` keeps the file small).

        The ``doc_topics.merge(topics_df, left_on="bertopic_topic",
        right_on="Topic", how="left")`` call is a SQL-style left join: every
        ticket on the left gets its matching topic-info columns from the
        right, and tickets whose topic is missing on the right (rare here)
        keep ``NaN``. ``left_on``/``right_on`` are needed because the join
        column has different names on each side.

        Finally, ``report_path.open("a")`` opens the executive findings
        markdown file in **append mode** (the ``"a"`` flag) so we add a new
        BERTopic Validation section without clobbering anything Stage 1 wrote.
    """
    assignments_path = run_dir / "semantic_cluster_assignments.csv"
    embeddings_path = run_dir / "embeddings_local.npy"
    if not assignments_path.exists():
        raise FileNotFoundError(assignments_path)
    if not embeddings_path.exists():
        raise FileNotFoundError(f"{embeddings_path} not found. Run option2_pipeline.py with --embedding-backend local first.")

    docs_df = pd.read_csv(assignments_path)
    docs = docs_df["model_text"].fillna("").astype(str).tolist()
    embeddings = np.load(embeddings_path)
    if len(docs) != len(embeddings):
        raise ValueError(f"doc/embedding mismatch: {len(docs)} docs vs {len(embeddings)} embeddings")

    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    vectorizer = CountVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=3,
        max_df=0.85,
        token_pattern=r"(?u)\b[\w][\w'-]{2,}\b",
    )
    umap_model = UMAP(
        n_neighbors=25,
        n_components=8,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
        n_jobs=1,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_topic_size,
        min_samples=max(5, min_topic_size // 3),
        metric="euclidean",
        prediction_data=False,
    )
    topic_model = BERTopic(
        embedding_model=None,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer,
        calculate_probabilities=False,
        low_memory=True,
        verbose=True,
    )
    topics, _ = topic_model.fit_transform(docs, embeddings)

    topics_df = topic_model.get_topic_info()
    topics_df.to_csv(run_dir / "bertopic_topics.csv", index=False)

    doc_topics = docs_df[["source_row", "manager", "category", "question_kind", "primary_desire", "context_depth_score", "is_unresolved", "model_text"]].copy()
    doc_topics["bertopic_topic"] = topics
    doc_topics = doc_topics.merge(
        topics_df[["Topic", "Name", "Representation", "Count"]],
        left_on="bertopic_topic",
        right_on="Topic",
        how="left",
    ).drop(columns=["Topic"])
    doc_topics.to_csv(run_dir / "bertopic_assignments.csv", index=False)

    try:
        fig = topic_model.visualize_barchart(top_n_topics=24)
        fig.write_html(run_dir / "bertopic_barchart.html", include_plotlyjs="cdn")
    except Exception as exc:
        print(f"[warn] BERTopic barchart failed: {exc}")

    metadata = {
        "run_dir": str(run_dir),
        "docs": len(docs),
        "embeddings_shape": list(embeddings.shape),
        "topics": int(pd.Series(topics).nunique()),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "bertopic_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    report_path = run_dir / "executive_findings.md"
    if report_path.exists():
        lines = [
            "",
            "## BERTopic Validation",
            "",
            f"BERTopic found {metadata['topics']} topics from {metadata['docs']:,} embedded tickets.",
            "Top BERTopic topics:",
        ]
        for _, row in topics_df[topics_df["Topic"] != -1].head(10).iterrows():
            representation = row.get("Representation", "")
            lines.append(f"- Topic {int(row['Topic'])}: {int(row['Count']):,} tickets; {row['Name']}; {representation}")
        with report_path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print(json.dumps(metadata, indent=2))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the BERTopic Stage 2 driver.

    Pulls ``run_dir`` (positional, required) and ``--min-topic-size``
    (optional, default 35) from ``sys.argv`` and returns them as an
    ``argparse.Namespace`` so the ``__main__`` block can hand them to
    :func:`run`.

    Returns:
        argparse.Namespace with attributes ``run_dir`` (str) and
        ``min_topic_size`` (int).

    Teaching:
        ``argparse`` is Python's standard library for declaring CLI
        interfaces. You build a parser, register arguments, and call
        ``parse_args()`` which inspects ``sys.argv`` for you. Two
        conventions worth noticing:

        * ``parser.add_argument("run_dir", ...)`` — no leading dashes makes
          this a **positional** argument (you must pass it). ``argparse``
          maps it to ``args.run_dir``.
        * ``--min-topic-size`` — leading dashes make it an **optional flag**
          with a default. ``argparse`` automatically converts hyphens to
          underscores so you read it as ``args.min_topic_size``.
        * ``type=int`` — ``argparse`` runs every CLI string through this
          callable so you don't have to call ``int(...)`` yourself, and you
          get a friendly error if the user passes ``"thirty-five"``.
    """
    parser = argparse.ArgumentParser(description="Run BERTopic validation for an Option 2 run directory.")
    parser.add_argument("run_dir", help="Path to outputs/option2_<timestamp>")
    parser.add_argument("--min-topic-size", type=int, default=35)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(Path(args.run_dir).expanduser().resolve(), args.min_topic_size)
