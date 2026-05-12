# 05 — Cosine similarity and centroids

## The problem

You now have an embedding matrix (Lesson 03) and a clustering
algorithm somewhere downstream produces a vector of integer cluster
labels. The labels alone are useless to a product manager. They
need to know:

- What is each cluster **about**?
- Which tickets are the most **representative** of that cluster?
- Which tickets are on the **edge**, possibly belonging to a
  neighbouring cluster?

The first question is answered by TF-IDF labelling (Lessons 01-02).
The second and third are answered by the geometry of the embedding
space itself. Specifically: every cluster has a **centroid** — the
mean of its members' embedding vectors — and every ticket has a
**similarity** to that centroid. High similarity = prototypical
member. Low similarity = edge case.

This lesson reads the centroid + similarity computation out of
[`summarize`](../../scripts/build_user_wants_taxonomy.py) line by
line, explains why `normalize_embeddings=True` (Lesson 03) makes the
math cheap, and shows how the resulting `centroid_similarity` column
in `user_wants_assignments.csv` drives the "three example tickets per
cluster" output that ends up in the workbook.

## Dot product as similarity

Recall from Lesson 03:

```
cosine(u, v) = dot(u, v) / (‖u‖ * ‖v‖)
```

If both `u` and `v` are unit vectors (length exactly 1), the
denominator is 1, and cosine similarity collapses to a plain dot
product:

```
cosine(u, v) == dot(u, v)        when ‖u‖ = ‖v‖ = 1
```

Computing a dot product is one `numpy` operation: `np.dot(u, v)`. For
a whole matrix of similarities, it is `embeddings @ embeddings.T` —
one matrix multiplication, vectorised across every pair, optimised by
BLAS on whatever hardware NumPy is sitting on.

Because the pipeline calls `model.encode(..., normalize_embeddings=True)`
in
[scripts/option2_pipeline.py:1220](../../scripts/option2_pipeline.py)
and
[scripts/build_user_wants_taxonomy.py:222](../../scripts/build_user_wants_taxonomy.py),
every row of `embeddings_local.npy` is unit-length. This is the
single most important consequence of the normalisation flag: it
turns the rest of the pipeline's similarity work into matrix
multiplication.

## A cluster centroid is just a mean

The centroid of a cluster is the **mean** of its members' embedding
vectors. There is no special function for this. Pandas and NumPy give
you one line.

[scripts/build_user_wants_taxonomy.py:547-552](../../scripts/build_user_wants_taxonomy.py):

```python
centroids: dict[int, np.ndarray] = {}
for cluster_id in sorted(set(labels)):
    if cluster_id == -1:
        continue
    mask = labels == cluster_id
    centroids[cluster_id] = embeddings[mask].mean(axis=0)
```

Walk through this:

1. **Loop over every distinct cluster ID.** `set(labels)` deduplicates;
   `sorted(...)` gives a stable iteration order so that two runs on
   the same data produce the same dict.
2. **Skip `-1`.** HDBSCAN labels outliers with `cluster_id = -1`
   (Module 04). Outliers are not a cluster — they are the leftover
   "did not fit anywhere" set. Computing a centroid over them would
   produce a meaningless vector that points at "the average of all
   the noise", which is approximately nothing.
3. **`mask = labels == cluster_id`.** A boolean array with `True` at
   every index belonging to this cluster. Length = number of
   embeddings.
4. **`embeddings[mask]`.** Slice the (n, 384) embedding matrix down
   to (k, 384) where k is the cluster size. NumPy's boolean
   indexing.
5. **`.mean(axis=0)`.** Take the mean **along axis 0** — i.e. average
   each of the 384 dimensions across all k rows. Output shape: (384,).

That is the centroid. One line of NumPy, no special library.

A subtle point: the centroid is **not itself a unit vector**. The
average of unit vectors has a length less than 1 (unless the inputs
were all identical). For our purposes this does not matter, because
the next step divides by both norms anyway. But you should know it,
because if you ever wanted to compare centroids to each other (e.g.
"how similar is cluster 5 to cluster 12?"), you would need to
re-normalise first.

## Per-row similarity to the assigned centroid

Once the centroids exist, the pipeline computes one cosine similarity
per ticket: how close is this ticket's embedding to the centroid of
the cluster it was assigned to?

