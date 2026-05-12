# 03 — Embeddings, the short version

## The problem

TF-IDF can do a lot. It cannot do this:

```
"I cannot login"
"разблокируйте мне аккаунт"
"please unblock my account"
"no puedo entrar"
```

These four sentences mean roughly the same thing — the user has lost
access and wants it back. TF-IDF treats them as four documents with
**zero shared tokens**. The Russian phrase has no Latin characters at
all. The Spanish phrase shares only `unblock`/`entrar` semantically,
nothing lexically. After tokenisation, the four documents land in
nearly orthogonal regions of the 6,000-dimensional sparse space.
Clustering separates them.

Embeddings do not. An embedding model takes a string and returns a
single dense vector — typically a few hundred floating-point numbers —
chosen so that strings with **similar meaning** land near each other in
that vector space. Two paraphrases of the same complaint, in two
different languages, end up at nearly the same coordinates. That is
the whole point.

This lesson covers what an embedding actually is, the
`SentenceTransformer.encode(...)` call inside
[`embed_texts`](../../scripts/option2_pipeline.py), why
`normalize_embeddings=True` is the small flag that makes everything
downstream cheaper, and the single-file `.npy` cache that keeps the
pipeline re-runnable. The specific model — why MiniLM, why the
`paraphrase-multilingual` variant, why 384 dimensions — gets its own
lesson next.

## What an embedding actually is

You have seen embeddings before, possibly without the name. A 2-D
scatter plot from UMAP is an embedding. A word2vec vector is an
embedding. A Jaccard-similarity score reduced to a number is an
embedding of a pair. The general definition: an **embedding** is a
function from objects (words, sentences, images) to fixed-length
vectors, chosen so that geometric relationships in the vector space
reflect semantic relationships between the objects.

For text, the most useful kind of embedding right now is a
**sentence embedding**. A neural network — typically a transformer
encoder — reads the entire sentence at once and produces a single
vector that represents its meaning. The training objective decides
what "meaning" means: in the paraphrase-multilingual MiniLM family
(Lesson 04), the network is trained on pairs of paraphrases across
languages, with the explicit goal that paraphrases land near each
other and unrelated sentences land far apart.

The output is a vector in some fixed-dimensional space — 384, 512,
768, 1536 are common choices. Every sentence becomes a point in that
space. Cosine similarity between two points is a direct measure of
how related they are.

You do not have to understand the transformer architecture to use
this. You can treat it as a black box: `text -> vector`.

```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
v = model.encode("please unblock my account")
print(v.shape)   # (384,)
```

The same model maps the Russian, Spanish, and English versions of the
sentence to nearly the same 384-dim vector. The pipeline relies on
exactly this property.

## Why cosine similarity, and not Euclidean

Once every sentence is a vector, you have to decide how to measure
"closeness". The two obvious candidates are:

- **Euclidean distance**: `‖u - v‖`. Straight-line distance in
  384-dim space.
- **Cosine similarity**: `dot(u, v) / (‖u‖ * ‖v‖)`. The cosine of
  the angle between the two vectors.

For sentence embeddings, cosine wins. The reason is that embeddings
trained on paraphrase tasks live approximately on the surface of a
sphere — what matters is the **direction** of the vector, not its
length. A short sentence and a long sentence about the same topic
will have similar directions but different magnitudes, because longer
sentences typically produce larger raw vector norms before
normalisation. Euclidean distance penalises this magnitude difference;
cosine similarity ignores it by construction.

You will see this assumption baked into the pipeline. UMAP is called
with `metric="cosine"`
([scripts/option2_pipeline.py:1351](../../scripts/option2_pipeline.py)),
the c-TF-IDF labelling step uses argsort over a mean vector (which is
direction-only after L2 normalisation), and the per-cluster centroid
similarity in
[`build_user_wants_taxonomy.py`](../../scripts/build_user_wants_taxonomy.py)
is explicitly the cosine formula
(Lesson 05).

## Why "I cannot login" and "разблокируйте мне аккаунт" land near each other

