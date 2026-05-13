#!/usr/bin/env python3
"""Stage 6 — cluster LLM-extracted wants into a final taxonomy.

The novel layer. Stages 1-5 produce per-ticket structured fields; this stage
collapses them into a stable list of "wants" by re-embedding the joined
``actual_user_want | job_to_be_done | product_opportunity | literal_request``
strings and clustering.

Pipeline:

1. Load the extraction table named by ``llm_extraction_status.json`` when
   present, then fall back to the canonical local/Ollama aliases.
2. Build ``_want_text`` per row by joining the four want/job/opportunity fields.
3. Embed with the same multilingual sentence-transformer used in earlier stages.
4. Cluster:

   * ``--method auto`` (default) — try HDBSCAN with ``min_samples=1`` and
     ``cluster_selection_epsilon=0.15``. If outliers > 40% of points or fewer
     than 8 clusters formed, fall back to KMeans.
   * ``--method kmeans`` — force KMeans with adaptive
     ``k = max(10, min(20, n // 14))`` (override with ``--n-clusters``).
   * ``--method hdbscan`` — accept whatever HDBSCAN gives.

5. Compute centroids and per-row cosine similarity to the assigned centroid.
6. Label each cluster heuristically — top 6 distinctive lower-cased tokens
   joined by ``_``, after dropping a project-specific stopwords list.
7. Build per-cluster summary with size, share, top jobs/emotions, average
   money/trust/urgency risk, three centroid-near examples, and two
   support-next-step examples.
8. Optionally join back to ``enriched_tickets.csv`` to attach manager,
   category, date for the ``want × manager`` cross-tab.

Outputs:

* ``user_wants_taxonomy.csv``      — 17 rows for the latest run.
* ``user_wants_assignments.csv``   — 250 rows.
* ``user_wants_workbook.xlsx``     — sheets: taxonomy, assignments,
  want_x_emotion, want_x_money_risk, want_x_manager.
* ``user_wants_findings.md``       — human-readable summary.
* ``user_wants_metadata.json``.

See :doc:`docs/engineering/06-stage6-taxonomy` for fallback logic and
:doc:`docs/engineering/05-findings` for the headline finding (top wants are
about ban-removal *and* explanation, not just ban-removal).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

#: The four LLM-extracted fields we glue together to form a per-ticket
#: "what they want" string.
#:
#: Why four fields and not one? Stage 4 asked the LLM to answer the same
#: underlying question from four different angles:
#:
#: * ``actual_user_want`` — the user's deeper goal in plain language.
#: * ``job_to_be_done`` — JTBD framing ("when X happens I want Y so I can Z").
#: * ``product_opportunity`` — what the product could do better.
#: * ``literal_request`` — the surface ask, often a single verb.
#:
#: Concatenating them with ``" | "`` is a deliberate redundancy trick:
#: a sentence-transformer embedding of "lift the ban | regain access |
#: faster appeals | unban my account" lands in a much more stable region
#: of vector space than any single phrase would. The repeated semantic
#: signal averages out the noise from any one bad LLM answer, so two
#: tickets that *mean* the same thing end up close even when their
#: literal wording differs. This makes the downstream clustering
#: (HDBSCAN / KMeans) far more robust on a dataset of 6,728 real
#: support records where the LLM occasionally leaves a field blank or
#: paraphrases oddly.
WANT_TEXT_FIELDS = [
    "actual_user_want",
    "job_to_be_done",
    "product_opportunity",
    "literal_request",
]


def load_extractions(run_dir: Path) -> pd.DataFrame:
    """Load the best available LLM extraction CSV from a stage run directory.

    Earlier pipeline stages may have written several extraction CSVs — one
    per backend/model, plus stable aliases. The status JSON is the safest
    source of truth because it records the output stem from the latest
    extraction command. We prefer that exact file, then fall back to stable
    aliases and finally to newest model-specific local extraction files.

    Args:
        run_dir: Directory holding the stage outputs (e.g. ``runs/2026-05-03``).

    Returns:
        A pandas DataFrame of LLM extractions. The basename of the file
        actually used is stashed in ``df.attrs["source_file"]`` so callers
        can record provenance without re-deriving it.

    Raises:
        FileNotFoundError: None of the four candidate CSVs were present
            and non-empty in ``run_dir``.

    Teaching:
        * **Priority-ordered fallback** is a tiny but powerful pattern:
          encode your preferences as an ordered list, iterate, and stop
          at the first hit. It separates "what is preferred" from
          "what to do about it", and it makes the preference order
          reviewable in one place.
        * ``path.stat().st_size > 0`` guards against the common nuisance
          of a previous run leaving a 0-byte file behind after a crash.
          Existence alone is not enough.
        * ``df.attrs`` is a little-known pandas dict that travels with
          the DataFrame but is *not* a column. It is the right place to
          keep metadata like "which file did this come from?" — the same
          information would pollute every row if stored as a column.
    """
    candidates: list[Path] = []
    status_path = run_dir / "llm_extraction_status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            output_stem = str(status.get("output_stem") or "").strip()
            if output_stem:
                candidates.append(run_dir / f"{output_stem}.csv")
        except Exception:
            pass

    candidates.extend(
        [
            run_dir / "ollama_extractions.csv",
            run_dir / "llm_extractions.csv",
        ]
    )
    candidates.extend(
        sorted(
            (
                p
                for p in run_dir.glob("ollama_*_extractions.csv")
                if not p.name.startswith("smoke_")
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    )
    candidates.append(run_dir / "rules_extractions.csv")

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.exists() and path.stat().st_size > 0:
            df = pd.read_csv(path)
            if "_status" in df.columns:
                df = df[df["_status"].fillna("").astype(str).eq("ok")].copy()
            df.attrs["source_file"] = path.name
            return df
    raise FileNotFoundError(f"No extraction CSV found in {run_dir}")


def build_want_text(row: pd.Series) -> str:
    """Concatenate the four want-style fields for a single ticket.

    This is applied row-by-row to the extractions DataFrame to produce
    the ``_want_text`` column that downstream embedding and clustering
    consume. Joining several semantically-related fields into one string
    makes the embedding more representative — see ``WANT_TEXT_FIELDS``
    for the redundancy rationale.

    Args:
        row: One row of the extractions DataFrame, as supplied by
            ``DataFrame.apply(..., axis=1)``.

    Returns:
        A single string with cleaned, non-empty values joined by
        ``" | "``. Empty if every field is missing or junk.

    Teaching:
        * The body could be written as a list comprehension, but the
          explicit ``for`` loop is friendlier when each iteration has
          three guards (type check, non-empty check, sentinel check).
        * The ``not in {"nan", "none", "other"}`` filter matters more
          than it looks. CSVs round-trip ``NaN`` and Python ``None``
          to literal strings on save/load, and the LLM frequently
          answers ``"other"`` when it has nothing to say. Letting any
          of these into the want text would cause every ticket to
          *look* slightly similar, smearing the clusters together.
        * The set literal ``{"nan", "none", "other"}`` is cheaper and
          more readable than chained ``or`` comparisons. ``in`` on a
          set is O(1).
        * ``" | "`` (with spaces) is chosen over ``"|"`` because the
          tokenizer inside the sentence-transformer treats it as a
          word break, which is what we want — we are joining *phrases*,
          not building a primary key.
    """
    parts = []
    for field in WANT_TEXT_FIELDS:
        val = row.get(field)
        if isinstance(val, str) and val.strip() and val.strip().lower() not in {"nan", "none", "other"}:
            parts.append(val.strip())
    return " | ".join(parts)


def embed_texts(texts: list[str]) -> np.ndarray:
    """Turn a list of want-strings into a dense float32 embedding matrix.

    We use ``paraphrase-multilingual-MiniLM-L12-v2`` because the support
    tickets in this dataset arrive in several languages and the model
    is small enough to embed all 6,728 rows on a laptop in seconds.
    The same model is used in earlier stages, which keeps every
    embedding-based step in the pipeline directly comparable.

    Args:
        texts: A list of strings, one per ticket.

    Returns:
        A ``(len(texts), 384)`` ``np.float32`` array. Each row is a
        unit-length vector — the L2 norm is exactly 1.

    Teaching:
        * The import is **inside** the function on purpose. The
          ``sentence-transformers`` package pulls in PyTorch on import,
          which is heavy. Local imports keep the script quick to load
          when only ``--help`` is requested or when other functions are
          imported as a library.
        * ``normalize_embeddings=True`` divides every output vector by
          its L2 norm. The geometric consequence is the small but
          important identity::

              cosine(u, v) == dot(u, v)            (when ‖u‖ = ‖v‖ = 1)

          So later code can use cheap matrix multiplications anywhere
          a cosine similarity is wanted, and Euclidean distance becomes
          a monotonic function of cosine distance. HDBSCAN with
          ``metric="euclidean"`` and KMeans (which is Euclidean by
          construction) therefore both behave like cosine clusterers
          for free.
        * ``np.asarray(..., dtype=np.float32)`` halves memory vs.
          float64 and is the precision the model was trained at —
          there is no information to gain by upcasting.
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    embeddings = model.encode(
        texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True
    )
    return np.asarray(embeddings, dtype=np.float32)


