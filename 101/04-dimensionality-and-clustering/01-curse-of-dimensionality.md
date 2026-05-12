# 01 — The Curse of Dimensionality

## The problem

You finished Module 03 with a NumPy array of shape `(6669, 384)` saved
on disk as `embeddings_local.npy`. Each row is one support ticket
projected into a 384-dimensional semantic space by
`paraphrase-multilingual-MiniLM-L12-v2`. Cosine similarity between any
two rows reflects how close their meanings are.

Your first instinct is probably right: pass this matrix to a clustering
algorithm. Group the rows by where they land. Done.

It will not work. Not because the embeddings are bad — they are excellent —
but because 384-dimensional Euclidean space behaves nothing like the 2-D
plane your intuition was built for. Your clustering algorithm needs
distances to be meaningful, and in 384 dimensions distances are not
meaningful in the way you think they are. Every point is roughly the same
distance from every other point. Density estimates collapse. The
clustering algorithm runs blind.

This is "the curse of dimensionality", and it is the entire reason the
pipeline runs UMAP twice before HDBSCAN gets a chance to look at the
data. Read [scripts/option2_pipeline.py:1336-1364](../../scripts/option2_pipeline.py)
and you will see the order: TF-IDF → SVD reduction to 80-dim → UMAP
to 10-dim → HDBSCAN. Or for the embedding backend: 384-dim embeddings
→ UMAP to 10-dim → HDBSCAN. Never directly on the raw 384.

This lesson is the why. The next lesson, [02-umap.md](02-umap.md), is
the how.

## The intuition: distances flatten as dimensions grow

Pick a random point in a 1-D segment, length 1. Its average distance to
another random point is 1/3. Pick a random point in a 2-D unit square.
The average distance is about 0.52. Pick one in a 3-D unit cube — about
0.66. Now imagine doing this in a 384-D unit hypercube. The distance
keeps growing, but more importantly, the **ratio between the smallest
and largest pairwise distances shrinks toward 1**.

In 2-D you can have two points 0.05 apart and two points 1.4 apart in
the same cloud. The ratio is 28×. The "near" pair is meaningfully
closer than the "far" pair. A density-based clusterer can spot the dense
neighbourhood.

In 384-D, with the same number of points, the ratio of nearest to
farthest pairwise distance might be 1.05. Every point is "about the same
distance" from every other point. There is no neighbourhood to spot.

The technical statement is: as dimensionality grows, the variance of
pairwise distances shrinks relative to the mean, and almost all points
end up on a thin shell at roughly the same distance from the origin and
from each other. This is why the project's own teaching note in
[scripts/option2_pipeline.py:1280-1289](../../scripts/option2_pipeline.py)
is careful to write `metric="euclidean"` is correct **after UMAP**, not
on the 384-D vectors:

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

Read the last line carefully. The UMAP output is what HDBSCAN sees. The
raw 384-D embeddings would defeat any Euclidean clustering attempt no
matter how careful the parameters were.

## The hub problem

There is a second flavour of the curse, which the literature calls the
"hub" problem. In high dimensions, a small number of points end up being
the nearest neighbour of a disproportionate number of other points.
These hubs distort density estimates and similarity rankings.

For 384-D sentence embeddings the hub effect is particularly nasty
because the model maps almost all support tickets — questions, complaints,
appeals — to vectors that are loosely "support-text-shaped". They share
a generic centroid that pulls everything toward the middle. The hub is
the centre of the support-text cloud, and almost every ticket is "close"
to it, even tickets about completely different things.

UMAP attacks both the flattening and the hub problem at once. Its
neighbourhood graph is built on **k-nearest-neighbour rank**, not raw
distance. Rank is robust to flattening — even if all distances are
within a factor of 1.05, you can still order points by which is the
1st nearest, the 2nd nearest, the 25th nearest. UMAP only looks at the
top-k of those rankings, so the absolute distances stop mattering.

