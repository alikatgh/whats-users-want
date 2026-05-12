# 05 — BERTopic and c-TF-IDF

## The problem

Stage 1 of the pipeline already produces clusters. It runs UMAP on the
384-dim embeddings, HDBSCAN on the 10-dim UMAP output, then labels each
cluster with the top mean-TF-IDF terms across its members. The output
is `semantic_clusters.csv` — 21 clusters plus the `-1` noise bucket.

Cluster 1 in that file has top terms
`dealer, want dealer, want, seller, wanna, wanna seller, dealers, main,
like dealer, main dealer`. Cluster 6 has
`diamonds, buy, buy diamonds, url, sell, yellow`. They are recognisable.
A product manager can read them.

But two complaints come back from review. First, the labels are not
distinctive enough across clusters — common support vocabulary like
"want", "user", "url" creeps into multiple clusters and dilutes the
signal. Second, the cluster IDs are arbitrary integers; "cluster 6"
is not a useful slack message. You want a name.

BERTopic addresses both. It is not a new clustering algorithm — it
uses the same embedding + UMAP + HDBSCAN machinery you have already
seen — but it adds two pieces. A class-based TF-IDF (c-TF-IDF) that
makes labels much more distinctive, and a topic-naming convention that
turns "topic 1" into `1_diamonds_buy_buy diamonds_money`. It also
ships with visualisation helpers and a stable API that downstream
tooling can rely on.

This lesson is what BERTopic does, what c-TF-IDF means, and how the
project uses it as Stage 2 to validate Stage 1.

## BERTopic stitches four ideas

The script docstring at
[scripts/bertopic_from_run.py:52-61](../../scripts/bertopic_from_run.py)
spells out the assembly:

```python
# BERTopic is a topic-modelling pipeline that stitches four ideas together:
# (1) sentence embeddings turn text into dense vectors that capture meaning,
# (2) UMAP squashes those high-dimensional vectors down to a few dimensions
# while preserving neighborhood structure, (3) HDBSCAN groups the squashed
# points into density-based clusters (and a ``-1`` "noise" bucket), and
# (4) c-TF-IDF labels each cluster with the words that distinguish it from
# the others. We hand BERTopic our own pre-cached embeddings via
# ``embedding_model=None`` so this stage is fast and reproducible — no model
# download, no GPU, just clustering plus labelling on top of vectors that
# Stage 1 already paid for.
```

Steps 1, 2, and 3 are exactly what you read in the previous three
lessons. The contribution of BERTopic is mostly step 4, plus the
plumbing that makes the four steps interchangeable. Pass your own
UMAP, your own HDBSCAN, your own vectorizer, and BERTopic will use
them. From [scripts/bertopic_from_run.py:144-178](../../scripts/bertopic_from_run.py):

```python
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
```

Read this carefully. There are no surprises. UMAP with `n_components=8`
and `metric="cosine"` (Lesson 02). HDBSCAN with `metric="euclidean"`
and a `min_cluster_size` sized to corpus needs (Lesson 03). The novel
piece is the `CountVectorizer` — note that it is `CountVectorizer`,
not `TfidfVectorizer`. That is on purpose, and it is the heart of
c-TF-IDF.

`embedding_model=None` is the load-bearing argument. With it, BERTopic
does not download or run any sentence transformer. It expects you to
hand it the embeddings you already cached. `topic_model.fit_transform(docs,
embeddings)` then takes the docs (for vectorising) and the embeddings
(for UMAP+HDBSCAN) as separate inputs.

## Why CountVectorizer, not TfidfVectorizer

Plain TF-IDF computes IDF per-term across documents:
`idf(t) = log(N_docs / df(t))`. A term that appears in many documents
gets a small weight; a term that appears in few gets a big weight.

BERTopic does not want this. It does not even need it, because c-TF-IDF
will compute its own weighting later. What it needs from
`CountVectorizer` is just the raw term-frequency matrix — counts of
every word in every document. The Count step builds the vocabulary;
c-TF-IDF supplies the weighting.

If you handed BERTopic a `TfidfVectorizer`, it would still work — the
counts get re-weighted afterwards anyway — but you would be
double-weighting. The cleaner contract is "give me counts; I will
weight them my way."

Note the vectorizer arguments here are nearly identical to Module 03's
TF-IDF setup: `min_df=3`, `max_df=0.85`, `ngram_range=(1, 2)`,
`stop_words="english"`, the same `token_pattern`. That consistency is
deliberate. The vocabulary BERTopic uses for labelling is roughly the
same vocabulary `make_text_matrix` uses for similarity.

## c-TF-IDF: TF inside the class, IDF across classes

Here is the move that makes BERTopic work. Concatenate every document
inside cluster `c` into one giant document called class `c`. Now run
TF-IDF, but **per class**:

- `tf_class(t, c)` is how often term `t` appears across all documents
  in cluster `c`.
- `idf_class(t)` is `log(avg_class_length / freq_class(t))` — how rare
  term `t` is *across clusters*, not across original documents.

Multiply: `c_tf_idf(t, c) = tf_class(t, c) * idf_class(t)`.