def cluster_wants(
    embeddings: np.ndarray,
    min_cluster_size: int = 5,
    method: str = "auto",
    n_clusters: int | None = None,
) -> np.ndarray:
    """Cluster the LLM-extracted want embeddings into discrete labels.

    This is the heart of Stage 6. Everything before it produces vectors;
    everything after it produces summaries — this function is where the
    qualitative "what do users want?" question becomes a finite set of
    integer cluster IDs.

    HDBSCAN is the primary choice. If it leaves >40% of points as outliers or
    finds fewer than 8 clusters, the function falls back to KMeans (``auto``
    mode). With this dataset's roughly 250 non-empty want strings, that
    fallback is common.

    Args:
        embeddings: Normalized embedding matrix ``(n_docs, dim)``.
        min_cluster_size: HDBSCAN ``min_cluster_size`` parameter — the
            smallest group that may be called a real cluster.
        method: ``auto`` (HDBSCAN with KMeans fallback), ``hdbscan`` (force),
            ``kmeans`` (force).
        n_clusters: KMeans ``k`` override. If None, uses
            ``max(10, min(20, n // 14))``.

    Returns:
        ``labels`` array of length ``n_docs``. ``-1`` indicates outliers
        (only possible when HDBSCAN is used).

    Teaching:
        **HDBSCAN parameters, in plain English.**

        * ``min_cluster_size=5`` — "I refuse to call anything smaller
          than 5 points a cluster." With ~250 rows this means at most
          50 clusters can ever exist; in practice we get far fewer.
        * ``min_samples=1`` — controls how aggressive HDBSCAN is at
          declaring a point an outlier. Higher = stricter = more
          ``-1`` labels. We set it to 1 because our data is small and
          we would rather assign a borderline point to its nearest
          cluster than throw it away.
        * ``cluster_selection_method="eom"`` — "Excess of Mass". The
          algorithm builds a tree of nested clusters and EOM picks the
          flat partition that captures the most "stable" mass. The
          alternative, ``"leaf"``, returns the deepest splits and tends
          to over-fragment. EOM gives the macro-level taxonomy we want.
        * ``cluster_selection_epsilon=0.15`` — a merge threshold in
          embedding distance. Two micro-clusters that are this close
          get merged. We tuned 0.15 to avoid splitting near-synonyms
          like "lift the ban" vs. "remove the block".

        **Why HDBSCAN first?** Unlike KMeans, HDBSCAN is allowed to
        say "I don't know" by labelling a point ``-1``. That is honest
        on noisy data — but on a dataset of only ~250 well-extracted
        wants, density estimates are unreliable and HDBSCAN tends to
        either declare half the points outliers or collapse everything
        into 2–3 mega-clusters. So we apply two sanity checks and bail
        out to KMeans when either fails.

        **The auto-fallback heuristic** is intentionally crude::

            outliers > 40% of points  OR  clusters < 8  →  switch to KMeans

        Forty percent is a "this is unusable" line; eight is the
        minimum number of distinct "wants" that makes the resulting
        spreadsheet interesting to a product manager.

        **KMeans choices.**

        * ``n_init="auto"`` — sklearn picks ``n_init=10`` for the
          standard Lloyd algorithm. Each restart picks different
          random seeds for the initial centroids and the final
          partition is the lowest-inertia of the bunch. This matters
          because KMeans is non-convex and can get stuck.
        * ``random_state=42`` — without this, two runs on the same
          data produce different (but equally valid) cluster IDs,
          which would make the taxonomy CSV churn on every commit.
          A fixed seed buys reproducibility at zero modelling cost.
        * Adaptive ``k = max(10, min(20, n // 14))`` — this clamps
          the number of clusters to a sensible band for our dataset:
          never fewer than 10 (otherwise the taxonomy is too coarse
          to be actionable), never more than 20 (otherwise the
          spreadsheet stops fitting on a screen), and inside that
          band one cluster per ~14 tickets. With ``n ≈ 250`` this
          settles on ``k = 17``.
    """
    if method == "kmeans":
        from sklearn.cluster import KMeans

        n = n_clusters or max(8, min(24, len(embeddings) // 12))
        return KMeans(n_clusters=n, n_init="auto", random_state=42).fit_predict(embeddings)
    try:
        import hdbscan

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=1,
            metric="euclidean",
            cluster_selection_method="eom",
            cluster_selection_epsilon=0.15,
        )
        labels = clusterer.fit_predict(embeddings.astype(np.float64))
        n_outlier = int((labels == -1).sum())
        n_clust = len({int(l) for l in labels if l != -1})
        if method == "auto" and (n_outlier > 0.4 * len(embeddings) or n_clust < 8):
            print(
                f"[info] HDBSCAN gave {n_clust} clusters / {n_outlier} outliers; "
                f"falling back to KMeans for denser taxonomy",
                file=sys.stderr,
            )
            from sklearn.cluster import KMeans

            n = n_clusters or max(10, min(20, len(embeddings) // 14))
            return KMeans(n_clusters=n, n_init="auto", random_state=42).fit_predict(embeddings)
        return labels
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] HDBSCAN failed ({exc}); falling back to KMeans", file=sys.stderr)
        from sklearn.cluster import KMeans

        n = n_clusters or max(8, min(20, len(embeddings) // 12))
        return KMeans(n_clusters=n, n_init="auto", random_state=42).fit_predict(embeddings)


#: Project-specific stopword list used by :func:`label_cluster`.
#:
#: This is **not** a generic NLTK-style English stopword list — it is a
#: hand-curated set of words that, on this specific support-ticket corpus,
#: would otherwise dominate every cluster label and make them all look
#: identical. It has three layers:
#:
#: 1. **Generic English filler** (``the``, ``and``, ``with``, ``would`` …):
#:    high-frequency function words with no topical content.
#: 2. **Domain filler** (``user``, ``ticket``, ``support``, ``system``,
#:    ``feature``, ``process``, ``provide``, ``improve`` …): words that
#:    appear in *every* support ticket and therefore carry zero
#:    discriminative signal. If we kept them, every cluster's label
#:    would start with ``user_ticket_support_…``.
#: 3. **Headline-topic filler** (``ban``, ``bans``, ``banned``, ``block``,
#:    ``blocked``, ``blocking``): the dataset is so dominated by
#:    ban-related complaints that "ban" appears in nearly every cluster.
#:    Keeping it would label *every* cluster ``ban_…`` and obscure the
#:    actual differences (appeal vs. explanation vs. compensation).
#:
#: The lesson: stopword lists are corpus-specific. Always look at your
#: top tokens before clustering and remove the ones that say "this is
#: a customer-support ticket" rather than "this is *what kind* of
#: customer-support ticket".
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "had", "you", "your", "but", "not", "can", "could", "should",
    "would", "they", "them", "their", "there", "any", "all", "into", "out",
    "user", "users", "ticket", "tickets", "support", "system", "issue", "issues",
    "feature", "process", "provide", "improve", "implement", "create", "ensure",
    "clear", "clarity", "options", "available", "make", "more", "better",
    "ban", "bans", "banned", "block", "blocked", "blocking",
}


def label_cluster(texts: list[str], top_n: int = 6) -> str:
    """Auto-generate a human-readable label for a cluster from its texts.

    Used by :func:`summarize` to give each integer cluster ID a name a
    product manager can recognise — e.g. ``appeal_explanation_account_violation``
    rather than just ``cluster_3``. The label is the top-N most frequent
    distinctive tokens across all want-strings in the cluster, joined by
    underscores. Distinctive here means "not in :data:`STOPWORDS` and
    long enough to carry meaning".

    Args:
        texts: All ``_want_text`` strings belonging to one cluster.
        top_n: How many tokens to keep in the label. Six is a compromise
            between informative and unwieldy.

    Returns:
        An underscore-joined string, or the literal ``"misc"`` if every
        token was filtered out.

    Teaching:
        * ``Counter`` from :mod:`collections` is the canonical Pythonic
          frequency table. ``Counter()[k] += 1`` is O(1) on average and
          ``Counter.most_common(n)`` returns ``(token, count)`` pairs
          sorted by count descending — much cleaner than building a
          dict and sorting it by hand.
        * The regex ``r"[A-Za-z][A-Za-z\\-']{2,}"`` is a small lesson in
          character classes:

          - ``[A-Za-z]`` — one ASCII letter (so the token must start with
            a letter, not a digit or a hyphen).
          - ``[A-Za-z\\-']{2,}`` — two or more letters, hyphens, or
            apostrophes. The ``\\-`` is escaped just for readability;
            inside a class a leading or trailing ``-`` is literal anyway.
          - Net effect: words like ``can't``, ``self-serve``, ``user-id``
            survive intact, while pure numbers, emoji, and ``"_"`` do not.

        * The ``len(token) <= 3`` guard catches three-letter words that
          slipped past the explicit STOPWORDS list (``why``, ``how``,
          ``get``, …). It is a cheap second filter.
        * ``"_".join(top) if top else "misc"`` is the standard "fallback
          when the list is empty" idiom — better than ``try/except`` on
          an index error.
    """
    tokens: Counter[str] = Counter()
    for text in texts:
        for token in re.findall(r"[A-Za-z][A-Za-z\-']{2,}", text.lower()):
            if token in STOPWORDS or len(token) <= 3:
                continue
            tokens[token] += 1
    top = [tok for tok, _ in tokens.most_common(top_n)]
    return "_".join(top) if top else "misc"


def safe_str(v) -> str:
    """Convert any pandas / Python value into a stripped string.

    Pandas mixes three "missing" representations in the same column:
    Python ``None``, NumPy ``float('nan')``, and the empty string. This
    helper collapses all of them to ``""`` and otherwise returns the
    stripped string form. It is the small defensive step that keeps
    every other formatting site in the script clean.

    Args:
        v: Anything — including ``None``, ``np.nan``, an int, a string,
            or a ``pd.Timestamp``.

    Returns:
        ``""`` for missing values; the trimmed ``str(v)`` otherwise.

    Teaching:
        * ``np.isnan`` raises ``TypeError`` on non-numeric input, which
          is why we *first* check ``isinstance(v, float)``. The order of
          short-circuited conditions matters.
        * ``v is None`` uses identity, not equality. ``None`` is a
          singleton, so ``is`` is both faster and the idiomatic check.
        * Defensive conversion functions like this are a textbook
          example of "make every other call site assume the easy case".
          A few lines here saves dozens of ``if pd.isna(...)`` guards
          elsewhere.
    """
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return str(v).strip()


def summarize(
    df: pd.DataFrame,
    labels: np.ndarray,
    embeddings: np.ndarray,
    enriched: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the taxonomy and assignments DataFrames from cluster labels.

    This is the longest function in the script and the one that turns
    a vector of integer labels into the two artefacts product managers
    actually read: a one-row-per-want **taxonomy** and a one-row-per-
    ticket **assignments** table. Conceptually it does five things:

    1. Compute a centroid for every cluster (mean of its embeddings).
    2. Score each ticket by cosine similarity to its assigned centroid
       — i.e. "how representative is this ticket of its cluster?".
    3. Aggregate per-cluster statistics: size, share, top JTBD codes,
       top emotions, average money / trust / urgency risk, share of
       high-risk tickets.
    4. Pick the three centroid-nearest examples and two next-step hints
       per cluster.
    5. Optionally left-join the per-ticket assignments to
       ``enriched_tickets.csv`` so cross-tabs can break wants down by
       Manager / Category / Date.

    Args:
        df: The extractions DataFrame, including the ``_want_text`` column.
        labels: Cluster labels from :func:`cluster_wants`.
        embeddings: The same matrix passed to :func:`cluster_wants`.
        enriched: Optional ``enriched_tickets.csv`` for joining managerial
            metadata. ``None`` is fine — the merge is skipped.

    Returns:
        ``(taxonomy, assignments)`` — two DataFrames sorted from largest
        cluster to smallest.

    Teaching:
        * **Centroid = mean of cluster's embeddings.** Because the
          embeddings are L2-normalised (see :func:`embed_texts`), the
          mean is *not* itself unit-length, but its direction is the
          best single representative of the cluster. Cosine similarity
          to that direction is what we use to rank "how typical" each
          ticket is.
        * **Cosine similarity** is computed by hand here rather than
          relying on a sklearn helper, partly to make the formula
          explicit and partly to avoid a dependency::

              cos(u, v) = dot(u, v) / (‖u‖ * ‖v‖)

          The ``or 1.0`` on the denominator is a defensive guard
          against an all-zero centroid (would only happen with empty
          clusters, but cheap insurance).
        * **Per-cluster aggregation** uses ``Counter`` again to find
          top jobs and top emotions, then formats them inline as
          ``"label:count, label:count, ..."``. This packs three facts
          into one CSV cell — useful when a stakeholder is scrolling
          a spreadsheet and wants the gist without opening a pivot.
        * **Examples sorted by ``centroid_similarity`` descending** —
          this is the small move that makes the output feel curated
          rather than random. The closest-to-centroid ticket is the
          most prototypical "what users want" sentence we have for
          that cluster.
        * **Conditional aggregation** (``if len(cluster_money) else
          None``) is the right way to surface "no data" rather than
          letting NumPy emit a ``RuntimeWarning: mean of empty slice``
          and a NaN.
        * **Optional left-join** with ``enriched_tickets.csv`` is what
          lets the workbook produce a ``want × manager`` cross-tab.
          We rename ``row_id`` → ``source_row`` on the right side to
          match the join key, and use ``how="left"`` so tickets without
          enriched metadata still appear in the output.
    """
    df = df.copy()
    df["want_id"] = labels

    centroids: dict[int, np.ndarray] = {}
    for cluster_id in sorted(set(labels)):
        if cluster_id == -1:
            continue
        mask = labels == cluster_id
        centroids[cluster_id] = embeddings[mask].mean(axis=0)

    similarities = np.zeros(len(df), dtype=np.float32)
    for i, lbl in enumerate(labels):
        if lbl == -1 or lbl not in centroids:
            similarities[i] = float("nan")
            continue
        cent = centroids[lbl]
        denom = (np.linalg.norm(embeddings[i]) * np.linalg.norm(cent)) or 1.0
        similarities[i] = float(np.dot(embeddings[i], cent) / denom)
    df["centroid_similarity"] = similarities

    rows = []
    for cluster_id in sorted(set(labels)):
        cluster_mask = labels == cluster_id
        cluster_texts = df.loc[cluster_mask, "_want_text"].tolist()
        cluster_jobs = df.loc[cluster_mask, "job_to_be_done"].dropna().tolist()
        cluster_emo = df.loc[cluster_mask, "user_emotion"].dropna().tolist()
        cluster_money = df.loc[cluster_mask, "money_risk_level"].dropna()
        cluster_trust = df.loc[cluster_mask, "trust_risk_level"].dropna()
        cluster_urgency = df.loc[cluster_mask, "urgency_level"].dropna()
        label = "outlier_misc" if cluster_id == -1 else label_cluster(cluster_texts)

        sub = df.loc[cluster_mask].sort_values("centroid_similarity", ascending=False)
        examples = sub["_want_text"].head(3).tolist()
        next_steps = sub["support_next_step"].dropna().head(3).tolist()

        rows.append(
            {
                "want_id": int(cluster_id),
                "want_label": label,
                "size": int(cluster_mask.sum()),
                "share": float(cluster_mask.sum()) / max(1, len(df)),
                "top_jobs": ", ".join(
                    f"{j}:{c}" for j, c in Counter(cluster_jobs).most_common(3)
                ),
                "top_emotions": ", ".join(
                    f"{e}:{c}" for e, c in Counter(cluster_emo).most_common(3)
                ),
                "avg_money_risk": round(float(cluster_money.astype(float).mean()), 2)
                if len(cluster_money)
                else None,
                "avg_trust_risk": round(float(cluster_trust.astype(float).mean()), 2)
                if len(cluster_trust)
                else None,
                "avg_urgency": round(float(cluster_urgency.astype(float).mean()), 2)
                if len(cluster_urgency)
                else None,
                "high_money_risk_share": float(
                    (cluster_money.astype(float) >= 4).mean()
                )
                if len(cluster_money)
                else None,
                "high_trust_risk_share": float(
                    (cluster_trust.astype(float) >= 4).mean()
                )
                if len(cluster_trust)
                else None,
                "example_1": examples[0] if len(examples) > 0 else "",
                "example_2": examples[1] if len(examples) > 1 else "",
                "example_3": examples[2] if len(examples) > 2 else "",
                "next_step_1": next_steps[0] if len(next_steps) > 0 else "",
                "next_step_2": next_steps[1] if len(next_steps) > 1 else "",
            }
        )

    taxonomy = pd.DataFrame(rows).sort_values(
        ["want_id"], key=lambda s: s.map(lambda x: (x == -1, -1 if x == -1 else -1 * x))
    )
    taxonomy = taxonomy.sort_values("size", ascending=False).reset_index(drop=True)

    label_map = dict(zip(taxonomy["want_id"], taxonomy["want_label"]))
    df["want_label"] = df["want_id"].map(label_map)

    keep_cols = [
        "source_row",
        "want_id",
        "want_label",
        "centroid_similarity",
        "_want_text",
        "job_to_be_done",
        "user_emotion",
        "urgency_level",
        "trust_risk_level",
        "money_risk_level",
        "product_opportunity",
        "support_next_step",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    assignments = df[keep_cols].copy()

    if enriched is not None and "source_row" in df.columns:
        join_cols = [
            c
            for c in [
                "row_id",
                "Manager",
                "Question",
                "Status",
                "Category",
                "Date",
            ]
            if c in enriched.columns
        ]
        if "row_id" in enriched.columns:
            assignments = assignments.merge(
                enriched[join_cols].rename(columns={"row_id": "source_row"}),
                on="source_row",
                how="left",
            )

    return taxonomy, assignments


def write_workbook(
    out_path: Path,
    taxonomy: pd.DataFrame,
    assignments: pd.DataFrame,
) -> None:
    """Write the multi-sheet Excel workbook stakeholders read.

    The workbook bundles five views into one file: the taxonomy itself,
    the per-ticket assignments, and three cross-tabs that answer the
    common follow-up questions ("which wants come from angry users?",
    "which wants are money-risky?", "which managers see which wants?").

    Args:
        out_path: Destination ``.xlsx`` path.
        taxonomy: The per-cluster summary returned by :func:`summarize`.
        assignments: The per-ticket assignment DataFrame.

    Returns:
        None. Side effect: writes ``out_path``.

    Teaching:
        * ``pd.ExcelWriter`` as a **context manager** (``with``) is
          the right pattern for multi-sheet workbooks. Each
          ``df.to_excel(writer, sheet_name=…)`` call adds a sheet to
          the same in-memory workbook; the ``with`` block flushes
          everything to disk on exit. Without the context manager
          you would have to call ``writer.save()`` manually and
          remember to close the file even on exceptions.
        * ``engine="openpyxl"`` is the modern ``.xlsx`` writer.
          (``xlsxwriter`` is faster but does not support reading
          existing files; ``openpyxl`` is the safest default.)
        * :func:`pd.crosstab` is the one-liner for a contingency
          table — it counts the co-occurrence of two categorical
          columns. ``pd.crosstab(rows, cols)`` produces a DataFrame
          with row labels = unique values of ``rows`` and column
          labels = unique values of ``cols``. Reading the output is
          like reading a heat-map: high cells are interesting.
        * The ``.fillna("(unknown)")`` on the manager column ensures
          a row appears even for tickets with no manager assigned —
          missing data becomes its own visible category rather than
          silently being dropped from the cross-tab.
        * Each sheet is guarded by an ``if column in assignments``
          check so the function still works on extraction sources
          that don't carry the optional fields.
    """
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        taxonomy.to_excel(writer, sheet_name="taxonomy", index=False)
        assignments.to_excel(writer, sheet_name="assignments", index=False)

        if "user_emotion" in assignments.columns:
            ct = pd.crosstab(
                assignments["want_label"], assignments["user_emotion"]
            )
            ct.to_excel(writer, sheet_name="want_x_emotion")
        if "money_risk_level" in assignments.columns:
            ct = pd.crosstab(
                assignments["want_label"],
                assignments["money_risk_level"].astype(str),
            )
            ct.to_excel(writer, sheet_name="want_x_money_risk")
        if "Manager" in assignments.columns:
            ct = pd.crosstab(
                assignments["want_label"], assignments["Manager"].fillna("(unknown)")
            )
            ct.to_excel(writer, sheet_name="want_x_manager")


def write_findings(
    out_path: Path,
    taxonomy: pd.DataFrame,
    extraction_source: str,
    total: int,
) -> None:
    """Render a human-readable Markdown summary of the taxonomy.

    This is the file an executive opens first. It walks the clusters
    in size-descending order and, for each, lists the JTBD codes,
    emotions, average risk levels, three example want-strings, and
    one suggested next step. The format is deliberately plain
    Markdown so it renders nicely in GitHub, in Notion, and as a
    PDF print.

    Args:
        out_path: Destination ``.md`` path.
        taxonomy: The taxonomy DataFrame from :func:`summarize`,
            already sorted by ``size`` descending.
        extraction_source: Filename of the extraction CSV used —
            recorded in the header for provenance.
        total: Total number of tickets included in the analysis.

    Returns:
        None. Side effect: writes ``out_path`` as UTF-8.

    Teaching:
        * **List-of-strings + ``"\\n".join(lines)``** is the standard
          Pythonic way to assemble a multi-line file. It avoids the
          quadratic cost of repeated ``s += line`` (each ``+=`` on a
          string allocates a new string) and reads top-to-bottom,
          paragraph by paragraph.
        * ``encoding="utf-8"`` matters even on macOS / Linux because
          the want-text contains non-ASCII characters from the
          multilingual support tickets — without it, a Windows runner
          could produce a CP1252-encoded file that breaks emoji and
          Cyrillic / Chinese characters.
        * The ``ex[:240]`` and ``next_step[:200]`` slices trim long
          examples to a readable width without truncating the rest of
          the document. String slicing past the end is safe in Python
          (no IndexError).
        * ``datetime.now(timezone.utc).isoformat(timespec='seconds')`` is the
          short, unambiguous timestamp format. ``timespec='seconds'``
          drops the microseconds that nobody reads.
    """
    lines: list[str] = []
    lines.append("# What Users Want — Taxonomy")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"Source extraction: {extraction_source}")
    lines.append(f"Tickets analyzed: {total}")
    lines.append(f"Wants discovered: {(taxonomy['want_id'] != -1).sum()}")
    if (taxonomy["want_id"] == -1).any():
        outlier = taxonomy.loc[taxonomy["want_id"] == -1, "size"].iloc[0]
        lines.append(f"Unclustered/outlier tickets: {int(outlier)}")
    lines.append("")
    lines.append("## Top User Wants")
    lines.append("")
    for _, row in taxonomy.iterrows():
        if row["want_id"] == -1:
            continue
        lines.append(
            f"### {row['want_label']}  (n={row['size']}, {row['share']*100:.1f}%)"
        )
        lines.append(
            f"- Top jobs: {row['top_jobs']}"
        )
        lines.append(
            f"- Emotions: {row['top_emotions']}"
        )
        risk_bits = []
        if row.get("avg_money_risk") is not None:
            risk_bits.append(f"money {row['avg_money_risk']}/5")
        if row.get("avg_trust_risk") is not None:
            risk_bits.append(f"trust {row['avg_trust_risk']}/5")
        if row.get("avg_urgency") is not None:
            risk_bits.append(f"urgency {row['avg_urgency']}/5")
        if risk_bits:
            lines.append("- Risk: " + ", ".join(risk_bits))
        for k in ("example_1", "example_2", "example_3"):
            ex = row.get(k)
            if isinstance(ex, str) and ex:
                lines.append(f"- e.g. {ex[:240]}")
        if row.get("next_step_1"):
            lines.append(f"- Next step: {row['next_step_1'][:200]}")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """Orchestrate the full Stage 6 pipeline end-to-end.

    Parses CLI arguments, loads the extractions, builds want-text,
    embeds, clusters, summarises, writes the four output artefacts
    (``.csv``, ``.csv``, ``.xlsx``, ``.md``) plus a metadata JSON.
    Returns a Unix-style exit code so the script can be chained from
    a shell pipeline or a Makefile.

    Returns:
        ``0`` on success, ``2`` if the run directory does not exist.

    Teaching:
        * **argparse** is the standard library answer to "I need a
          CLI". Three patterns to notice:

          - ``parser.add_argument("run_dir", type=Path)`` — positional
            argument, automatically converted to a :class:`pathlib.Path`.
          - ``choices=["auto", "hdbscan", "kmeans"]`` — argparse
            validates the value against this list and produces a
            helpful error if the user mistypes ``--method kmean``.
          - ``--n-clusters`` defaults to ``None``, which lets
            :func:`cluster_wants` distinguish "user said nothing" from
            "user said zero".

        * The ``--method auto`` default with a per-method override
          is a common CLI shape: sensible behaviour out of the box,
          but power users (or CI scripts) can pin behaviour for
          reproducibility.
        * **Why save metadata?** The ``user_wants_metadata.json``
          file is small but makes the run *self-describing*: anyone
          opening the spreadsheet later can find out which extraction
          source was used, when the run happened, and how many
          clusters / outliers were produced. Treat it as a Git-style
          commit message for the analysis.
        * **Why a non-zero exit code on missing dir?** Returning
          ``2`` rather than printing and continuing means a CI
          pipeline that runs ``python build_user_wants_taxonomy.py
          runs/today`` will halt loudly if today's run directory was
          never created — far better than silently producing an
          empty workbook.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--min-cluster-size", type=int, default=5)
    parser.add_argument(
        "--method",
        choices=["auto", "hdbscan", "kmeans"],
        default="auto",
        help="auto = HDBSCAN, fall back to KMeans if too sparse",
    )
    parser.add_argument("--n-clusters", type=int, default=None)
    args = parser.parse_args()

    run_dir: Path = args.run_dir
    if not run_dir.exists():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 2

    extractions = load_extractions(run_dir)
    source_file = extractions.attrs.get("source_file", "extractions.csv")
    print(f"loaded {len(extractions)} extractions from {source_file}")

    extractions["_want_text"] = extractions.apply(build_want_text, axis=1)
    extractions = extractions[extractions["_want_text"].str.len() > 0].reset_index(drop=True)
    print(f"non-empty want_text rows: {len(extractions)}")

    embeddings = embed_texts(extractions["_want_text"].tolist())
    print(f"embeddings: {embeddings.shape}")

    labels = cluster_wants(
        embeddings,
        min_cluster_size=args.min_cluster_size,
        method=args.method,
        n_clusters=args.n_clusters,
    )
    n_clusters = len({int(l) for l in labels if l != -1})
    n_outlier = int((labels == -1).sum())
    print(f"clusters: {n_clusters}; outliers: {n_outlier}")

    enriched_path = run_dir / "enriched_tickets.csv"
    enriched = pd.read_csv(enriched_path) if enriched_path.exists() else None

    taxonomy, assignments = summarize(extractions, labels, embeddings, enriched)
    taxonomy_path = run_dir / "user_wants_taxonomy.csv"
    assignments_path = run_dir / "user_wants_assignments.csv"
    workbook_path = run_dir / "user_wants_workbook.xlsx"
    findings_path = run_dir / "user_wants_findings.md"

    taxonomy.to_csv(taxonomy_path, index=False)
    assignments.to_csv(assignments_path, index=False)
    write_workbook(workbook_path, taxonomy, assignments)
    write_findings(findings_path, taxonomy, source_file, len(extractions))

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_file": source_file,
        "rows": int(len(extractions)),
        "clusters": int(n_clusters),
        "outliers": int(n_outlier),
        "min_cluster_size": int(args.min_cluster_size),
    }
    (run_dir / "user_wants_metadata.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )

    print("wrote:")
    for p in [taxonomy_path, assignments_path, workbook_path, findings_path]:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
