# 02 — UMAP

## The problem

You ended Lesson 01 convinced that 384-D vectors do not cluster well
directly. You need to project them down. The question is which
projection.

Principal Component Analysis would give you a linear projection that
preserves global variance. It is fast, deterministic, and bad for
clustering. PCA tries to keep total variance, which on
sentence-transformer output ends up flattening topically distinct
clusters into the same plane because the model uses many dimensions
to encode shared "support-text" structure.

t-SNE preserves local neighbourhoods — the right idea — but it is slow,
its output depends heavily on the perplexity hyperparameter, and it
distorts global structure in unpredictable ways. It is also notorious
for producing visualisations where cluster *sizes* and *distances
between clusters* mean nothing at all.

UMAP is the modern alternative. It preserves local neighbourhoods like
t-SNE, runs much faster on 6,669 rows, has a more stable global
geometry, and exposes a small handful of meaningful knobs:
`n_components`, `n_neighbors`, `min_dist`, `metric`, `random_state`.

This lesson is what each of those knobs does and why the pipeline picks
the values it does in three separate places.

## The intuition: a fuzzy neighbourhood graph, then layout it out

UMAP works in two stages. Stage one: build a graph of nearest neighbours
in the high-dimensional input. For each point, find its `n_neighbors`
nearest points by `metric` distance, and connect them with a fuzzy edge
weighted by how close they are. The result is a sparse graph where
local relationships are recorded but absolute distances are forgotten.

Stage two: find a layout in `n_components` dimensions that reproduces
that fuzzy graph as closely as possible. Two points that were neighbours
in the input should be close in the output. Two points that were not
neighbours can land anywhere — UMAP does not waste effort getting their
distances right.

This two-stage design is why UMAP is good at the curse of
dimensionality. The graph step compresses 384 dimensions into
neighbourhood ranks, which are robust to distance flattening. The
layout step then reconstructs distances in a low-D space where
distances actually mean something.

The teaching note inside `cluster_texts` says it the same way at
[scripts/option2_pipeline.py:1261-1278](../../scripts/option2_pipeline.py):

```python
# WHY UMAP TWICE — VISUALIZATION VS CLUSTERING.
# UMAP (Uniform Manifold Approximation and Projection) is a non-linear
# dimensionality reduction algorithm. Intuition: it builds a fuzzy
# neighbourhood graph in the high-dim embedding space, then optimises
# a low-dim layout that preserves those neighbourhoods. We run it
# TWICE with different ``n_components``:
#   * ``n_components=2`` for the on-screen scatter (x, y coords) —
#     humans need 2D, ``min_dist=0.08`` lets points spread out a bit.
#   * ``n_components=10`` for clustering — more dimensions retain
#     more discriminative signal. ``min_dist=0.0`` packs neighbours
#     tightly (which is what HDBSCAN's density estimator wants).
# ``metric="cosine"`` matters: text embeddings live on a sphere, so
# angular distance (cosine) reflects semantic similarity better than
# Euclidean. ``random_state=42`` makes the reduction reproducible.
# ``n_neighbors`` is auto-scaled with the corpus size — too small and
# the manifold gets fragmented, too large and local structure is
# smeared.
```

That paragraph is the entire lesson in 17 lines. The rest of this
document unpacks it.

## n_components: how many dimensions out

`n_components` is the size of the output vectors. For the 6,669
embeddings in our run, the pipeline uses three different values:

- `n_components=2` for the scatter plot.
- `n_components=10` in `cluster_texts` for HDBSCAN to chew on.
- `n_components=8` in `bertopic_from_run.py` for BERTopic's HDBSCAN to
  chew on.

The 8-vs-10 difference is empirical, not principled. BERTopic ships with
8 as a default; the project's own clustering call landed on 10 after
tuning. Both work. Anything from 5 to 20 produces broadly similar
clusters, with the curse weakening below 20 and the discriminative
signal weakening below 5. Read both calls side by side. From
[scripts/option2_pipeline.py:1351-1355](../../scripts/option2_pipeline.py):

```python
n_neighbors = min(30, max(5, len(work) // 200))
reducer_2d = umap.UMAP(n_components=2, n_neighbors=n_neighbors, min_dist=0.08, metric="cosine", random_state=42)
coords = reducer_2d.fit_transform(dense)
x, y = coords[:, 0], coords[:, 1]
reducer_cluster = umap.UMAP(n_components=10, n_neighbors=n_neighbors, min_dist=0.0, metric="cosine", random_state=42)
reduced = reducer_cluster.fit_transform(dense)
```