The mechanism is training data, not magic. The
`paraphrase-multilingual-MiniLM-L12-v2` model was fine-tuned on
hundreds of millions of paraphrase pairs spanning ~50 languages. The
training loop took a sentence in English, its translation in another
language, and pushed the two embeddings towards each other while
pushing them away from a randomly sampled third sentence. Repeat for
billions of training steps; the network learns a vector space where
**meaning crosses the language boundary**.

In our corpus this is not abstract. The `model_text` column contains
English ("I cannot login"), Russian ("разблокируйте мне аккаунт"),
Spanish, Portuguese, Tagalog, and romanised Chinese phrases — often
in the same ticket. TF-IDF would split a single semantic cluster into
four or five parallel clusters, one per language. Embeddings collapse
them into one.

You can see the payoff in the cluster summaries. Cluster 13
(`account, restore, deleted, number, spam, restore account, phone`,
624 tickets) and cluster 19 (`unban, user, block, insults, unban
user, points, proofs`, 390 tickets) both contain mixed-language
tickets. The cluster IDs come from HDBSCAN running on the dense
MiniLM embeddings, with TF-IDF labels applied **after** the fact for
human readability. The clustering itself does not care what
language the ticket was written in.

## The `embed_texts` function

Here is the embedding code, end to end.
[scripts/option2_pipeline.py:1213-1223](../../scripts/option2_pipeline.py):

```python
if backend == "local":
    if cache.exists():
        return np.load(cache), None, f"local-cache:{model_name}"
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    arr = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=True)
    arr = np.asarray(arr, dtype=np.float32)
    np.save(cache, arr)
    return arr, None, f"local:{model_name}"
```

Read it line by line.

**`if cache.exists():`** — first thing the function does is check if the
embedding has already been computed for this run. The cache path is
`out_dir / f"embeddings_{backend}.npy"`. For our run that is
`outputs/option2_20260502_150055/embeddings_local.npy`, 10.2 MB on
disk. If the file is there, we load it and return early. Re-running
the pipeline (because you changed a chart, or fixed a typo in the
CSV writer, or want to re-cluster with different HDBSCAN parameters)
takes seconds instead of a minute.

**`from sentence_transformers import SentenceTransformer`** — local
import, on purpose. The `sentence-transformers` package transitively
imports PyTorch, which loads ~300 MB of native code and CUDA
introspection. If you only ran `option2_pipeline.py --help`, you
would not want to wait for that. Local imports are a lazy-loading
pattern this codebase uses everywhere.

**`SentenceTransformer(model_name)`** — instantiate the model. On the
first call, if the model is not in the HuggingFace cache, it
downloads ~458 MB of weights and tokeniser into
`~/.cache/huggingface/hub/`. On every subsequent call (within and
across pipeline runs) it loads from cache in seconds. Lesson 04
covers what is in the cache directory.

**`model.encode(texts, batch_size=64, normalize_embeddings=True,
show_progress_bar=True)`** — the actual work. `texts` is a list of
6,669 strings (the rows of `model_text` that survived the
`len(text) >= 8` filter). `batch_size=64` controls how many
sentences are pushed through the GPU/CPU at once; smaller is gentler
on memory, larger is faster. `show_progress_bar=True` prints a
tqdm bar to stderr. The interesting argument is the third one.

**`normalize_embeddings=True`** — divide every output vector by its
L2 norm before returning. Each row of the result is a unit vector,
length exactly 1.0 (well, exactly 1.0 to float32 precision).

The geometric consequence is the small but important identity:

```
cosine(u, v) == dot(u, v)        when ‖u‖ = ‖v‖ = 1
```

So later code can use cheap matrix multiplications anywhere a cosine
similarity is wanted. And **Euclidean distance becomes a monotonic
function of cosine distance** on the unit sphere — which means
HDBSCAN with `metric="euclidean"` and KMeans (also Euclidean by
construction) both behave like cosine clusterers without any code
changes. You normalise once, at the embedding boundary, and every
downstream consumer benefits.