The teaching note inside `bertopic_from_run.py` at
[scripts/bertopic_from_run.py:77-86](../../scripts/bertopic_from_run.py)
says it like this:

```python
# c-TF-IDF (class-based TF-IDF) is the heart of BERTopic's labelling.
# Plain TF-IDF asks "how rare is this word across documents?" — it
# weights term frequency (tf) by inverse document frequency
# ``idf = log(N_docs / df_word)``. c-TF-IDF instead concatenates every
# ticket inside a cluster into one mega-document, then asks "how rare is
# this word across **clusters**?" — i.e.
# ``tf_class * log(avg_class_length / freq_word_across_classes)``. The
# result: words that are common inside this cluster but rare in other
# clusters bubble to the top, so each topic gets a label that genuinely
# distinguishes it.
```

The intuition: in plain TF-IDF, a word like "bank" gets up-weighted
because few documents contain it. But in c-TF-IDF, you ask whether
"bank" is rare *across topics*. If "bank" appears heavily in one
topic about banking and rarely in any other topic, it gets a huge
c-TF-IDF score for that topic. If "user" appears in every topic — as
it does on a customer-support corpus — it gets a tiny score
everywhere, even though it is common inside each individual cluster.

This is the exact failure mode that plain TF-IDF labels suffer from.
Words that are universally common in the domain (`url`, `user`,
`account`, `ban`) get weighted by their global IDF, which is small but
not zero, so they sneak into every cluster's label. c-TF-IDF
explicitly down-weights anything that fails the "distinctive across
clusters" test.

## What the labels look like

The output of BERTopic on our run lives at
[outputs/option2_20260502_150055/bertopic_topics.csv](../../outputs/option2_20260502_150055/bertopic_topics.csv).
The first few rows:

```
Topic,Count,Name,Representation
-1,1331,-1_url_group_imo_screen,"['url', 'group', 'imo', 'screen', ...]"
0,536,0_account_restore_deleted_number,"['account', 'restore', 'deleted', 'number', ...]"
1,481,1_diamonds_buy_buy diamonds_money,"['diamonds', 'buy', 'buy diamonds', 'money', ...]"
2,235,2_scammed_deceived_dealer_rubles,"['scammed', 'deceived', 'dealer', 'rubles', ...]"
```

The `Name` column is the topic ID, an underscore, then the top four
c-TF-IDF terms joined by underscores. That is the BERTopic naming
convention. `1_diamonds_buy_buy diamonds_money` reads as "topic 1, top
words diamonds, buy, buy diamonds, money". The repetition of "buy" and
"buy diamonds" is bigrams ("buy diamonds" survived as one token) — the
`ngram_range=(1, 2)` setting allowed both unigrams and bigrams into
the vocabulary.

