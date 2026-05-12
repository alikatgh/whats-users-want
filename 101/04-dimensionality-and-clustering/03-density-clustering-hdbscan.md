# 03 — Density Clustering with HDBSCAN

## The problem

You have a 10-D UMAP embedding of 6,669 tickets. Tight clouds of
similar tickets sit next to each other. Sparse strings of unrelated
tickets connect the clouds. There is no natural number of clusters —
some tickets fall into a 500-strong "account recovery" blob, some into
a 12-strong "two-factor auth glitch" blob, and many into nothing
recognisable at all. You need a clustering algorithm that can handle
that.

KMeans cannot. KMeans demands you fix `k` up front and then forces every
point into one of `k` groups, including the tickets that genuinely do
not belong anywhere. The result on a heterogeneous corpus is always the
same: a small number of huge, mushy clusters with vague labels.

HDBSCAN — Hierarchical Density-Based Spatial Clustering of Applications
with Noise — is built for exactly this case. It makes two calls KMeans
will not. First, it picks the number of clusters by itself, based on
where density actually concentrates. Second, it admits ignorance: any
point that is not in a dense region gets cluster ID `-1`, the noise
bucket. You do not have to assign every point.

The pipeline runs HDBSCAN three times — once on the full corpus in
`cluster_texts`, once again inside BERTopic in `bertopic_from_run.py`,
and a third time on a 250-row LLM extraction in `cluster_wants`. This
lesson is what HDBSCAN does at each call, what its parameters mean, and
why we are happy that 21% of the corpus ended up in topic `-1`.

## The intuition: dense neighbourhoods, sparse boundaries

HDBSCAN starts with the same nearest-neighbour graph idea as UMAP, but
uses it for a different end. For every point it computes a "core
distance": the distance to its `min_samples`-th nearest neighbour. A
point in a dense region has a small core distance; a point in a sparse
region has a large one.

Then it builds a "mutual reachability" graph where the edge between
two points is the maximum of their two core distances and their actual
distance. This is the trick. Points in the same dense blob keep their
direct distances. Points across a sparse gap get artificially pushed
apart, because at least one of them has a large core distance.

Run a minimum spanning tree on that graph, then cut it at varying
thresholds, and you get a hierarchy of nested clusters. HDBSCAN selects
a flat partition by picking, at each level of the hierarchy, whichever
partition is "stable" across the widest range of thresholds. That is
the EOM (Excess of Mass) selection method.

Anything left out — points the algorithm could not put in any stable
cluster — gets label `-1`. That is the noise bucket, and it is the
single most useful thing about HDBSCAN.

The teaching note inside `cluster_texts` says it the same way at
[scripts/option2_pipeline.py:1279-1289](../../scripts/option2_pipeline.py):

```python
# WHY HDBSCAN — DENSITY-BASED CLUSTERING.
# Unlike k-means, HDBSCAN does NOT require ``k`` up front. It builds
# a hierarchy of density-connected components and selects the most
# stable clusters across multiple density thresholds. ``min_cluster_size``
# is the only hard-knob: clusters smaller than this become noise
# (``cluster_id = -1``). We adapt it to corpus size:
# ``max(12, min(80, n // 90))`` — ~75 for 6,728 tickets. This means
# HDBSCAN can declare some tickets as "outliers" (cluster -1), which
# is gold for finding emerging issues that don't fit any pattern yet.
# ``min_samples`` controls the density floor; ``metric="euclidean"``
# is correct AFTER UMAP (UMAP outputs are not on a unit sphere).
```

## min_cluster_size: the size floor

`min_cluster_size` is the smallest collection of points HDBSCAN is
willing to call a cluster. Anything smaller becomes noise. This is
where you express your tolerance for tiny clusters versus your
patience for noise.

The Stage 1 call at
[scripts/option2_pipeline.py:1362-1364](../../scripts/option2_pipeline.py)
adapts the parameter to corpus size:

```python
min_cluster_size = max(12, min(80, len(work) // 90))
clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=max(5, min_cluster_size // 3), metric="euclidean")
labels = clusterer.fit_predict(reduced)
probabilities = getattr(clusterer, "probabilities_", np.ones(len(work)))
```

For our 6,669 tickets that yields `max(12, min(80, 74)) = 74`. Roughly
"clusters under 74 tickets are noise". The result is the 21-cluster
output you see in `semantic_clusters.csv` (counted as 22 lines
including the `-1` row and the header).

The Stage 2 BERTopic call uses a slightly stricter setting at
[scripts/bertopic_from_run.py:164-169](../../scripts/bertopic_from_run.py):

```python
hdbscan_model = HDBSCAN(
    min_cluster_size=min_topic_size,
    min_samples=max(5, min_topic_size // 3),
    metric="euclidean",
    prediction_data=False,
)
```

with `min_topic_size=35` from the CLI. 35 is BERTopic-team-tuned for
"a topic must contain at least 35 docs to count as a topic". It produces
53 named topics on our corpus plus the `-1` noise topic of 1,381
tickets — counted in the actual output at
[outputs/option2_20260502_150055/bertopic_metadata.json](../../outputs/option2_20260502_150055/bertopic_metadata.json):