You will see the same idiom in the second embedding call,
[scripts/build_user_wants_taxonomy.py:218-225](../../scripts/build_user_wants_taxonomy.py):

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
embeddings = model.encode(
    texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True
)
return np.asarray(embeddings, dtype=np.float32)
```

Same model, same `normalize_embeddings=True`. Different batch size and
no progress bar — this is the second pass over the LLM-extracted
want-strings, only ~250 of them, fast enough that the bar would be
distracting.

**`np.asarray(arr, dtype=np.float32)`** — cast to float32. Embedding
models compute internally in float32 anyway, so the cast is exact.
Float32 halves the memory footprint compared to the float64 default
that NumPy would use for unspecified-dtype arrays. With 6,669 rows
and 384 dimensions, the difference is 10.2 MB vs 20.5 MB on disk.
For 100k tickets, the difference is 150 MB vs 300 MB; for 1M
tickets, 1.5 GB vs 3 GB. Always cast to float32.

**`np.save(cache, arr)`** — write the array to disk in NumPy's `.npy`
format. This is a single binary file containing a small header (dtype
and shape) followed by the raw float32 bytes. It is faster to load
than a CSV by an order of magnitude, smaller than pickle, portable
across NumPy versions, and only stores the array — not arbitrary
Python objects. For a numeric matrix with no metadata, `.npy` is
exactly the right tool.

## Why the cache file is non-negotiable

The first time you run `option2_pipeline.py --embedding-backend local`,
encoding 6,669 tickets on a 2024 MacBook Pro CPU takes ~30 seconds.
On an Apple Silicon GPU (`mps` backend), ~10 seconds. On a server
GPU, ~3 seconds. None of these are catastrophic, but they are not
free either.

Now imagine you tweaked `cluster_texts` — moved the `min_dist`
parameter on UMAP, changed an HDBSCAN setting — and want to re-run.
Without the cache, you re-pay the embedding cost on every iteration.
**With** the cache, the function returns in under a second:

```python
if cache.exists():
    return np.load(cache), None, f"local-cache:{model_name}"
```

The `local-cache:` prefix in the return label is what flows through to
the `nlp_backend` column in the output CSVs, so you can tell from the
artefacts whether a given run hit the cache or recomputed.

The cache key is the **backend name**, not the model name or any
content hash. If you ever change the embedding model (say, swap MiniLM
for a larger model), you must delete the cache file by hand —
otherwise the file will silently contain stale embeddings under the
new model's name. The trade-off is simplicity: the cache key is one
string, and the user is expected to manage cache invalidation by
deleting the run directory.

For the OpenAI branch ([scripts/option2_pipeline.py:1198-1212](../../scripts/option2_pipeline.py))
the same `np.save(cache, arr)` line writes the result. So a switch
from `--embedding-backend local` to `--embedding-backend openai`
also produces a file at `embeddings_openai.npy` — separate cache,
different filename, no collision.

## Try it

```python
import numpy as np
import pandas as pd

run_dir = "outputs/option2_20260502_150055"
emb = np.load(f"{run_dir}/embeddings_local.npy")
print("shape:", emb.shape)               # (6669, 384)
print("dtype:", emb.dtype)                # float32
print("first row norm:", np.linalg.norm(emb[0]))   # ~1.0

# Cosine similarity by hand for two random rows.
i, j = 0, 1
cos = float(np.dot(emb[i], emb[j]))
print(f"cosine(row {i}, row {j}) = {cos:.4f}")

# Find the 5 nearest neighbours of ticket 0.
sims = emb @ emb[0]
top = np.argsort(-sims)[:6]
docs = pd.read_csv(f"{run_dir}/semantic_cluster_assignments.csv")
print("\nNearest neighbours of row 0:")
for idx in top:
    print(f"  cos={sims[idx]:.3f}  cluster={docs.iloc[idx]['cluster_id']}  "
          f"{docs.iloc[idx]['model_text'][:80]}")
```

You should see five tickets in the same cluster as row 0, with cosine
similarities in the 0.7–0.95 range, and the texts they retrieve will
be obvious paraphrases — possibly across languages. That is the
whole demonstration: a single dot product, no n-grams, no language
detection, no machine translation, just `embeddings @ embeddings.T`,
and the output is "tickets that mean roughly the same thing".

The next lesson explains why the specific model that produced these
vectors — `paraphrase-multilingual-MiniLM-L12-v2` — is the right
default, and what the cost trade-offs look like against an OpenAI
embedding endpoint.