[scripts/build_user_wants_taxonomy.py:554-562](../../scripts/build_user_wants_taxonomy.py):

```python
similarities = np.zeros(len(df), dtype=np.float32)
for i, lbl in enumerate(labels):
    if lbl == -1 or lbl not in centroids:
        similarities[i] = float("nan")
        continue
    cent = centroids[lbl]
    denom = (np.linalg.norm(embeddings[i]) * np.linalg.norm(cent)) or 1.0
    similarities[i] = float(np.dot(embeddings[i], cent) / denom)
df["centroid_similarity"] = similarities
```

Read this carefully:

1. **`similarities = np.zeros(len(df), dtype=np.float32)`** — preallocate
   an output array. NumPy's `np.zeros` is fast and explicit; growing
   a list and converting at the end would be slower.
2. **Loop over every row.** `enumerate(labels)` gives `(index,
   cluster_id)` pairs.
3. **Outlier guard.** If the row is in cluster `-1` or somehow
   missing from the centroid dict, set `NaN` and skip. NaN is the
   right "no value" marker here — it propagates through subsequent
   `mean()` calls and is easy to filter on.
4. **Compute the cosine formula by hand.** This is the textbook
   formula:

   ```
   cos(u, v) = dot(u, v) / (‖u‖ * ‖v‖)
   ```

   `np.dot(...)` is the numerator. `np.linalg.norm(...)` is the L2
   norm of a vector. The product `‖u‖ * ‖v‖` is the denominator.
5. **`or 1.0` as a safety guard.** `(a * b) or 1.0` evaluates to `a *
   b` if non-zero, otherwise to `1.0`. This protects against an
   all-zero centroid (degenerate case, e.g. an empty cluster slipping
   through). Cheap insurance.

A natural question: why **compute** the cosine when both `embeddings[i]`
and `cent` could be normalised, and `np.dot(u, v)` would suffice?

Two reasons. First, `cent` is the mean of unit vectors, and (as
noted above) is not itself unit-length. Second, the explicit formula
is **self-documenting**. Someone reading this loop a year from now
sees the cosine identity spelled out and does not need to remember
that the embeddings are normalised. The cost is two `np.linalg.norm`
calls per row — negligible at 250 rows, modest at 6,669, and you
would optimise this only if profiling pointed here.

For the larger semantic-cluster pass (6,669 rows), an equivalent
vectorised version would be:

```python
# Hypothetical vectorised form for the same computation:
cent_matrix = np.stack([centroids[l] for l in labels])     # (n, 384)
cent_norms = np.linalg.norm(cent_matrix, axis=1)           # (n,)
emb_norms = np.linalg.norm(embeddings, axis=1)             # (n,) ~= 1.0
similarities = np.einsum("ij,ij->i", embeddings, cent_matrix) / (emb_norms * cent_norms)
```

The pipeline does not actually do this, because the cluster sizes are
small enough that the loop is sub-second. Premature optimisation.

## What `centroid_similarity` looks like in practice

After this loop runs, every row in `user_wants_assignments.csv` has a
`centroid_similarity` value. Tickets near the centre of their
cluster have similarities around 0.85–0.95. Tickets on the cluster
edge (still assigned, but borderline) sit at 0.5–0.7. Tickets in the
outlier cluster have NaN.

The pipeline uses this column to pick **canonical examples** for each
cluster. [scripts/build_user_wants_taxonomy.py:573-577](../../scripts/build_user_wants_taxonomy.py):

```python
sub = df.loc[cluster_mask].sort_values("centroid_similarity", ascending=False)
examples = sub["_want_text"].head(3).tolist()
next_steps = sub["support_next_step"].dropna().head(3).tolist()
```

Sort the cluster's rows by `centroid_similarity` descending; take the
top 3 want-strings. These three end up in the `example_1`,
`example_2`, `example_3` columns of `user_wants_taxonomy.csv` — the
ones a product manager reads to understand each cluster.

This is the small move that makes the output feel **curated** rather
than random. Without sorting by `centroid_similarity`, you would
land on three arbitrary tickets — possibly all on the cluster edge,
possibly contradicting each other. With the sort, the three examples
are the three most prototypical members of the cluster. They tell a
coherent story.