And from [scripts/bertopic_from_run.py:157-163](../../scripts/bertopic_from_run.py):

```python
umap_model = UMAP(
    n_neighbors=25,
    n_components=8,
    min_dist=0.0,
    metric="cosine",
    random_state=42,
)
```

Two things are identical across both: `metric="cosine"` and
`random_state=42`. We come back to those.

## n_neighbors: how local to be

`n_neighbors` controls the size of the local neighbourhood UMAP cares
about. Small values (5–10) give a very local view: each point only
"knows" its closest few neighbours, and the resulting graph emphasises
fine-grained structure. Large values (50+) blend in global structure
because each point's neighbourhood now spans most of a cluster.

The pipeline auto-scales `n_neighbors` with the corpus size in
`cluster_texts`:

```python
n_neighbors = min(30, max(5, len(work) // 200))
```

For 6,669 tickets that yields `min(30, max(5, 33)) = 30`. For a
hypothetical 1,000-ticket dataset it would yield `min(30, max(5, 5))
= 5`. The cap of 30 prevents the neighbourhood from getting too
global on large datasets; the floor of 5 keeps it from fragmenting on
tiny ones.

`bertopic_from_run.py` uses a fixed `n_neighbors=25`, which is
BERTopic's recommended default. On our 6,669-ticket corpus, the two
choices (auto-30 and fixed-25) produce nearly identical neighbourhoods.

A practical heuristic: if your clusters look fragmented (many small
clusters that should be one), increase `n_neighbors`. If they look
mushy (different topics getting bundled together), decrease it. The
project found that 25–30 was right for support-ticket text at this
scale.

## min_dist: how tight to pack

`min_dist` is the most consequential knob for the difference between
"map for humans" and "map for HDBSCAN". It sets the minimum distance
between points in the output layout.

`min_dist=0.0` lets UMAP pack neighbours right on top of each other.
The result is a layout with very tight density blobs separated by empty
gaps — exactly what a density-based clusterer wants. HDBSCAN sees a
clear "high density here, sparse there" signal and can draw boundaries.

`min_dist=0.08` (or anything above 0.05) forces UMAP to spread points
apart so they do not overlap visually. The result is a layout where
clusters look like distinct shapes a human can tell apart on screen,
but the density blobs are softened — bad for clustering, good for
plotting.

This is exactly why the same code calls UMAP twice. The 2-D output
with `min_dist=0.08` goes to the scatter plot. The 10-D output with
`min_dist=0.0` goes to HDBSCAN. They are not the same projection
viewed at different resolutions; they are two different optimisations
with different objectives.

## metric: cosine, not euclidean

`metric="cosine"` is non-negotiable for sentence-transformer output.
The model was trained with a cosine-similarity objective. Embeddings
that mean similar things have small angles between them; their
Euclidean distances are essentially noise modulated by their norms.

The project enforces this in two layers. First, all embeddings are L2
normalised at production time
([scripts/build_user_wants_taxonomy.py:222-225](../../scripts/build_user_wants_taxonomy.py)):

```python
embeddings = model.encode(
    texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True
)
return np.asarray(embeddings, dtype=np.float32)
```

`normalize_embeddings=True` divides every vector by its L2 norm, so all
embeddings live on the unit hypersphere. Once they are unit-length,
cosine similarity equals dot product — `cos(u, v) = dot(u, v)` — and
Euclidean distance becomes a monotonic function of cosine distance
(`||u - v||² = 2 - 2·dot(u, v)`).

Second, UMAP is told `metric="cosine"` so its neighbour graph uses
angular distance even before any normalisation. Belt and braces.

In contrast, HDBSCAN downstream uses `metric="euclidean"` because by
that point UMAP's output is **not** on the unit sphere — it is in some
arbitrary 8-D or 10-D space UMAP picked. Euclidean is the right metric
there. Read it in
[scripts/option2_pipeline.py:1362-1364](../../scripts/option2_pipeline.py):

```python
min_cluster_size = max(12, min(80, len(work) // 90))
clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=max(5, min_cluster_size // 3), metric="euclidean")
labels = clusterer.fit_predict(reduced)
```

Cosine on the way in, Euclidean on the way out. That is the right pairing.

## random_state: reproducibility

UMAP uses stochastic optimisation. Without a seed, every run produces
slightly different output — the topology is preserved, but the exact
coordinates rotate, mirror, and shift. For a one-off plot that is
fine. For a pipeline that writes a CSV and a dashboard reads from it,
it is a problem: tomorrow's `cluster_id` 7 might be today's
`cluster_id` 3, the per-row x/y coordinates will be different, and any
cached downstream artefact gets stale.

