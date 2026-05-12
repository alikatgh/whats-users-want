# 06 — Cluster Quality and Centroids

## The problem

You have clusters. HDBSCAN gave you 21 in Stage 1 and 53 in Stage 2.
KMeans gave you 26 sub-themes inside the noise bucket. They are
labelled with c-TF-IDF or with mean-TF-IDF. They are written to CSV.
The dashboard renders them.

Two questions remain. First, are these clusters any good? "Good"
clustering means tight membership and clear separation: tickets inside
a cluster are similar, tickets across clusters are different.
"Bad" clustering means everything is mushy and the labels are arbitrary.
You need a number — a single scalar — that tells you which one you
have.

Second, even within a good cluster, some tickets are more representative
than others. The diamond-purchases cluster has 481 tickets; you cannot
read all of them. You need to surface the three or four that best
embody the cluster, the ones a product manager would quote in a
roadmap. That is a different problem from cluster quality but it
shares the math: distance to the cluster centre.

This lesson is about both. Silhouette score for cluster quality.
Centroid computation and per-row centroid similarity for finding
representative examples. They are connected by the same intuition:
distance to the cluster centre is the load-bearing quantity.

## Centroids: the cluster's centre of gravity

A centroid is the mean of the embeddings in a cluster. For cluster `c`
with member rows `M_c`, the centroid is `mean(embeddings[M_c])` along
each dimension. For 384-dim embeddings and a cluster of 481 tickets,
that is 481 vectors of 384 floats averaged element-wise into one
vector of 384 floats.

The pipeline computes centroids in
[scripts/build_user_wants_taxonomy.py:547-552](../../scripts/build_user_wants_taxonomy.py):

```python
centroids: dict[int, np.ndarray] = {}
for cluster_id in sorted(set(labels)):
    if cluster_id == -1:
        continue
    mask = labels == cluster_id
    centroids[cluster_id] = embeddings[mask].mean(axis=0)
```

Three things to read. `sorted(set(labels))` is the unique cluster IDs
in ascending order. The `if cluster_id == -1: continue` skips the
noise bucket — there is no meaningful "centre" of noise.
`embeddings[mask]` is fancy boolean indexing: NumPy filters the
embeddings array down to the rows where `mask` is True, then
`.mean(axis=0)` averages along the first axis (the rows), leaving a
single vector of dimension equal to the embedding dimension.

The result is one centroid per non-noise cluster, stored in a dict
keyed by cluster ID. For the user-wants taxonomy with 17 clusters and
no outliers, that is 17 entries, each a 384-dim float32 vector.

## Why mean-of-normalised-embeddings is not unit length

The teaching note at
[scripts/build_user_wants_taxonomy.py:509-514](../../scripts/build_user_wants_taxonomy.py)
flags a subtlety:

```python
# * **Centroid = mean of cluster's embeddings.** Because the
#   embeddings are L2-normalised (see :func:`embed_texts`), the
#   mean is *not* itself unit-length, but its direction is the
#   best single representative of the cluster. Cosine similarity
#   to that direction is what we use to rank "how typical" each
#   ticket is.
```

Pause here. The original embeddings are unit length —
`||emb_i|| = 1` for all `i`. But the average of unit vectors is not
unit length unless they all point in the same direction. Two unit
vectors that point in opposite directions average to the zero vector;
two that point in the same direction average to a unit vector.

For a cluster where all embeddings are tightly clustered (small
angle), the centroid is close to unit length. For a cluster that is
spread out, the centroid is shorter — its norm is less than 1.

This is fine. The centroid's direction is what we care about. We are
about to compute cosine similarity, which only looks at angle, not
magnitude. We are not pretending the centroid is itself a sentence
embedding.

## Per-row centroid similarity

For each ticket, we want a number telling us how representative it is
of its assigned cluster. The standard answer is cosine similarity
between the ticket's embedding and the cluster's centroid. From
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

The formula is the textbook cosine: `dot(u, v) / (||u|| * ||v||)`.