You can verify by reading the taxonomy file. The
`access_account_recover_unban_regain_unblocked` cluster (29 tickets,
the largest) has these three examples in our run:

```
to have their account unblocked | recover_access | improve the clarity of ban reasons provided to users | unban the user 3023330656874904
to have their account unblocked | recover_access | improve the clarity of ban reasons provided to users | unban this user, please
to have their account unblocked | recover_access | improve the point system and its impact on account restrictions | unban the user 1116837121577217
```

All three are clear, consistent variations on the same theme. Compare
to a random sample from the same cluster, which would mix in tickets
that happen to use the words "unban" and "account" but in a different
context.

## How this generalises beyond `build_user_wants_taxonomy.py`

The same pattern shows up in three other places in the codebase, each
slightly different. Worth recognising them all as the **same idea**
applied at different stages:

1. **Cluster-labelling top terms** — the c-TF-IDF mean over members'
   TF-IDF rows
   ([scripts/option2_pipeline.py:1390-1392](../../scripts/option2_pipeline.py)).
   Same `embeddings[mask].mean(axis=0)` shape, applied to a sparse
   matrix instead of a dense one. The output is a "centroid" in
   token-space rather than embedding-space.
2. **Per-cluster top examples in the semantic clusters** —
   [scripts/option2_pipeline.py:1410](../../scripts/option2_pipeline.py)
   sorts by `(context_depth_score, cluster_probability)` instead of
   centroid similarity. The principle is the same (pick the three
   most representative members), but the ranking key is different
   because at that stage the pipeline already has HDBSCAN's own
   `cluster_probability` as a per-row "how confidently does this
   point belong" score.
3. **Repeat-user persona summaries** ([Module 02
   Lesson 04](../02-data-with-pandas/04-groupby-and-aggregations.md))
   pick the top recurring tickets by sorted `context_depth_score`,
   not by centroid similarity. Same shape, different axis.

The lesson: **whenever you have a group of items and you want to
surface the K most representative ones, you need a per-item score
that ranks within the group**. Centroid similarity is one such
score — natural for embeddings. HDBSCAN's `cluster_probability` is
another. `context_depth_score` is a third. Pick the one that
answers the question your stakeholder is actually asking.

## Try it

```python
import numpy as np
import pandas as pd

run_dir = "outputs/option2_20260502_150055"
emb = np.load(f"{run_dir}/embeddings_local.npy")
docs = pd.read_csv(f"{run_dir}/semantic_cluster_assignments.csv")
print("embeddings:", emb.shape, " assignments:", len(docs))

# Compute a centroid for cluster 9 ('channel, create, open channel...').
target_cluster = 9
mask = (docs["cluster_id"] == target_cluster).to_numpy()
print(f"cluster {target_cluster} size:", mask.sum())

centroid = emb[mask].mean(axis=0)
print("centroid shape:", centroid.shape, "  norm:", np.linalg.norm(centroid))

# Per-ticket cosine similarity to the centroid (within the cluster only).
sub_emb = emb[mask]
denoms = np.linalg.norm(sub_emb, axis=1) * np.linalg.norm(centroid)
sims = (sub_emb @ centroid) / denoms

# Find the three most prototypical and the three least prototypical members.
sub_docs = docs.loc[mask].copy().reset_index(drop=True)
sub_docs["centroid_similarity"] = sims

print("\n3 most prototypical tickets in cluster 9:")
for _, row in sub_docs.nlargest(3, "centroid_similarity").iterrows():
    print(f"  cos={row['centroid_similarity']:.3f}  {row['model_text'][:90]}")

print("\n3 cluster-edge tickets (lowest centroid similarity):")
for _, row in sub_docs.nsmallest(3, "centroid_similarity").iterrows():
    print(f"  cos={row['centroid_similarity']:.3f}  {row['model_text'][:90]}")
```

The `nlargest(3)` rows should read like the same complaint expressed
three times — "open my channel", "unban my channel", "increase
channel limit". The `nsmallest(3)` rows are the cluster's outliers:
tickets that ended up here because their nearest neighbour was in
this cluster, not because they cleanly belong. That diagnostic gap
between the two groups is what the `centroid_similarity` column
gives you.

The next lesson swings back to text-feature engineering — the
hand-written regex evidence flags that ride alongside embeddings as a
parallel representation, and the `context_depth_score` formula that
weights them.