`random_state=42` fixes the seed. The same input embeddings and the
same UMAP version will produce identical output every time. This is
why all three UMAP calls in the project pass the same constant, and
why the BERTopic call does too.

Forty-two is a Hitchhiker's-Guide-to-the-Galaxy joke. It has zero
mathematical significance. Any constant would do.

## Why the 2-D output is not a clustering input

This is the most important caveat in the lesson, repeated here because
it gets violated all the time. The 2-D coordinates in
`semantic_cluster_assignments.csv` (the `x` and `y` columns) are for
display only. They went through `min_dist=0.08` to spread apart for
the eye. Clustering on them would produce different — and worse —
groupings than the 10-D output that the actual `cluster_id` column
came from.

The dashboard at
[scripts/dashboard/pages/06_Ticket_Map.py:14-19](../../scripts/dashboard/pages/06_Ticket_Map.py)
spells out the consequence:

```python
# * **Crucial intuition: the X and Y numbers are not meaningful.** Only
#   *relative position* matters — which dots are close to which. A point at
#   (3.2, -1.7) tells you nothing on its own; what matters is "this dot
#   sits in the cloud of account-recovery tickets, far from the cloud of
#   payment disputes." That's why we hide ticks and axis titles — keeping
#   them would invite users to read meaning where there is none.
```

The page hides axis ticks for that reason. Visitors who see a number
on an axis assume the number means something. UMAP coordinates do not.

## The recap

- UMAP works in two stages: build a fuzzy k-NN graph in high
  dimensions, then optimise a low-D layout that preserves the graph.
- `n_components` sets the output dimensionality. Use 2 for plots,
  8–10 for clustering. Anything outside that band degrades quickly.
- `n_neighbors` controls locality. The pipeline auto-scales to
  `min(30, max(5, n // 200))` in `cluster_texts` and uses a fixed 25
  in `bertopic_from_run.py`. Both work for our corpus.
- `min_dist=0.0` packs points for clustering; `min_dist=0.08` spreads
  them for plotting. The choice depends entirely on who consumes the
  output.
- `metric="cosine"` matches the sentence-transformer training
  objective and the L2-normalised embeddings.
- `random_state=42` makes the reduction reproducible across runs so
  downstream artefacts stay stable.
- 2-D coordinates are for human eyes, not for HDBSCAN. Hide the axis
  ticks if you display them.

## Try it

Compare 2-D and 10-D UMAP layouts on the same input.

```python
import numpy as np
import pandas as pd
import umap

emb = np.load("outputs/option2_20260502_150055/embeddings_local.npy")
csv = pd.read_csv("outputs/option2_20260502_150055/semantic_cluster_assignments.csv")
assert len(emb) == len(csv) == 6669

# 2-D, min_dist=0.08 (visualization-style)
red2 = umap.UMAP(n_components=2, n_neighbors=30, min_dist=0.08,
                 metric="cosine", random_state=42).fit_transform(emb)

# 10-D, min_dist=0.0 (clustering-style)
red10 = umap.UMAP(n_components=10, n_neighbors=30, min_dist=0.0,
                  metric="cosine", random_state=42).fit_transform(emb)

print("2-D shape:", red2.shape, "x range:", red2[:, 0].min(), red2[:, 0].max())
print("10-D shape:", red10.shape, "first-axis range:", red10[:, 0].min(), red10[:, 0].max())
```

Notice the x range in 2-D will be roughly `(-15, 25)` — UMAP picks
whatever scale falls out of the optimiser. Comparing the absolute
numbers across two runs (or to your colleague's run) is meaningless.

For the second experiment, plot `red2` coloured by `csv["cluster_id"]`
and overlay `csv["x"]` and `csv["y"]`. The two layouts should look
similar in topology but rotated, mirrored, or stretched relative to
each other. That is the rotational ambiguity of UMAP — preserved
neighbourhoods, arbitrary basis. Now hide your axis ticks
(`plt.xticks([])`, `plt.yticks([])`) to internalise the lesson before
you publish another scatter with axis numbers.

For the third experiment, run UMAP twice with different
`random_state` values (try 42 and 7). The clusters survive but the
coordinates are completely different. This is the reason
`random_state=42` is in every UMAP call in the project: without it,
the dashboard's per-ticket `(x, y)` would change on every rerun.