Three small implementation choices worth noticing. The `or 1.0` on the
denominator is defensive — if the centroid happens to be the zero
vector (which would only happen with an empty cluster, but nothing's
free) we divide by 1 instead of crashing. Tickets in the noise
bucket get `NaN` rather than 0, which lets pandas drop or filter them
explicitly downstream rather than confusing them with low-similarity
real tickets. And the loop is in pure Python, which on 250 wants is
fast enough — with 6,669 rows you would vectorise it as a single
matrix multiplication, but for the user-wants stage the loop is
clearer.

The output `centroid_similarity` ends up in
[outputs/option2_20260502_150055/user_wants_assignments.csv](../../outputs/option2_20260502_150055/user_wants_assignments.csv).
A row with `centroid_similarity=0.91` is a ticket whose extracted
"want" is right at the centre of its cluster — the canonical example.
A row with `centroid_similarity=0.32` is on the edge, possibly close
to a different cluster.

## Picking representative examples

With per-row centroid similarity in hand, picking the most
representative tickets is a one-liner. From
[scripts/build_user_wants_taxonomy.py:573-577](../../scripts/build_user_wants_taxonomy.py):

```python
label = "outlier_misc" if cluster_id == -1 else label_cluster(cluster_texts)

sub = df.loc[cluster_mask].sort_values("centroid_similarity", ascending=False)
examples = sub["_want_text"].head(3).tolist()
next_steps = sub["support_next_step"].dropna().head(3).tolist()
```

`sort_values("centroid_similarity", ascending=False)` orders the
cluster's tickets from most representative to least. `.head(3)` takes
the top three, which become `example_1`, `example_2`, `example_3` in
the taxonomy CSV.

The teaching note at
[scripts/build_user_wants_taxonomy.py:529-533](../../scripts/build_user_wants_taxonomy.py)
makes the case:

```python
# * **Examples sorted by ``centroid_similarity`` descending** —
#   this is the small move that makes the output feel curated
#   rather than random. The closest-to-centroid ticket is the
#   most prototypical "what users want" sentence we have for
#   that cluster.
```

A previous version of this code took the first three tickets in
arbitrary order. The output looked random — sometimes the example was
a clear case, sometimes a borderline one. Sorting by centroid
similarity made the taxonomy feel curated. Same data, completely
different perception.

The same pattern surfaces in `split_outlier_bucket.py` for the noise
sub-themes, but with confidence instead of centroid similarity (KMeans
does not give us per-row centroid similarity directly, so we compute
the distance-ratio confidence we saw in
[04-kmeans-fallback.md](04-kmeans-fallback.md)).

## Silhouette score: cluster quality in one number

Silhouette is the most common single-number cluster-quality metric. It
asks, for each point: how much closer is it to its own cluster than to
the next-nearest cluster? Formally, for a single point:

`s(i) = (b(i) - a(i)) / max(a(i), b(i))`