Compare to the plain mean-TF-IDF cluster labels in the Stage 1 output
[outputs/option2_20260502_150055/semantic_clusters.csv](../../outputs/option2_20260502_150055/semantic_clusters.csv).
Cluster 6's top terms there are `diamonds, buy, buy diamonds, url,
sell, yellow`. Same idea, similar words — but `url` made the top six
in Stage 1 and got pushed out in Stage 2's c-TF-IDF because `url` is
not distinctive across topics.

That is the c-TF-IDF win, in one comparison. Distinctive vocabulary
bubbles up; universally common vocabulary gets demoted.

## The 53 topics and the 1,381-ticket noise

Read the bertopic metadata at
[outputs/option2_20260502_150055/bertopic_metadata.json](../../outputs/option2_20260502_150055/bertopic_metadata.json):

```json
{
  "docs": 6669,
  "embeddings_shape": [6669, 384],
  "topics": 53,
  "generated_at": "2026-05-02T15:03:15"
}
```

53 topics from 6,669 embedded tickets — counting topic `-1` and the
52 named topics. The `-1` topic has 1,331 docs (slightly different from
Stage 1's 1,381 because BERTopic's HDBSCAN tuning is slightly stricter
with `min_cluster_size=35`). The largest named topic is topic 0 with
536 tickets (account recovery), then topic 1 with 481 (diamond
purchases), then topic 2 with 235 (scams).

Notice the long tail. The output has 54 lines (one header, 53 topics
in the data plus the `-1` noise topic). Most topics have between 35
(the minimum, by construction) and 100 tickets. That is the granularity
BERTopic produces with `min_topic_size=35`: a long tail of small,
well-defined topics that c-TF-IDF labels distinctively.

## fit_transform and visualize_barchart

The integration is clean. From
[scripts/bertopic_from_run.py:179-198](../../scripts/bertopic_from_run.py):

```python
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
```

`fit_transform` returns the topic IDs (one per document) and a
probability matrix (which we discard with `_` because
`calculate_probabilities=False` skipped the expensive computation).

`get_topic_info()` returns a small DataFrame with one row per topic:
`Topic`, `Count`, `Name`, `Representation`, `Representative_Docs`. We
write it out as `bertopic_topics.csv`.

`visualize_barchart(top_n_topics=24)` produces a Plotly figure of the
top words per topic — one bar chart per topic, top-20 c-TF-IDF terms
each. The HTML at `bertopic_barchart.html` is what reviewers actually
look at; it is the single most useful artefact for sanity-checking
the topic model.

`include_plotlyjs="cdn"` keeps the HTML small (~50 KB) by linking
plotly.js from a CDN instead of inlining the 3 MB library.

## How Stage 1 and Stage 2 disagree (and why we run both)

Stage 1's clusters and Stage 2's topics are not the same. They use
slightly different UMAP `n_components` (10 vs 8), slightly different
HDBSCAN `min_cluster_size` (74 vs 35), and Stage 2 has c-TF-IDF
labelling on top. The Stage 1 output is 21 clusters and 1,381 noise.
The Stage 2 output is 53 topics and 1,331 noise.

Why both? Validation. If Stage 2 produced wildly different topics from
Stage 1 — same noise tickets ending up in different "real" clusters,
or the diamond cluster splitting in unrecognisable ways — we would
know one of the two had a configuration bug. Instead, the structure is
recognisably the same with finer granularity in Stage 2 because of the
smaller `min_cluster_size`. That agreement is a sanity check.

The script appends a "BERTopic Validation" section to
`executive_findings.md` at
[scripts/bertopic_from_run.py:208-221](../../scripts/bertopic_from_run.py)
that lists the top 10 Stage 2 topics for the reviewer to compare
against Stage 1 — agreement-by-eyeball, but cheaper than any other
sanity check.

## The recap

- BERTopic stitches four steps: embeddings, UMAP, HDBSCAN, c-TF-IDF.
  The first three you have already seen. The fourth is the
  contribution.
- It uses `CountVectorizer`, not `TfidfVectorizer`. Counts go in;
  c-TF-IDF supplies the weighting itself.
- c-TF-IDF treats each cluster as one mega-document, computes
  per-class TF, and takes IDF *across classes* rather than
  across-documents. The result: distinctive words bubble up, common
  domain vocabulary gets pushed down.
- Topic names like `1_diamonds_buy_buy diamonds_money` are the topic
  ID plus the top c-TF-IDF terms. They are stable, distinctive, and
  ready to paste into a slack message.
- Our run produced 53 named topics plus the `-1` noise topic of
  1,331 tickets. Compare to Stage 1's 21 clusters and 1,381 noise:
  same data, finer granularity.
- `embedding_model=None` lets BERTopic reuse the cached
  Stage 1 embeddings instead of downloading and rerunning the model.
  This stage is fast and reproducible.

## Try it

Reproduce the BERTopic run and inspect the c-TF-IDF effect on a
specific cluster.

```python
import numpy as np
import pandas as pd
from bertopic import BERTopic
from hdbscan import HDBSCAN
from sklearn.feature_extraction.text import CountVectorizer
from umap import UMAP

run = "outputs/option2_20260502_150055"
docs_df = pd.read_csv(f"{run}/semantic_cluster_assignments.csv")
emb = np.load(f"{run}/embeddings_local.npy")
docs = docs_df["model_text"].fillna("").astype(str).tolist()

vec = CountVectorizer(lowercase=True, stop_words="english", ngram_range=(1, 2),
                     min_df=3, max_df=0.85, token_pattern=r"(?u)\b[\w][\w'-]{2,}\b")
um = UMAP(n_neighbors=25, n_components=8, min_dist=0.0, metric="cosine", random_state=42)
hd = HDBSCAN(min_cluster_size=35, min_samples=11, metric="euclidean", prediction_data=False)

model = BERTopic(embedding_model=None, umap_model=um, hdbscan_model=hd,
                 vectorizer_model=vec, calculate_probabilities=False, low_memory=True)
topics, _ = model.fit_transform(docs, emb)
info = model.get_topic_info()
print(info[["Topic", "Count", "Name"]].head(8))
print("noise topic count:", int(info[info["Topic"] == -1]["Count"].iloc[0]))
```

Compare your output to
[outputs/option2_20260502_150055/bertopic_topics.csv](../../outputs/option2_20260502_150055/bertopic_topics.csv).
The exact topic IDs may permute — UMAP and HDBSCAN are stochastic past
their seeds, and a few border tickets shift between topics — but the
top-word signatures should be recognisable.

For the second experiment, compare a Stage 2 topic name to its Stage 1
counterpart. Pick topic 1 from `bertopic_topics.csv`
(`1_diamonds_buy_buy diamonds_money`) and find the Stage 1 cluster
with overlapping top terms in
[outputs/option2_20260502_150055/semantic_clusters.csv](../../outputs/option2_20260502_150055/semantic_clusters.csv).
Look at how `url` survives in the Stage 1 top terms but is pushed out
of the Stage 2 c-TF-IDF top terms. That demotion is the entire point
of c-TF-IDF.

For the third experiment, write each c-TF-IDF score by hand for a
small artificial example: 4 docs, 2 clusters, 6 vocabulary words. You
will see that "bank" with `tf_class=8` in cluster 0 and `tf_class=0`
in cluster 1 gets a c-TF-IDF score around `8 * log(avg_len / 8)`
which is positive, while "user" with `tf_class=4` in both clusters
gets `4 * log(avg_len / 8)` which is much smaller. The math matches
the intuition.
