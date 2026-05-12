# 01 — Tokens and TF-IDF

## The problem

You finished Module 02 with a column called `model_text`. Each row is a
support ticket as the user wrote it, with URLs replaced by the literal
token `[URL]` and stray whitespace squashed. Six and a half thousand of
them, in English, Russian, Spanish, Portuguese, Tagalog, and a fair amount
of romanized Chinese.

A clustering algorithm cannot read that. K-means computes Euclidean
distances. HDBSCAN computes density estimates. Both need vectors of
numbers. So the first job of any text pipeline is the same: turn each
document into a vector that **preserves topical meaning** while being
**cheap to compute**.

The cheapest approach that still works is older than you. It is called
TF-IDF — term frequency times inverse document frequency. It dates from
the 1970s, ships with scikit-learn out of the box, and is the right tool
when (a) your corpus is small enough to fit in memory and (b) you do not
need to capture word order or paraphrase. We use it as the fallback
embedding backend in `cluster_texts`, and we use it again as a labelling
tool no matter which embedding backend was chosen — to give every cluster
a human-readable name like `svip, games, game, points, fisher` instead
of `cluster_8`.

This lesson is about the formula, the parameters, and the real numbers
on disk in `outputs/option2_20260502_150055/`.

## What a token actually is

A token is a string of characters the vectorizer agrees to call a word.
The default `TfidfVectorizer` decides this with a regex,
`token_pattern`. The pipeline overrides the default in
[scripts/option2_pipeline.py:1121-1130](../../scripts/option2_pipeline.py):

```python
vectorizer = TfidfVectorizer(
    max_features=max_features,
    min_df=3,
    max_df=0.82,
    ngram_range=(1, 2),
    strip_accents="unicode",
    lowercase=True,
    token_pattern=r"(?u)\b[\w][\w'-]{2,}\b",
    stop_words="english",
)
matrix = vectorizer.fit_transform(texts)
```

Read the regex `(?u)\b[\w][\w'-]{2,}\b` slowly:

- `(?u)` — the legacy Unicode flag. In Python 3 `\w` is already
  Unicode-aware, but the flag advertises the intent.
- `\b` — word boundary. The token cannot start in the middle of another
  word.
- `[\w]` — exactly one word character (letter, digit, or underscore).
- `[\w'-]{2,}` — followed by at least two more word characters,
  apostrophes, or hyphens. Net effect: the token is at least three
  characters long and may contain internal apostrophes (`don't`,
  `can't`) and hyphens (`self-serve`).
- `\b` — closing word boundary.

This regex is doing two jobs at once. It excludes 2-letter noise (English
"of", "to", "is" — most of which are also stop-listed below, but
belt-and-braces) and it excludes pure-digit tokens like `2025`,
`8742839023049`. Bigo support tickets are full of long numeric IDs that
would otherwise carry zero topical signal but plenty of variance. We do
**not** want every UID to land in the vocabulary.

`strip_accents="unicode"` runs every character through Unicode
decomposition and drops the combining accent marks. `é` becomes `e`,
`ñ` becomes `n`. Without this flag, `cómo` and `como` would be different
tokens; this is the single most-broken assumption in any multilingual
text pipeline.

`lowercase=True` is the third normalisation. `Diamonds`, `DIAMONDS`, and
`diamonds` all collapse to `diamonds`.

The four passes — Unicode strip, lowercase, regex tokenize, stop-list — run
in that order. After they finish, a ticket like

```
"Hello, Albert! I want to BUY DIAMONDS. https://example.com Please help."
```

becomes the bag of tokens

```
hello, albert, want, buy, diamonds, [url], please, help
```

— minus the ones that hit the English stop list (`to`, `i`, `please`).

## Term frequency, document frequency, IDF

You have a token list per document. Now turn it into a vector.

For a token `t` and a document `d`:

- `tf(t, d)` is the count of `t` in `d`. (Some variants use a sublinear
  log; sklearn's default `sublinear_tf=False` keeps the raw count.)
- `df(t)` is the **number of documents** that contain `t` at least once.
- `N` is the total number of documents in the corpus. In our run,
  N = 6,669 (the rows that survived the `len(model_text) >= 8` filter
  in `cluster_texts`).
- `idf(t) = log(N / df(t)) + 1`. Tokens that appear in nearly every
  document have an IDF close to 1. Tokens that appear in one document
  out of N have IDF roughly `log(N) + 1` ≈ 9.8.
- `tfidf(t, d) = tf(t, d) * idf(t)`.

Then sklearn L2-normalises every document vector, so each row of the
final matrix has length 1.

The intuition is simple: a token's weight in a document is high when it
appears **often in that document but rarely elsewhere**. Common
function words — `the`, `and`, `of`, `please` — get crushed by the IDF
factor. Rare-but-distinctive words like `unban` or `svip` dominate
their document's vector.

This is a bag-of-words representation. Order is lost. "Buy diamonds" and
"diamonds buy" produce identical TF-IDF rows. We partly fix that with
bigrams (next lesson). But even without bigrams, the topical signal
survives — the words a ticket uses tell you what the ticket is about.

## Why the parameters matter

The defaults in `make_text_matrix` are tuned for our specific corpus.
Each one solves a problem the dataset throws at you:

```python
TfidfVectorizer(
    max_features=max_features,   # 6000 by default — vocabulary cap
    min_df=3,                    # token must appear in >= 3 docs
    max_df=0.82,                 # token must appear in <= 82% of docs
    ngram_range=(1, 2),          # unigrams + bigrams
    strip_accents="unicode",     # ñ -> n, é -> e
    lowercase=True,              # case-fold
    token_pattern=r"(?u)\b[\w][\w'-]{2,}\b",
    stop_words="english",
)
```

**`max_features=6000`** — keep the 6,000 highest-frequency tokens that
survive the other filters. With 6,669 documents and a typical ticket of
~80 words, the raw vocabulary easily exceeds 30,000 unique tokens. Most
of the tail is junk: misspellings, transliterations, one-off names. A
6,000-term cap is wide enough to capture the meaningful vocabulary and
narrow enough to keep the sparse matrix small.

**`min_df=3`** — every token must appear in at least 3 documents. This
single filter throws away most of the misspellings and unique IDs. A
token that fires in only 1 or 2 tickets cannot generalise to a cluster.

**`max_df=0.82`** — every token must appear in at most 82% of documents.
This catches **domain stop words** that the English stop list does not
know about. In support tickets, words like `hello`, `please`, `help`,
`thanks` appear in nearly every ticket. They are the support-domain
equivalent of `the` and `and`. Without `max_df`, every cluster's top
terms would start with `hello, please, help`.

**`ngram_range=(1, 2)`** — extract both unigrams and bigrams. A bigram
is a pair of adjacent tokens like `buy diamonds` or `unban channel`. We
treat the pair as a single feature with its own column in the TF-IDF
matrix. This catches idioms and named entities that unigrams miss.
Cluster 6 in our run shows the payoff explicitly: its top terms are

```
diamonds, buy, buy diamonds, url, sell, yellow, sent, money, sell diamonds, gift
```

Note `buy diamonds` and `sell diamonds` as their own features, not just
the unigram `diamonds`. The bigrams disambiguate "what about diamonds?"
into "users want to buy them" vs "users want to sell them".

**`stop_words="english"`** — drop the standard English stop list (`a`,
`the`, `of`, `and`, ~318 tokens total). This helps the dominant English
subset of the corpus and does nothing for non-English content. The
trade-off and its workaround are the subject of [Lesson 02](02-stopwords-and-ngrams.md).

## c-TF-IDF, informally

Once you have a TF-IDF matrix and a vector of cluster labels, you can
ask: which words distinguish each cluster?

The pipeline answers this by treating each cluster as one "super-document".
[scripts/option2_pipeline.py:1382-1394](../../scripts/option2_pipeline.py)
walks every cluster, takes the **mean** of its members' TF-IDF rows,
and picks the columns with the highest mean values:

```python
if used_backend == "tfidf":
    topic_terms = []
    labels_series = pd.Series(labels, index=work.index)
    for cluster_id in sorted(pd.Series(labels).unique()):
        idx = np.where(labels == cluster_id)[0]
        if len(idx) == 0:
            continue
        mean_tfidf = np.asarray(features[idx].mean(axis=0)).ravel()
        top_idx = mean_tfidf.argsort()[-12:][::-1]
        terms = [str(feature_terms[i]) for i in top_idx if mean_tfidf[i] > 0]
        topic_terms.append((int(cluster_id), terms))
    terms_by_cluster = dict(topic_terms)
```

This is the c-TF-IDF idea — class-based TF-IDF. BERTopic later
formalises it with a different normalisation (lesson in Module 04). The
intuition stays the same: a token is **distinctive** for a cluster
when its mean TF-IDF inside the cluster beats its mean elsewhere.

The 22 rows of `semantic_clusters.csv` in our run are produced exactly
this way. Pick a few:

| cluster_id | tickets | top_terms (truncated) |
| ---------: | ------: | --- |
| 6  | 484 | `diamonds, buy, buy diamonds, url, sell, yellow, sent, money` |
| 8  | 441 | `svip, games, game, points, fisher, svip points, recharge` |
| 9  | 655 | `channel, create, open channel, create channel, open, limit` |
| 13 | 624 | `account, restore, deleted, number, spam, restore account` |
| 19 | 390 | `unban, user, block, insults, unban user, points, proofs` |

A product manager who has never opened a ticket can read this table
and tell you what each cluster is about. That is the entire point.

## Plain `CountVectorizer` and where it shows up

TF-IDF is not the only sparse text representation in this project. The
BERTopic stage uses plain `CountVectorizer` —
[scripts/bertopic_from_run.py:146-156](../../scripts/bertopic_from_run.py):

```python
from sklearn.feature_extraction.text import CountVectorizer

vectorizer = CountVectorizer(
    lowercase=True,
    stop_words="english",
    ngram_range=(1, 2),
    min_df=3,
    max_df=0.85,
    token_pattern=r"(?u)\b[\w][\w'-]{2,}\b",
)
```

Notice what is gone: no `strip_accents`, and the matrix it produces is
**raw counts**, not IDF-weighted floats. Why?

Because BERTopic does the embedding step itself, with the same
sentence-transformers model we will discuss in Lesson 04. The
clustering happens on dense semantic vectors. The `CountVectorizer` is
only used at the **labelling** stage, inside BERTopic's c-TF-IDF
function. BERTopic computes its own IDF-like weighting on top of the
raw counts (with a different denominator — see Module 04). Asking
sklearn to also IDF-weight the counts would double-count the
correction.

The shared parameters tell you which decisions are corpus-wide and which
are stage-specific. `lowercase`, `stop_words`, `ngram_range`, and the
custom `token_pattern` repeat verbatim — those are properties of the
**text**, not of the vectorizer. `min_df`, `max_df`, and the choice
between `Tfidf` and `Count` are properties of the **stage** (clustering
input vs class-label generation).

## Why TF-IDF is still the cheapest semantic baseline

Three things keep TF-IDF in the toolkit even after embeddings exist:

1. **No model, no download.** `from sklearn.feature_extraction.text
   import TfidfVectorizer` runs everywhere Python runs. The local
   embedding model is a 458 MB HuggingFace cache; the OpenAI backend
   needs an API key and a network call.
2. **Interpretable features.** Every column of the TF-IDF matrix has a
   name (a token or a bigram). You can sort, slice, and read the
   top-K words per cluster directly. An embedding column is a learned
   axis with no English meaning.
3. **Linear-time labelling.** Even when the pipeline embeds with
   MiniLM, it falls through to TF-IDF inside `cluster_texts` —
   [scripts/option2_pipeline.py:1396-1406](../../scripts/option2_pipeline.py):

   ```python
   else:
       # Still create labels using TF-IDF over texts inside each embedding cluster.
       tfidf, vec, _ = make_text_matrix(texts, max_features=5000)
       terms = np.asarray(vec.get_feature_names_out())
       terms_by_cluster = {}
       for cluster_id in sorted(pd.Series(labels).unique()):
           idx = np.where(labels == cluster_id)[0]
           if len(idx) == 0:
               continue
           mean_tfidf = np.asarray(tfidf[idx].mean(axis=0)).ravel()
           top_idx = mean_tfidf.argsort()[-12:][::-1]
           terms_by_cluster[int(cluster_id)] = [str(terms[i]) for i in top_idx if mean_tfidf[i] > 0]
   ```

   Embeddings cluster; TF-IDF labels. Both representations earn their
   keep, in different stages.

For a small, homogeneous corpus — a few hundred FAQs, a single product's
release notes — TF-IDF alone is often enough. You only need embeddings
when the corpus is multilingual, paraphrase-heavy, or large enough that
synonyms split clusters that should be one.

## Try it

```python
# Run from the project root.
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

run_dir = "outputs/option2_20260502_150055"
docs = pd.read_csv(f"{run_dir}/semantic_cluster_assignments.csv")
texts = docs["model_text"].fillna("").astype(str).tolist()

vec = TfidfVectorizer(
    max_features=6000,
    min_df=3,
    max_df=0.82,
    ngram_range=(1, 2),
    strip_accents="unicode",
    lowercase=True,
    token_pattern=r"(?u)\b[\w][\w'-]{2,}\b",
    stop_words="english",
)
X = vec.fit_transform(texts)
print("matrix:", X.shape)             # (6669, 6000)
print("nonzeros per doc avg:", X.nnz / X.shape[0])

terms = vec.get_feature_names_out()

# Reproduce the c-TF-IDF labelling for cluster 6.
import numpy as np
mask = (docs["cluster_id"] == 6).to_numpy()
mean = np.asarray(X[mask].mean(axis=0)).ravel()
top = mean.argsort()[-10:][::-1]
print("cluster 6 top terms:")
for i in top:
    print(f"  {terms[i]:30s}  {mean[i]:.4f}")
```

You should see `diamonds`, `buy`, `buy diamonds`, `sell` near the top of
the printout — the same terms that `semantic_clusters.csv` carries in
its `top_terms` column for cluster 6. Now drop `ngram_range=(1, 2)` and
re-run; the bigrams disappear, and the picture loses the buy / sell
distinction. That is what `ngram_range` is for, and where the next
lesson starts.