```json
{
  "docs": 6669,
  "embeddings_shape": [6669, 384],
  "topics": 53
}
```

The Stage 6 user-wants call uses a much smaller floor at
[scripts/build_user_wants_taxonomy.py:323-330](../../scripts/build_user_wants_taxonomy.py):

```python
clusterer = hdbscan.HDBSCAN(
    min_cluster_size=min_cluster_size,
    min_samples=1,
    metric="euclidean",
    cluster_selection_method="eom",
    cluster_selection_epsilon=0.15,
)
labels = clusterer.fit_predict(embeddings.astype(np.float64))
```

with `min_cluster_size=5` and a much smaller dataset (~250 LLM-extracted
wants). Different scale, different parameters, same algorithm.

## min_samples: the density floor

`min_samples` controls how aggressive HDBSCAN is at declaring outliers.
Higher values are stricter: a point is only "in a cluster" if it has
many other points crowded close by. Lower values are more permissive,
labelling more points as cluster members and fewer as noise.

The pipeline uses two patterns. The Stage 1 and Stage 2 calls scale it
with `min_cluster_size`:

```python
min_samples=max(5, min_cluster_size // 3)
```

For our 74 / 35 cluster sizes that gives 24 / 11. Roughly: a real
cluster needs about a third as many supporting neighbours as its size
floor. That is a balance between "leave too much in noise" and "merge
distinct clusters".

The Stage 6 user-wants call sets `min_samples=1`. With only 250 docs,
density estimates are unreliable, and we would rather assign borderline
points to the nearest cluster than throw them out. The teaching note at
[scripts/build_user_wants_taxonomy.py:265-269](../../scripts/build_user_wants_taxonomy.py)
spells it out:

```python
# * ``min_samples=1`` — controls how aggressive HDBSCAN is at
#   declaring a point an outlier. Higher = stricter = more
#   ``-1`` labels. We set it to 1 because our data is small and
#   we would rather assign a borderline point to its nearest
#   cluster than throw it away.
```

The contrast across the three calls is intentional. On big data with
real density, be strict. On small data with weak density signals, be
permissive.

## cluster_selection_method and epsilon

The Stage 6 call uses two extra knobs:

```python
cluster_selection_method="eom",
cluster_selection_epsilon=0.15,
```

`"eom"` (Excess of Mass) is the default and the right choice for
macro-level taxonomies. The alternative, `"leaf"`, returns the deepest
splits in the cluster hierarchy and tends to over-fragment.

`cluster_selection_epsilon=0.15` is a merge threshold in embedding
distance. Two micro-clusters within 0.15 of each other get merged into
one. The teaching note at
[scripts/build_user_wants_taxonomy.py:275-278](../../scripts/build_user_wants_taxonomy.py)
explains the tuning:

```python
# * ``cluster_selection_epsilon=0.15`` — a merge threshold in
#   embedding distance. Two micro-clusters that are this close
#   get merged. We tuned 0.15 to avoid splitting near-synonyms
#   like "lift the ban" vs. "remove the block".
```

This is one of the few places in the pipeline where a hand-tuned
constant survives in production. Lower values fragment the taxonomy
into too many clusters; higher values collapse meaningfully different
wants into one.

## Why noise is a feature, not a bug

The single best thing about HDBSCAN is that it can say "I don't know."
Stage 1 produced a `-1` cluster of 1,381 tickets. Stage 2 (BERTopic)
produced its own `-1` topic of, again, 1,381 tickets — the same
tickets, since BERTopic uses HDBSCAN under the hood with our same
embeddings. That is 21% of the corpus.

You could argue this is a clustering failure. Twenty-one percent
unassigned looks bad on a slide. But forcing those 1,381 tickets into
the existing 21 clusters would be worse: the labels would get
contaminated with noise, the per-cluster top terms would smear toward
generic support-ticket vocabulary, and emerging issues would be
invisible because they would have been merged into "account recovery"
or "diamonds purchase" by mistake.

The pipeline takes a different approach: treat the `-1` bucket as its
own object of study. Stage 4 (`split_outlier_bucket.py`) re-clusters
just the noise tickets with KMeans (so every ticket gets a sub-theme),
producing 26 sub-themes you can read in
[outputs/option2_20260502_150055/outlier_subtopics.csv](../../outputs/option2_20260502_150055/outlier_subtopics.csv).
That is the subject of [04-kmeans-fallback.md](04-kmeans-fallback.md).

The script's own docstring at
[scripts/split_outlier_bucket.py:1-13](../../scripts/split_outlier_bucket.py)
opens with:

```python
"""Stage 4 — split BERTopic noise into 26 sub-themes.

BERTopic assigns ``topic = -1`` to tickets it cannot confidently cluster. With
1,381 tickets in there, that "topic" is the largest single group in the dataset.
This stage refuses to lose that signal: it slices the cached multilingual
embeddings down to the noise rows and runs a forced MiniBatchKMeans (so every
ticket gets a sub-theme) plus a TF-IDF labelling pass.
```