## Why 8–10 dimensions for clustering

Once UMAP has built a low-dimensional embedding, the curse weakens fast.
At 10 dimensions, distances still concentrate slightly, but the
concentration is mild enough that HDBSCAN's mutual-reachability
distance — its core trick for finding density blobs — works again. At
50 dimensions it would still struggle. At 384 it has no chance.

So why not project all the way to 2-D for clustering? Because each
dimension UMAP keeps preserves more discriminative signal. Two
clusters that are well-separated along an axis you happen to drop
collapse on top of each other. Eight to ten dimensions is the sweet
spot the BERTopic team and the project converged on independently.

You can see the choice in two places. First in
[scripts/option2_pipeline.py:1351-1355](../../scripts/option2_pipeline.py):

```python
n_neighbors = min(30, max(5, len(work) // 200))
reducer_2d = umap.UMAP(n_components=2, n_neighbors=n_neighbors, min_dist=0.08, metric="cosine", random_state=42)
coords = reducer_2d.fit_transform(dense)
x, y = coords[:, 0], coords[:, 1]
reducer_cluster = umap.UMAP(n_components=10, n_neighbors=n_neighbors, min_dist=0.0, metric="cosine", random_state=42)
reduced = reducer_cluster.fit_transform(dense)
```

Two reductions, fed into two different consumers. The 2-D output goes
to the scatter plot in `semantic_ticket_map.html`. The 10-D output goes
to HDBSCAN.

Second in [scripts/bertopic_from_run.py:157-163](../../scripts/bertopic_from_run.py):

```python
umap_model = UMAP(
    n_neighbors=25,
    n_components=8,
    min_dist=0.0,
    metric="cosine",
    random_state=42,
)
```

Eight here, ten in the other call. They are both in the band that
works. If you run a third experiment yourself, you will find anything
from 5 to 20 produces broadly similar clusters; below 5 you start
losing real groups, above 20 the curse creeps back.

## Why 2 dimensions for visualisation only

The page that consumes the 2-D output, `semantic_ticket_map.html`,
plots all 6,669 tickets as dots. The Streamlit version in
[scripts/dashboard/pages/06_Ticket_Map.py:202-209](../../scripts/dashboard/pages/06_Ticket_Map.py)
explicitly hides the axis numbers:

```python
# X and Y come from a UMAP projection — the numbers themselves are arbitrary;
# only relative position matters. Hide ticks and titles so viewers don't read meaning into them.
fig.update_layout(
    margin=dict(l=10, r=10, t=10, b=10),
    legend_title_text=color_label,
    xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, title=""),
    yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, title=""),
)
```

`showticklabels=False` removes the numbers, `showgrid=False` removes the
gridlines, `title=""` clears the axis label. The reason for all of this
is in the page docstring at
[scripts/dashboard/pages/06_Ticket_Map.py:14-19](../../scripts/dashboard/pages/06_Ticket_Map.py):
"the X and Y numbers are not meaningful." A point at `(3.2, -1.7)`
tells you nothing on its own. UMAP picked those numbers as a layout for
visual clarity, the way a force-directed graph picks node positions.
Only **relative position** carries information. If two dots are in the
same cloud, they are semantically similar. If they are in different
clouds, they are not.

This caveat trips people up because every other 2-D scatter they have
seen in their lives — a salary-vs-experience plot, a weight-vs-height
plot — has meaningful axes. UMAP scatter does not. The axes are an
arbitrary basis the optimiser chose. Rotate the whole plot 30 degrees
and the result is equally valid.

This is also why we **never cluster on the 2-D output**. The
information loss going from 384 to 2 dimensions is enormous. What
survives is "are these tickets in the same cloud or a different one",
which is good enough for a human looking at coloured dots. It is not
good enough for HDBSCAN to draw cluster boundaries.

## Why projecting first is mathematically safe