where `a(i)` is the average distance from point `i` to other points in
its own cluster, and `b(i)` is the average distance from `i` to points
in the *next-nearest* cluster (the cluster that minimises this
distance, excluding the point's own cluster).

The number is in `[-1, 1]`. `+1` is a tight, well-separated cluster.
`0` is a point on the boundary between two clusters. `-1` is a point
that is closer on average to a different cluster than to its own —
i.e. likely misassigned.

The mean silhouette across all points is the dataset-level score.

The teaching note in `split_outlier_bucket.py` at
[scripts/split_outlier_bucket.py:407-413](../../scripts/split_outlier_bucket.py)
states the formula directly:

```python
# **5. Quality check (silhouette).** The silhouette score for one row is
# ``(b - a) / max(a, b)`` where ``a`` is its mean distance to its own
# cluster and ``b`` is its mean distance to the *nearest other* cluster.
# It is +1 for a tight, well-separated cluster, 0 for ambiguous, -1 for
# misassigned. Computing it on all 1,381 rows is O(n^2); we sample 1,200
# with NumPy's ``default_rng`` for a quick proxy. We use ``metric=
# "cosine"`` because embeddings live on the unit hypersphere.
```

Two key practical points are tucked in there. First, the score is
expensive — `O(n²)` because every point compares its distance to every
other point in every cluster. Second, the answer is stable enough that
sampling is fine. We sample.

## Why we sample for silhouette

Computing silhouette exactly on `n` points is `O(n²)` because of the
pairwise distances. On 1,331 points that is about 1.7M pairs — easy.
On 6,669 points it is 44M pairs — still doable, but slow. On a hundred
thousand points it is impractical.

The code at
[scripts/split_outlier_bucket.py:481-489](../../scripts/split_outlier_bucket.py)
samples:

```python
metrics = []
try:
    sample_n = min(1200, len(X))
    rng = np.random.default_rng(42)
    sample = rng.choice(len(X), sample_n, replace=False)
    sil = silhouette_score(X[sample], labels[sample], metric="cosine")
    metrics.append({"metric": "silhouette_cosine_sample", "value": round(float(sil), 4)})
except Exception as exc:
    metrics.append({"metric": "silhouette_cosine_sample_error", "value": str(exc)})
```

`rng.choice(len(X), 1200, replace=False)` picks 1,200 unique row
indices. We compute silhouette only on those 1,200 rows and treat the
result as a proxy for the full-dataset score. With `random_state=42`
behind `default_rng`, the sample is reproducible across runs.

`metric="cosine"` is mandatory here. The embeddings live on the unit
sphere, so Euclidean distance is monotonic in cosine distance and you
might think it does not matter. But silhouette inside KMeans
specifically uses pairwise distances on the *normalised* output of
`split_outliers`, where the relationship between Euclidean and cosine
is exact. Telling sklearn `metric="cosine"` makes the formula match
the geometry.

The result for our run, written to
[outputs/option2_20260502_150055/outlier_split_metrics.csv](../../outputs/option2_20260502_150055/outlier_split_metrics.csv):

```
metric,value
silhouette_cosine_sample,0.124
outlier_topic,-1.0
outlier_docs,1331.0
subtopics,26.0
```

Silhouette of 0.124. That is not great, and we should be honest
about why.

## What 0.124 silhouette tells us

A silhouette score of 0.124 is positive but mushy. Above 0.5 you have
clearly-separated, dense clusters. Between 0.25 and 0.5 you have
recognisable structure. Between 0 and 0.25 — where we are — you have
clusters that are barely better than random with respect to that
metric.

This is exactly what we should expect, and it is not a bug. The 1,331
docs we are clustering with KMeans are tickets HDBSCAN already
declined to cluster. They are noise *by definition*. KMeans is being
asked to split a heterogeneous bag of leftovers, and it produces 26
sub-themes with weak internal cohesion because that is what is in the
data.

The silhouette score makes that explicit. A reviewer reading the
metrics file sees `0.124` and knows: the sub-themes are useful for
triage, but they are softer than the main-corpus clusters. Filter the
dashboard by `outlier_subtopic_confidence` and read the high-confidence
rows; treat the low-confidence ones as candidates for further
investigation.

The pipeline does not abandon the bad-silhouette output. It surfaces
the metric, surfaces the per-row confidence, and lets the dashboard
filter on it. That is the honest workflow.

## When to trust silhouette and when not to

Silhouette is the best single number we have, but it is not perfect.
Three caveats.

It penalises non-spherical clusters. KMeans assumes spherical, equal-
variance clusters; silhouette implicitly does too. A long, thin cluster
will get a worse silhouette than a compact, round cluster of the same
quality, because some of its members are far from the centroid even
though they belong.

It penalises overlap, even useful overlap. In real text data, clusters
overlap at the boundaries — a ticket about "diamond purchase that
failed because of a ban" sits between the diamonds cluster and the ban
cluster. Silhouette punishes those points. They are not misassigned;
the data is genuinely ambiguous.

It rewards big clusters of mediocre quality over small clusters of
high quality. A 500-ticket cluster of "account recovery" with internal
variance gets a similar silhouette to a 30-ticket cluster of "two-
factor auth glitch" with very tight internal cohesion. The mean is
weighted by cluster size.

For all those reasons, the pipeline reports silhouette but does not
optimise to it. The clustering is chosen for "is the output useful to
a product manager?" — the silhouette is a diagnostic, not an
objective.

## The recap

- A centroid is `embeddings[mask].mean(axis=0)`. The mean of
  L2-normalised embeddings is not itself unit length, but its
  direction is the best single representative of the cluster.
- Per-row centroid similarity is `dot(emb, centroid) / (||emb|| *
  ||centroid||)`. Sort tickets by this score descending to find the
  three most representative examples per cluster.
- Silhouette score for one row is `(b - a) / max(a, b)` where `a` is
  mean distance to your own cluster and `b` is mean distance to the
  nearest other cluster. Range is `[-1, +1]`.
- Computing silhouette on all `n` rows is `O(n²)`. The pipeline
  samples 1,200 rows for a fast proxy, with a fixed
  `default_rng(42)` for reproducibility.
- Our run's outlier-split silhouette is 0.124 — positive but mushy,
  exactly what you should expect from clustering noise. The metric
  is reported honestly, not optimised away.
- Silhouette penalises non-spherical clusters, useful overlap, and
  small high-quality clusters. Use it as a diagnostic, not an
  objective.

## Try it

Compute centroids and per-row centroid similarity by hand on the
canonical user-wants run.

```python
import numpy as np
import pandas as pd

run = "outputs/option2_20260502_150055"
ass = pd.read_csv(f"{run}/user_wants_assignments.csv")
print("rows:", len(ass), "clusters:", ass["want_id"].nunique())

# We need to re-embed the _want_text since the LLM-extraction stage's
# embeddings are not separately saved; for this exercise compare with
# the centroid_similarity column already in the CSV.
print(ass[["want_id", "centroid_similarity"]].describe())

# For each cluster, pull the top-3 by centroid_similarity and check
# they match example_1..example_3 in user_wants_taxonomy.csv.
top = ass.sort_values("centroid_similarity", ascending=False)
top_per_cluster = top.groupby("want_id").head(3)
print(top_per_cluster[["want_id", "centroid_similarity", "_want_text"]].head(15))
```

For the silhouette experiment, reproduce the 1,200-row sample on the
outlier-split.

```python
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

run = "outputs/option2_20260502_150055"
emb = np.load(f"{run}/embeddings_local.npy")
sem = pd.read_csv(f"{run}/semantic_cluster_assignments.csv")
bert = pd.read_csv(f"{run}/bertopic_assignments.csv")

merged = sem.assign(_idx=range(len(sem))).merge(
    bert[["source_row", "bertopic_topic"]], on="source_row", how="left"
)
mask = pd.to_numeric(merged["bertopic_topic"], errors="coerce").eq(-1)
outlier_idx = merged.loc[mask, "_idx"].to_numpy()
X = normalize(emb[outlier_idx])

km = MiniBatchKMeans(n_clusters=26, random_state=42, n_init=30, batch_size=512)
labels = km.fit_predict(X)

rng = np.random.default_rng(42)
sample = rng.choice(len(X), min(1200, len(X)), replace=False)
sil = silhouette_score(X[sample], labels[sample], metric="cosine")
print(f"silhouette on 1,200-row sample: {sil:.4f}")  # ~0.124
```

For the full-dataset comparison, run silhouette on **all** 1,331 rows
(it will take a few seconds; 1.7M pairwise distances) and confirm the
sampled score is close to the exact one. The variance across samples
is small enough that the 1,200-row proxy is a reliable diagnostic.

For the third experiment, compute silhouette on the Stage 1 clusters
(6,669 rows, 21 clusters plus the `-1` noise). The sampled score
should be much higher — somewhere in the 0.3–0.5 band — because the
main-corpus clusters are real density blobs, not leftovers. Compare
the two numbers and read it as: HDBSCAN found real structure in the
main corpus, KMeans is doing the best it can with the leftovers.