The honest read: HDBSCAN's noise is a triage signal. It says "these
tickets do not match any existing pattern; treat them with extra care."
That is exactly what you want from a clustering algorithm.

## Probabilities for soft assignments

HDBSCAN also produces a per-row probability, accessible as
`clusterer.probabilities_`. It is the algorithm's confidence that a
given point really belongs to its assigned cluster. The pipeline reads
this back at
[scripts/option2_pipeline.py:1364-1365](../../scripts/option2_pipeline.py):

```python
labels = clusterer.fit_predict(reduced)
probabilities = getattr(clusterer, "probabilities_", np.ones(len(work)))
```

The `getattr` fallback to ones is for the KMeans branch, which has no
probabilities. The probability ends up in `cluster_probability` in
`semantic_cluster_assignments.csv`. A ticket with `cluster_id=3` and
`cluster_probability=0.93` is firmly in cluster 3; one with the same
ID but `cluster_probability=0.21` is on the edge and could just as
easily have been noise.

The dashboard does not surface this column directly, but downstream
code in `summarize` uses it to sort representative examples by
confidence (best first).

## When HDBSCAN fails: the fallback

Two of the three HDBSCAN calls have explicit fallbacks. From
[scripts/option2_pipeline.py:1366-1373](../../scripts/option2_pipeline.py):

```python
except Exception as exc:
    print(f"[warn] HDBSCAN unavailable/failed: {exc}. Falling back to MiniBatchKMeans.", file=sys.stderr)
    from sklearn.cluster import MiniBatchKMeans

    k = max(8, min(35, int(math.sqrt(len(work) / 2))))
    clusterer = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=20, batch_size=1024)
    labels = clusterer.fit_predict(reduced)
    probabilities = np.ones(len(work))
```

HDBSCAN's C extension is occasionally broken across Python upgrades,
NumPy upgrades, or wheel mismatches on certain platforms. The fallback
is KMeans with `k = max(8, min(35, sqrt(n/2)))`. The tradeoff is no
noise bucket and no probabilities — every ticket gets forced into a
cluster, which is the KMeans contract. That is the topic of the next
lesson.

## The recap

- HDBSCAN finds clusters by density. It does not need `k` up front.
- `min_cluster_size` is the size floor below which a candidate cluster
  becomes noise. The pipeline scales it with corpus size: 74 for 6,669
  tickets, 35 inside BERTopic, 5 for the 250-row user-wants extraction.
- `min_samples` is the density floor. Higher means stricter, more
  noise. The pipeline scales it as `min_cluster_size // 3` on big data
  and sets it to 1 on small data.
- `metric="euclidean"` is correct on UMAP output because UMAP output
  is not on a unit sphere.
- The noise bucket (`cluster_id = -1`) is a feature. It is honest
  about what cannot be clustered, and Stage 4 turns it into 26 named
  sub-themes via KMeans. In our run, 1,381 of 6,669 tickets — 21% —
  ended up in `-1`.
- `probabilities_` gives a per-row confidence. The pipeline stores it
  as `cluster_probability` and uses it for sorting representative
  examples.

## Try it

Reproduce the Stage 1 cluster counts and the noise bucket size from
the cached embeddings.

```python
import numpy as np
import pandas as pd

emb = np.load("outputs/option2_20260502_150055/embeddings_local.npy")
print("embeddings:", emb.shape)  # (6669, 384)

import umap
red = umap.UMAP(n_components=10, n_neighbors=30, min_dist=0.0,
                metric="cosine", random_state=42).fit_transform(emb)

import hdbscan
n = len(red)
mcs = max(12, min(80, n // 90))
print("min_cluster_size:", mcs)  # 74
clusterer = hdbscan.HDBSCAN(min_cluster_size=mcs,
                             min_samples=max(5, mcs // 3),
                             metric="euclidean")
labels = clusterer.fit_predict(red)

print("clusters:", len(set(labels)) - (1 if -1 in labels else 0))
print("noise tickets:", int((labels == -1).sum()))
print("noise share:", (labels == -1).mean().round(3))
```

Expected ballpark: 21 clusters and around 1,381 noise tickets, give or
take a few because UMAP is stochastic past the seed and HDBSCAN is
sensitive to small perturbations near cluster boundaries. Compare your
output to the canonical
[outputs/option2_20260502_150055/semantic_clusters.csv](../../outputs/option2_20260502_150055/semantic_clusters.csv).

For the second experiment, look at the per-row probabilities:

```python
probs = clusterer.probabilities_
print("median confidence (assigned):", np.median(probs[labels != -1]).round(3))
print("low-confidence tickets (<0.3, in some cluster):",
      int(((labels != -1) & (probs < 0.3)).sum()))
```

Those low-confidence tickets are the borderline cases. Read three of
them by indexing into `semantic_cluster_assignments.csv` and you will
find tickets that genuinely sit between two topics — a complaint that
mentions both account recovery and a payment problem, for example.
That is exactly the population that would have been mis-assigned by
KMeans, which has no concept of "borderline".