A reasonable worry: if we project from 384 to 10, surely we lose
information that could be useful for clustering? Yes — and that is the
point. The information we lose is mostly noise. A 384-D
sentence-transformer vector contains genuinely useful signal in maybe
50–80 dimensions; the rest is fine-grained variation that the model
captured but that is not relevant to coarse topic separation. UMAP's
neighbourhood-preserving objective is, in practice, very good at
keeping the topical signal and dropping the noise.

The TF-IDF backend takes a similar precaution at
[scripts/option2_pipeline.py:1336-1338](../../scripts/option2_pipeline.py):

```python
n_components = min(80, max(2, features.shape[1] - 1), max(2, features.shape[0] - 1))
svd = TruncatedSVD(n_components=n_components, random_state=42)
dense = normalize(svd.fit_transform(features))
```

That is `TruncatedSVD` — a linear dimensionality reduction — projecting
the sparse TF-IDF matrix from tens of thousands of dimensions down to
80. Same idea: kill the curse before the clusterer sees it. SVD is
linear, UMAP is non-linear; both are pre-processing steps with the same
goal.

## The recap

- 384-D embeddings flatten distances. Every pair of points ends up
  about the same distance apart. HDBSCAN cannot find density blobs in
  that.
- The fix is to project to a lower dimension first. The pipeline uses
  UMAP for embeddings (8 or 10 components for clustering, 2 for
  plotting) and SVD for TF-IDF (80 components).
- Two-dimensional output is for humans only. The X and Y numbers are
  arbitrary; only relative position matters. The dashboard explicitly
  hides axis ticks to drive that home.
- Eight to ten dimensions is the empirical sweet spot for clustering
  text embeddings. Lower and you lose discriminative signal; higher
  and the curse creeps back.

## Try it

Open a Python shell in the project root and verify the curse with the
real cached embeddings:

```python
import numpy as np

emb = np.load("outputs/option2_20260502_150055/embeddings_local.npy")
print(emb.shape, emb.dtype)  # (6669, 384) float32

rng = np.random.default_rng(42)
sample = emb[rng.choice(len(emb), 1000, replace=False)]

# Pairwise Euclidean distance ratio: max / min on a 1000-row sample.
d = np.linalg.norm(sample[:, None, :] - sample[None, :, :], axis=-1)
d = d[np.triu_indices_from(d, k=1)]
print(f"raw 384-D: min={d.min():.4f}, max={d.max():.4f}, ratio={d.max()/d.min():.2f}")

# Now reduce to 10-D with UMAP and look at the same ratio.
import umap
red = umap.UMAP(n_components=10, n_neighbors=20, min_dist=0.0,
                metric="cosine", random_state=42).fit_transform(emb[:1500])
sub = red[rng.choice(len(red), 1000, replace=False)]
d2 = np.linalg.norm(sub[:, None, :] - sub[None, :, :], axis=-1)
d2 = d2[np.triu_indices_from(d2, k=1)]
print(f"reduced 10-D: min={d2.min():.4f}, max={d2.max():.4f}, ratio={d2.max()/d2.min():.2f}")
```

Two things to notice. The 384-D max-to-min ratio will sit somewhere
around 4–8×, which sounds like a lot until you compare it to the 10-D
ratio of 100× or more. The reduced space has a much wider dynamic
range — exactly what HDBSCAN needs to spot dense blobs and gaps.

For the second experiment, project the same 1,500 embeddings to 2-D
and plot them with matplotlib. Colour by `cluster_id` from
`semantic_cluster_assignments.csv` (you will need to align the indices
— `np.load` gives you positional rows; the CSV has the same order).
You will see the topic-1 "diamonds" cluster, the topic-0 "account
recovery" cluster, and the noise band running through the middle.
That noise band is the 1,381 tickets HDBSCAN refused to assign — the
subject of [03-density-clustering-hdbscan.md](03-density-clustering-hdbscan.md).
