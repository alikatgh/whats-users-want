#!/usr/bin/env python3
"""Stage 4 — split BERTopic noise into 26 sub-themes.

BERTopic assigns ``topic = -1`` to tickets it cannot confidently cluster. With
1,381 tickets in there, that "topic" is the largest single group in the dataset.
This stage refuses to lose that signal: it slices the cached multilingual
embeddings down to the noise rows and runs a forced MiniBatchKMeans (so every
ticket gets a sub-theme) plus a TF-IDF labelling pass.

It also re-runs :func:`insight_layer.build_opportunity_backlog` after replacing
``issue_id == -1`` rows with ``outlier_<sub_id>`` rows, producing a refined
backlog where the noise bucket is broken into actionable items.

Required inputs in the run directory:

* ``semantic_cluster_assignments.csv`` (Stage 1)
* ``bertopic_assignments.csv`` (Stage 2)
* ``embeddings_local.npy`` (Stage 1, local backend)

Outputs:

* ``outlier_subtopics.csv`` — one row per sub-theme.
* ``outlier_subtopic_assignments.csv`` — per-ticket sub-theme assignment with
  per-row confidence (computed from KMeans transform distances).
* ``outlier_subtopic_map.html`` — interactive 2D UMAP map.
* ``refined_opportunity_backlog.csv`` — Stage 3 backlog with noise replaced.
* ``outlier_split_workbook.xlsx``, ``outlier_split_metrics.csv``,
  ``outlier_split_metadata.json``.
* "Outlier Split" section appended to ``executive_findings.md``.

The number of sub-themes ``k`` is auto-chosen via
``round(sqrt(n_docs / 2))`` clamped to [8, 32]. For 1,331 docs this yields
26. Override with ``--n-subtopics``.

See :doc:`docs/engineering/04-stage4-outlier-split` for design notes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

if not os.environ.get("LOKY_MAX_CPU_COUNT", "").strip():
    os.environ["LOKY_MAX_CPU_COUNT"] = str(max(1, (os.cpu_count() or 2) - 1))

import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize


def latest_run(outputs_dir: Path) -> Path:
    """Return the newest ``option2_<timestamp>`` run folder that has finished Stage 0.

    Each pipeline run lives under ``outputs/option2_YYYYMMDD_HHMMSS/``. Stage 4
    (this script) needs Stage 1's outputs, so we keep only folders that already
    contain ``enriched_tickets.csv`` (the Stage 0/1 sentinel). The default
    behaviour of the CLI is "operate on the most recent run", which is what this
    helper resolves.

    Args:
        outputs_dir: The parent ``outputs/`` directory that holds every run.

    Returns:
        Path to the most recent valid run folder.

    Raises:
        FileNotFoundError: If no valid run folders exist under ``outputs_dir``.

    Teaching:
        ``Path.glob("option2_*")`` yields paths in arbitrary order. Because the
        timestamp suffix is zero-padded ISO-style (``YYYYMMDD_HHMMSS``), plain
        lexicographic ``sorted(...)`` puts them in chronological order, and
        ``[-1]`` picks the newest. This "sorted glob with timestamped names"
        idiom is the simplest way to do "give me the latest run" without
        reading file mtimes (which can lie if folders are copied around).
    """
    runs = sorted([p for p in outputs_dir.glob("option2_*") if (p / "enriched_tickets.csv").exists()])
    if not runs:
        raise FileNotFoundError(f"No option2_* run folders under {outputs_dir}")
    return runs[-1]


def compact(text: str, max_len: int = 520) -> str:
    """Collapse whitespace and truncate a ticket excerpt to a fixed length.

    The "example_1..example_4" columns we attach to every sub-theme summary need
    to fit in an Excel cell and read well in markdown. Real tickets are full of
    newlines, double spaces, and HTML residue, so we squeeze all whitespace runs
    down to a single space first, then truncate with an ellipsis.

    Args:
        text: Raw ticket text. Anything is accepted (NaN, ints, etc.); it is
            coerced to ``str`` first.
        max_len: Maximum length of the returned string, including the ``"..."``.

    Returns:
        A single-line string no longer than ``max_len``.

    Teaching:
        Two idioms in three lines.

        1. ``re.sub(r"\\s+", " ", ...)`` — ``\\s+`` matches one or more
           whitespace characters (spaces, tabs, newlines), and we replace each
           run with a single space. This is the standard "normalise whitespace"
           pattern; ``str.split()/join()`` would also work but is less explicit.
        2. The truncation idiom ``s[: max_len - 3].rstrip() + "..."``: cut to
           three less than the limit (to leave room for the ellipsis), strip
           any trailing space we created by chopping mid-token, then append the
           ellipsis. Doing it this way (vs ``textwrap.shorten``) keeps it
           predictable and avoids word-boundary surprises.
    """
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= max_len else text[: max_len - 3].rstrip() + "..."


def slug_terms(terms: list[str]) -> str:
    """Build a short snake_case-ish identifier from the top TF-IDF terms.

    Sub-theme labels look like ``outlier_07_recover_account_access_login_unban``.
    The numeric prefix is added by the caller; this helper produces the trailing
    ``recover_account_access_login_unban`` part from the cluster's top terms.

    Args:
        terms: Ordered list of significant terms (most important first).

    Returns:
        Up to five lowercase tokens joined with underscores. Returns the
        literal string ``"mixed"`` if no usable token survives cleaning.

    Teaching:
        Three things going on in this loop:

        1. ``re.sub(r"[^a-zA-Z0-9]+", "_", term.lower())`` — anything that's
           not a letter or digit becomes an underscore. This handles spaces
           (multi-word n-grams like ``"login screen"``), punctuation, accents
           that survived earlier normalisation, etc.
        2. ``.strip("_")`` removes leading/trailing underscores left over after
           substitution (e.g. a term like ``"--login"`` becomes ``"_login"``,
           then ``"login"``).
        3. The de-duplication ``token not in cleaned`` and the early-exit
           ``len(cleaned) >= 5`` keep the slug short and readable when the same
           token appears in both unigrams and bigrams (e.g. ``"login"`` and
           ``"login screen"`` both yield ``"login"``-prefixed tokens).
    """
    cleaned = []
    for term in terms:
        token = re.sub(r"[^a-zA-Z0-9]+", "_", term.lower()).strip("_")
        if token and token not in cleaned:
            cleaned.append(token)
        if len(cleaned) >= 5:
            break
    return "_".join(cleaned) or "mixed"


def top_join(series: pd.Series, n: int = 5) -> str:
    """Comma-join the ``n`` most common non-empty values of a pandas Series.

    Used to summarise a sub-theme by its top managers / categories / desires:
    given a Series like ``["billing", "billing", "support", "", NaN, "billing"]``
    with ``n=2``, we get ``"billing, support"``.

    Args:
        series: Any pandas Series (typically a column slice of a sub-cluster).
        n: How many of the most frequent values to keep.

    Returns:
        Comma-separated string of the top ``n`` values, or ``""`` if the
        series has no usable entries.

    Teaching:
        This is a five-step pandas idiom worth memorising:

        * ``.dropna()`` — drop ``NaN``/``None`` (CSVs often have these).
        * ``.astype(str)`` — guarantee string dtype before string ops.
        * ``s.str.strip().ne("")`` — boolean mask removing rows that are empty
          after trimming whitespace. ``ne`` reads as "not equal to".
        * ``.value_counts()`` — sort unique values by frequency, descending.
        * ``.head(n).index.tolist()`` — take the top ``n`` and grab their
          values from the index (since ``value_counts`` puts the values into
          the index of the resulting Series).

        Then ``", ".join(...)`` produces the human-readable summary.
    """
    s = series.dropna().astype(str)
    s = s[s.str.strip().ne("")]
    if s.empty:
        return ""
    return ", ".join(s.value_counts().head(n).index.tolist())


def choose_k(n_docs: int, requested: int | None) -> int:
    """Pick the number of sub-clusters ``k`` for the noise bucket.

    BERTopic's outlier bucket has 1,381 tickets in our dataset. Splitting it
    into 2 clusters loses information; splitting it into 200 just hides noise
    inside more noise. We need a ``k`` that scales with data size but stays in
    a useful band.

    Args:
        n_docs: How many tickets are in the noise bucket (≈ 1,381 for us).
        requested: ``--n-subtopics`` from the CLI, or ``None`` to auto-pick.

    Returns:
        The chosen ``k``, always at least 3.

    Teaching:
        The auto-formula is ``round(sqrt(n_docs / 2))`` clamped to ``[8, 32]``.

        * Why ``sqrt(n)``? In clustering literature, "rule of thumb" choices
          for ``k`` often grow as ``sqrt(n)`` because it gives roughly equal
          weight to the number of clusters and the average cluster size: each
          group ends up with about ``sqrt(n)`` items, which keeps both the
          per-cluster sample and the number of clusters interpretable.
        * The ``/ 2`` is a soft prior that says "we expect coarse themes, not
          fine-grained ones in this bucket".
        * Clamping to ``[8, 32]`` keeps the output dashboard-sized: fewer than
          8 sub-themes is barely better than the single ``-1`` bucket; more
          than 32 is overwhelming.

        For our 1,331 noise-bucket docs (after re-merging),
        ``round(sqrt(1331/2)) = round(sqrt(665.5)) = round(25.8) = 26``,
        which is why the file header advertises 26.

        The manual-override branch ``min(requested, n_docs // 12)`` enforces
        "at least 12 docs per cluster on average", a sanity check against
        ``--n-subtopics 200`` on a 100-doc set.
    """
    if requested:
        return max(3, min(requested, max(3, n_docs // 12)))
    return max(8, min(32, round(math.sqrt(n_docs / 2))))


def load_inputs(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Load Stage 1 + Stage 2 outputs and verify they line up by row count.

    This stage cannot work without three artefacts produced by earlier stages:

    * the semantic cluster assignments (gives us ``model_text`` and metadata),
    * the BERTopic assignments (tells us which rows are in topic ``-1``),
    * the cached embedding matrix (so we don't have to re-embed 6,728 tickets).

    Args:
        run_dir: The run folder, e.g. ``outputs/option2_20260101_120000``.

    Returns:
        ``(semantic_df, bert_df, embeddings)`` where ``embeddings`` is an
        ``(N, dim)`` ``np.ndarray`` aligned row-for-row with ``semantic_df``.

    Raises:
        FileNotFoundError: If any of the three input files is missing. Each
            error message mentions the upstream script to run.
        ValueError: If the embedding matrix has a different number of rows
            than the semantic CSV — that means the run is corrupted.

    Teaching:
        Two patterns to notice:

        1. **Defensive input validation** — we check each file's existence
           with a tailored error message *before* doing any real work. The
           messages name the script you need to run to produce the missing
           file. This is far more useful than letting ``pd.read_csv`` raise
           a generic ``FileNotFoundError`` deep inside the call stack.
        2. **Row-count invariant check** — embeddings live in a NumPy ``.npy``
           file (loaded via ``np.load``) while metadata lives in a CSV. They
           are aligned positionally: row ``i`` of the embedding matrix
           corresponds to row ``i`` of the CSV. The only way to reuse cached
           embeddings safely is to *verify* this invariant. ``ValueError`` is
           the conventional choice for "your inputs are well-formed but
           inconsistent".
    """
    sem_path = run_dir / "semantic_cluster_assignments.csv"
    bert_path = run_dir / "bertopic_assignments.csv"
    emb_path = run_dir / "embeddings_local.npy"
    if not sem_path.exists():
        raise FileNotFoundError(sem_path)
    if not bert_path.exists():
        raise FileNotFoundError(f"{bert_path} missing. Run scripts/bertopic_from_run.py first.")
    if not emb_path.exists():
        raise FileNotFoundError(f"{emb_path} missing. Run local embedding pipeline first.")
    semantic = pd.read_csv(sem_path)
    semantic["source_row"] = semantic["source_row"].astype(str)
    bert = pd.read_csv(bert_path)
    bert["source_row"] = bert["source_row"].astype(str)
    embeddings = np.load(emb_path)
    if len(semantic) != len(embeddings):
        raise ValueError(f"embedding/semantic row mismatch: {len(embeddings)} embeddings vs {len(semantic)} rows")
    return semantic, bert, embeddings


def make_subtopic_labels(outlier: pd.DataFrame, labels: np.ndarray, vectorizer: TfidfVectorizer, tfidf) -> dict[int, list[str]]:
    """Compute the top 12 TF-IDF terms for each KMeans sub-cluster.

    Args:
        outlier: The outlier-rows DataFrame (unused here but kept for symmetry
            and future enhancements like per-cluster metadata).
        labels: KMeans cluster id for each row, shape ``(n_docs,)``.
        vectorizer: The fitted ``TfidfVectorizer`` (we need its vocabulary).
        tfidf: The sparse ``(n_docs, n_terms)`` TF-IDF matrix.

    Returns:
        A dict mapping ``cluster_id -> [term, term, ...]`` (up to 12 terms
        per cluster, ordered by within-cluster mean TF-IDF, descending).

    Teaching:
        This is **c-TF-IDF in spirit**. Classic TF-IDF scores each term
        per-document; class-based TF-IDF (used by BERTopic) treats each
        cluster as one big "super-document" and scores terms there. Here we
        use a simpler proxy: the *mean* per-document TF-IDF inside the
        cluster. Terms that are frequent and distinctive across the cluster
        bubble up, terms that only appear in one outlier ticket are washed
        out by the average.

        NumPy idioms in three steps:

        1. ``np.unique(labels)`` returns the sorted unique cluster ids; we
           iterate them in ascending order so cluster 0's terms come first.
        2. ``np.where(labels == label)[0]`` returns the *integer indices* of
           the rows belonging to ``label``. ``np.where`` returns a tuple
           because labels could be N-D; ``[0]`` unpacks the 1-D case.
        3. ``mean_tfidf.argsort()[-14:][::-1]`` is the canonical "top-K
           descending" pattern: ``argsort`` gives ascending order, ``[-14:]``
           takes the largest 14 (still ascending), ``[::-1]`` reverses to
           descending. We grab 14 candidates but cap at 12 after filtering
           out terms whose mean is exactly 0 (a term might not appear in any
           doc of this cluster).
    """
    terms = np.asarray(vectorizer.get_feature_names_out())
    labels_to_terms: dict[int, list[str]] = {}
    for label in sorted(np.unique(labels)):
        idx = np.where(labels == label)[0]
        mean_tfidf = np.asarray(tfidf[idx].mean(axis=0)).ravel()
        top_idx = mean_tfidf.argsort()[-14:][::-1]
        labels_to_terms[int(label)] = [str(terms[i]) for i in top_idx if mean_tfidf[i] > 0][:12]
    return labels_to_terms


def split_outliers(run_dir: Path, n_subtopics: int | None, outlier_topic: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Force-cluster the BERTopic noise bucket with MiniBatchKMeans.

    BERTopic refused to label these tickets (HDBSCAN parked them in topic
    ``-1``). That is 1,381 tickets — about 21% of the 6,728-ticket corpus —
    quietly thrown away. This function rescues them by switching algorithms:
    KMeans does not have a "noise" option; every point lands in some cluster.
    The trade-off is that some sub-clusters will be soft (low silhouette,
    low confidence), which is why we attach a per-row confidence column the
    dashboard can filter on.

    Args:
        run_dir: Existing run directory with semantic + bertopic outputs and
            cached embeddings.
        n_subtopics: Forced k (passed through with a sanity floor/ceiling). If
            None, k is auto-chosen as ``round(sqrt(n_docs/2))`` clamped to [8, 32].
        outlier_topic: Which BERTopic topic to split. Default ``-1`` (the
            actual noise bucket).

    Returns:
        Tuple of three DataFrames: per-ticket assignments (with embedding_row,
        sub_id, confidence, terms, label), per-sub-theme summary (size, avg
        context, terms, examples), and a metrics DataFrame including the
        cosine silhouette on a 1,200-row sample.

    Raises:
        ValueError: If fewer than 50 outlier rows exist (cluster split is not
            statistically meaningful).

    Teaching:
        Walk through the body in five conceptual blocks.

        **1. Embedding alignment.** When we filter ``merged`` down to just the
        outlier rows, ``reset_index(drop=False)`` preserves the original row
        index as a new column ``embedding_row``. We then index the global
        embedding matrix with that column: ``embeddings[outlier["embedding_row"]
        .to_numpy()]``. This is critical — the embeddings live in the original
        UMAP/multilingual space, so we *cannot* re-embed; we have to slice the
        existing matrix while remembering each ticket's original row.

        **2. KMeans (mini-batch).** ``MiniBatchKMeans(n_clusters=k, n_init=30,
        batch_size=512)`` differs from plain KMeans in two ways. *Mini-batch*
        means the algorithm updates centroids using small random subsets of
        512 rows at a time instead of every point on every iteration; this
        scales to large datasets and tends to converge in a fraction of the
        time. *``n_init=30``* means it runs the whole fit thirty times with
        thirty different random seeds, then keeps the best one (lowest
        inertia) — a brute-force defence against KMeans's well-known
        sensitivity to initialisation.

        **3. Per-row confidence.** ``km.transform(X)`` returns the
        ``(n_docs, k)`` matrix of distances from each row to each centroid.
        We take the distance to the *chosen* centroid for each row
        (``distances[np.arange(n), labels]``) and divide by the row's mean
        distance to all centroids. A row that is much closer to its own
        centroid than to the others gets a small ratio, so ``1 - ratio`` is
        close to 1 (high confidence). A row that is roughly equidistant from
        every centroid gets a ratio near 1, so confidence is near 0. We clip
        to ``[0, 1]`` because numerical noise can push it slightly outside.

        **4. Labelling.** A separate ``TfidfVectorizer`` is fit on the cleaned
        ``model_text`` column (English stop-words, unigrams + bigrams, 3-document
        minimum) and ``make_subtopic_labels`` extracts the top terms per
        cluster. The slug ``outlier_07_recover_account_login_unban`` is then
        built from the cluster id plus those terms.

        **5. Quality check (silhouette).** The silhouette score for one row is
        ``(b - a) / max(a, b)`` where ``a`` is its mean distance to its own
        cluster and ``b`` is its mean distance to the *nearest other* cluster.
        It is +1 for a tight, well-separated cluster, 0 for ambiguous, -1 for
        misassigned. Computing it on all 1,381 rows is O(n^2); we sample 1,200
        with NumPy's ``default_rng`` for a quick proxy. We use ``metric=
        "cosine"`` because embeddings live on the unit hypersphere.
    """
    semantic, bert, embeddings = load_inputs(run_dir)
    merged = semantic.merge(
        bert[["source_row", "bertopic_topic", "Name", "Representation", "Count"]],
        on="source_row",
        how="left",
    )
    outlier_mask = pd.to_numeric(merged["bertopic_topic"], errors="coerce").eq(outlier_topic)
    outlier = merged.loc[outlier_mask].copy().reset_index(drop=False).rename(columns={"index": "embedding_row"})
    if len(outlier) < 50:
        raise ValueError(f"Only {len(outlier)} rows in outlier topic {outlier_topic}; not enough to split")

    X = embeddings[outlier["embedding_row"].to_numpy()]
    X = normalize(X)
    docs = outlier["model_text"].fillna("").astype(str).tolist()
    k = choose_k(len(outlier), n_subtopics)
    km = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=30, batch_size=512)
    labels = km.fit_predict(X)
    distances = km.transform(X)
    confidence = 1 - (distances[np.arange(len(labels)), labels] / np.maximum(distances.mean(axis=1), 1e-9))
    confidence = np.clip(confidence, 0, 1)

    vectorizer = TfidfVectorizer(
        max_features=7000,
        min_df=3,
        max_df=0.85,
        ngram_range=(1, 2),
        lowercase=True,
        strip_accents="unicode",
        stop_words="english",
        token_pattern=r"(?u)\b[\w][\w'-]{2,}\b",
    )
    tfidf = vectorizer.fit_transform(docs)
    terms_by_label = make_subtopic_labels(outlier, labels, vectorizer, tfidf)

    assignments = outlier.copy()
    assignments["outlier_subtopic_id"] = labels.astype(int)
    assignments["outlier_subtopic_confidence"] = np.round(confidence, 4)
    assignments["outlier_subtopic_terms"] = assignments["outlier_subtopic_id"].map(lambda x: ", ".join(terms_by_label.get(int(x), [])[:10]))
    assignments["outlier_subtopic_label"] = assignments["outlier_subtopic_id"].map(lambda x: f"outlier_{int(x):02d}_{slug_terms(terms_by_label.get(int(x), []))}")

    summaries = []
    for label, sub in assignments.groupby("outlier_subtopic_id"):
        terms = terms_by_label.get(int(label), [])
        examples = sub.sort_values(["context_depth_score", "outlier_subtopic_confidence"], ascending=False).head(4)["model_text"].map(compact).tolist()
        summaries.append(
            {
                "outlier_subtopic_id": int(label),
                "outlier_subtopic_label": f"outlier_{int(label):02d}_{slug_terms(terms)}",
                "tickets": int(len(sub)),
                "share_of_outlier": round(len(sub) / len(assignments), 4),
                "avg_confidence": round(float(sub["outlier_subtopic_confidence"].mean()), 4),
                "avg_context_score": round(float(sub["context_depth_score"].mean()), 2),
                "rich_or_forensic_share": round(float(sub["context_depth_score"].ge(35).mean()), 4),
                "unresolved_share": round(float(sub["is_unresolved"].astype(str).str.lower().isin(["true", "1"]).mean()), 4),
                "top_terms": ", ".join(terms[:12]),
                "top_desires": top_join(sub["primary_desire"], 5),
                "top_categories": top_join(sub["category"], 5),
                "top_managers": top_join(sub["manager"], 5),
                "example_1": examples[0] if len(examples) > 0 else "",
                "example_2": examples[1] if len(examples) > 1 else "",
                "example_3": examples[2] if len(examples) > 2 else "",
                "example_4": examples[3] if len(examples) > 3 else "",
            }
        )
    summary = pd.DataFrame(summaries).sort_values(["tickets", "avg_context_score"], ascending=False)

    metrics = []
    try:
        sample_n = min(1200, len(X))
        rng = np.random.default_rng(42)
        sample = rng.choice(len(X), sample_n, replace=False)
        sil = silhouette_score(X[sample], labels[sample], metric="cosine")
        metrics.append({"metric": "silhouette_cosine_sample", "value": round(float(sil), 4)})
    except Exception as exc:
        metrics.append({"metric": "silhouette_cosine_sample_error", "value": str(exc)})
    metrics += [
        {"metric": "outlier_topic", "value": outlier_topic},
        {"metric": "outlier_docs", "value": int(len(assignments))},
        {"metric": "subtopics", "value": int(k)},
    ]
    metrics_df = pd.DataFrame(metrics)
    return assignments, summary, metrics_df


def write_refined_backlog(run_dir: Path, assignments: pd.DataFrame) -> pd.DataFrame | None:
    """Re-run Stage 3's opportunity backlog with sub-themes replacing topic ``-1``.

    Stage 3 (``insight_layer.build_opportunity_backlog``) groups tickets by
    ``issue_id`` and ranks them. As long as everything in the noise bucket
    shared ``issue_id == "-1"``, the backlog had a single useless mega-row at
    the top: "Issue -1: 1,381 tickets, recommended action: investigate". Now
    that we have sub-theme labels, we can swap in ``outlier_<sub_id>`` for
    each noise ticket and let Stage 3 re-rank them as 26 actionable rows.

    Args:
        run_dir: The current run directory.
        assignments: Per-ticket sub-theme assignments returned by
            :func:`split_outliers`.

    Returns:
        The refined opportunity backlog DataFrame, or ``None`` if the import
        of ``insight_layer`` fails (e.g. missing optional dependency).

    Teaching:
        Two patterns to highlight.

        * **Module-as-library reuse.** ``insight_layer.py`` is a sibling
          script that exposes ``build_opportunity_backlog`` and ``load_run``
          as ordinary callable functions. We add this script's directory to
          ``sys.path`` so Python can import its sibling, then call those
          functions directly. This is how you avoid duplicating Stage 3's
          ranking logic — instead of copy-pasting it, you treat the script
          like a library.
        * **Targeted column overwrite via masked ``.loc``.** The mask
          ``df["outlier_subtopic_label"].notna() & df["issue_id"].eq("-1")``
          identifies exactly the rows we want to update; ``df.loc[mask, col]
          = ...`` writes back to those positions. This is the safe pandas
          pattern — never use chained indexing (``df[mask][col] = ...``),
          which assigns into a copy and silently does nothing.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from insight_layer import build_opportunity_backlog, load_run  # type: ignore
    except Exception as exc:
        print(f"[warn] could not import insight layer for refined backlog: {exc}")
        return None
    df, _, _ = load_run(run_dir)
    repl = assignments[["source_row", "outlier_subtopic_id", "outlier_subtopic_label"]].copy()
    repl["source_row"] = repl["source_row"].astype(str)
    df = df.merge(repl, on="source_row", how="left")
    mask = df["outlier_subtopic_label"].notna() & df["issue_id"].eq("-1")
    df.loc[mask, "issue_id"] = "outlier_" + df.loc[mask, "outlier_subtopic_id"].astype(int).astype(str)
    df.loc[mask, "issue_label"] = df.loc[mask, "outlier_subtopic_label"]
    refined = build_opportunity_backlog(df)
    refined.to_csv(run_dir / "refined_opportunity_backlog.csv", index=False)
    return refined


def create_map(run_dir: Path, assignments: pd.DataFrame, embeddings: np.ndarray | None = None) -> None:
    """Render an interactive 2-D UMAP scatter of the outlier sub-themes.

    The full pipeline produces a map of all 6,728 tickets. That map is
    dominated by the well-formed clusters; the noise bucket is a grey blob in
    the middle. This function renders only the outlier rows, projected
    independently, so each sub-theme has room to spread out.

    Args:
        run_dir: Run directory; the HTML is written there as
            ``outlier_subtopic_map.html``.
        assignments: Per-ticket DataFrame with ``embedding_row`` and
            ``outlier_subtopic_label`` columns.
        embeddings: Pre-loaded embedding matrix; if ``None`` we reload it
            from disk (handy when called as a side effect later in the
            pipeline).

    Teaching:
        * **Lazy imports.** ``plotly`` and ``umap`` are heavy; importing them
          only inside the function (and inside a try/except) means the rest
          of the pipeline still runs if either library is missing. The
          warning is printed instead of raised so a missing visualisation
          doesn't kill the whole run.
        * **UMAP for visualisation.** ``UMAP(n_components=2, n_neighbors=20,
          min_dist=0.08, metric="cosine")`` projects the high-dimensional
          embeddings to 2-D for plotting. ``cosine`` matches the embedding
          space; ``min_dist=0.08`` keeps points tightly grouped (good for
          spotting clusters); ``n_neighbors=20`` is a moderate "global vs
          local" trade-off.
        * **WebGL rendering.** Plotly's default scatter uses SVG, which slows
          to a crawl past a few thousand points. With ~1,381 dots ``px.scatter``
          will switch to ``render_mode="webgl"`` automatically when given a
          DataFrame this size, which means the browser renders points on the
          GPU and stays responsive.
        * **``include_plotlyjs="cdn"``** keeps the HTML small (~50 KB) by
          loading Plotly from a CDN instead of inlining the 3 MB library.
    """
    try:
        import plotly.express as px
        import umap
    except Exception as exc:
        print(f"[warn] outlier map skipped: {exc}")
        return
    try:
        if embeddings is None:
            _, _, embeddings = load_inputs(run_dir)
        X = normalize(embeddings[assignments["embedding_row"].to_numpy()])
        coords = umap.UMAP(
            n_components=2,
            n_neighbors=20,
            min_dist=0.08,
            metric="cosine",
            random_state=42,
            n_jobs=1,
        ).fit_transform(X)
        plot_df = assignments.copy()
        plot_df["x"] = coords[:, 0]
        plot_df["y"] = coords[:, 1]
        fig = px.scatter(
            plot_df,
            x="x",
            y="y",
            color="outlier_subtopic_label",
            hover_data=["source_row", "manager", "category", "primary_desire", "context_depth_score", "outlier_subtopic_terms"],
            title="Split of BERTopic outlier bucket into subthemes",
            height=850,
        )
        fig.write_html(run_dir / "outlier_subtopic_map.html", include_plotlyjs="cdn")
    except Exception as exc:
        print(f"[warn] outlier map failed: {exc}")


def write_outputs(run_dir: Path, assignments: pd.DataFrame, summary: pd.DataFrame, metrics: pd.DataFrame, refined: pd.DataFrame | None) -> None:
    """Persist Stage 4 results as CSV, multi-sheet Excel, and DuckDB tables.

    Different consumers read different formats: pandas users want CSV, the
    business team wants a single ``.xlsx`` they can email around, and the
    SQL-leaning analysts want DuckDB so they can ``JOIN`` against earlier
    stages. Producing all three keeps everyone happy.

    Args:
        run_dir: Where to write the files.
        assignments: Per-ticket sub-theme assignments.
        summary: Per-sub-theme summary rows.
        metrics: Quality metrics (silhouette, sizes).
        refined: The refined opportunity backlog or ``None`` if Stage 3's
            module wasn't importable.

    Teaching:
        * **``pd.ExcelWriter`` context manager.** Opening one writer and
          calling ``to_excel`` on it multiple times produces a workbook with
          one sheet per call — much better than writing four separate
          ``.xlsx`` files. The ``with`` block ensures the file is closed and
          the openpyxl engine flushes buffers cleanly.
        * **``CREATE OR REPLACE TABLE``.** DuckDB lets us register a pandas
          DataFrame as a temporary view (``con.register("_tmp", table)``)
          and then materialise it as a real table with one SQL statement.
          ``CREATE OR REPLACE`` is idempotent: re-running this script
          overwrites the previous table without an error. ``con.unregister``
          tidies up the view name so the next loop iteration can reuse it.
        * **Optional output handling.** If ``refined`` is ``None`` we just
          skip that sheet/table — outputs are *additive* and a missing
          optional file should never crash the writer.
    """
    assignments.to_csv(run_dir / "outlier_subtopic_assignments.csv", index=False)
    summary.to_csv(run_dir / "outlier_subtopics.csv", index=False)
    metrics.to_csv(run_dir / "outlier_split_metrics.csv", index=False)
    with pd.ExcelWriter(run_dir / "outlier_split_workbook.xlsx", engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="outlier_subtopics", index=False)
        assignments.to_excel(writer, sheet_name="assignments", index=False)
        metrics.to_excel(writer, sheet_name="metrics", index=False)
        if refined is not None:
            refined.to_excel(writer, sheet_name="refined_backlog", index=False)
    try:
        import duckdb
        con = duckdb.connect(str(run_dir / "analysis.duckdb"))
        for name, table in {
            "outlier_subtopics": summary,
            "outlier_subtopic_assignments": assignments,
            "outlier_split_metrics": metrics,
            "refined_opportunity_backlog": refined,
        }.items():
            if table is None:
                continue
            con.register("_tmp", table)
            con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM _tmp')
            con.unregister("_tmp")
        con.close()
    except Exception as exc:
        print(f"[warn] DuckDB write skipped: {exc}")


def append_report(run_dir: Path, summary: pd.DataFrame, metrics: pd.DataFrame, refined: pd.DataFrame | None) -> None:
    """Append (or replace) an "Outlier Split" section in ``executive_findings.md``.

    ``executive_findings.md`` is the one human-readable narrative the pipeline
    produces. Stage 0/1/2/3 each append their own section to it; Stage 4 adds
    the "Outlier Split" section. Re-running Stage 4 should *replace* its
    section, not duplicate it — hence the marker pattern.

    Args:
        run_dir: Run directory containing ``executive_findings.md`` (or not,
            in which case it is created).
        summary: Per-sub-theme summary (top 12 rows are quoted as bullets).
        metrics: Used to look up the headline numbers (doc count, k).
        refined: Refined backlog; if present, top 8 items are listed.

    Teaching:
        * **Marker-based section idempotency.** We define ``marker = "\\n## Outlier
          Split\\n"``. If that marker is already in the file (from a previous
          run), we keep everything *before* it and discard everything after,
          then write the fresh section. This is the simplest pattern for
          "re-running this stage shouldn't pile up duplicate sections" — no
          parsing libraries needed.
        * **``str.split(marker, 1)``** with ``maxsplit=1`` ensures we only
          split on the first occurrence, even if a marker accidentally
          appears later in the document.
        * **List-of-strings then ``join``.** Building the markdown as a list
          and joining at the end is faster and easier to read than repeated
          ``+=`` string concatenation.
    """
    report = run_dir / "executive_findings.md"
    existing = report.read_text(encoding="utf-8") if report.exists() else ""
    marker = "\n## Outlier Split\n"
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip() + "\n"
    lines = [
        "",
        "## Outlier Split",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Split {int(metrics.loc[metrics['metric'].eq('outlier_docs'), 'value'].iloc[0]):,} outlier tickets into {int(metrics.loc[metrics['metric'].eq('subtopics'), 'value'].iloc[0])} forced semantic subtopics.",
        "",
        "### Largest Outlier Subtopics",
    ]
    for _, row in summary.head(12).iterrows():
        lines.append(
            f"- {row['outlier_subtopic_label']}: {int(row['tickets'])} tickets, unresolved {row['unresolved_share']:.1%}, context {row['avg_context_score']}; terms: {row['top_terms']}"
        )
    if refined is not None:
        lines += ["", "### Top Refined Backlog Items", ""]
        for _, row in refined.head(8).iterrows():
            lines.append(
                f"- {row['issue_label']}: score {row['opportunity_score']}, {int(row['tickets'])} tickets; {row['recommended_action']}"
            )
    lines += [
        "",
        "### Additional Files",
        "",
        "- outlier_subtopics.csv",
        "- outlier_subtopic_assignments.csv",
        "- refined_opportunity_backlog.csv",
        "- outlier_subtopic_map.html",
        "- outlier_split_workbook.xlsx",
    ]
    report.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    """Stage 4 orchestrator: resolve inputs, cluster, label, write everything.

    Args:
        args: Parsed CLI arguments from :func:`parse_args`.

    Teaching:
        This is the **orchestrator pattern**. Every step has its own
        function with a clear contract; ``run`` just composes them in the
        right order and forwards data between them:

        1. Pick a run directory (explicit or latest).
        2. ``split_outliers`` does the clustering + labelling.
        3. ``write_refined_backlog`` re-ranks Stage 3 with the new labels.
        4. ``create_map`` renders the UMAP HTML.
        5. ``write_outputs`` writes CSV/Excel/DuckDB.
        6. ``append_report`` updates the markdown report.
        7. A small JSON metadata file is written and echoed to stdout —
           handy for orchestration tools that want to know what just ran.

        Because each step is its own function, the script doubles as a
        library: a Jupyter notebook could ``from split_outlier_bucket import
        split_outliers`` and skip the file-writing entirely.
    """
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else latest_run(Path(args.outputs_dir).expanduser().resolve())
    assignments, summary, metrics = split_outliers(run_dir, args.n_subtopics, args.outlier_topic)
    refined = write_refined_backlog(run_dir, assignments)
    create_map(run_dir, assignments)
    write_outputs(run_dir, assignments, summary, metrics, refined)
    append_report(run_dir, summary, metrics, refined)
    metadata = {
        "run_dir": str(run_dir),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "assignments": list(assignments.shape),
        "summary": list(summary.shape),
        "refined_backlog": list(refined.shape) if refined is not None else None,
    }
    (run_dir / "outlier_split_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


def parse_args() -> argparse.Namespace:
    """Define and parse the Stage 4 CLI.

    Returns:
        ``argparse.Namespace`` with attributes ``run_dir``, ``outputs_dir``,
        ``outlier_topic``, ``n_subtopics``.

    Teaching:
        Three argparse patterns worth memorising:

        * **Optional positional arg.** ``nargs="?"`` makes ``run_dir`` a
          *positional* argument that you may omit. When omitted, ``args.run_dir``
          is ``None`` and the orchestrator falls back to ``latest_run``.
        * **Convention: hyphenated flag, underscore attribute.** ``--n-subtopics``
          on the command line becomes ``args.n_subtopics`` in code. argparse
          converts dashes to underscores automatically.
        * **Typed defaults.** ``type=int, default=-1`` for ``--outlier-topic``
          parses the string the user types into an ``int`` and supplies a
          sensible default; ``default=None`` for ``--n-subtopics`` lets us
          distinguish "not provided" from "any number".
    """
    parser = argparse.ArgumentParser(description="Split BERTopic -1 outlier bucket into finer semantic subtopics.")
    parser.add_argument("run_dir", nargs="?", help="Path to outputs/option2_<timestamp>; defaults to latest run")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--outlier-topic", type=int, default=-1)
    parser.add_argument("--n-subtopics", type=int, default=None, help="Force this many subtopics; default auto")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
