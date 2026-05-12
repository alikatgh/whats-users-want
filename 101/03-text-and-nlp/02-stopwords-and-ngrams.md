# 02 — Stopwords, n-grams, and SVD

## The problem

Lesson 01 ended with a working TF-IDF matrix and a per-cluster labelling
trick that produces output like

```
cluster 6: diamonds, buy, buy diamonds, url, sell, yellow, sent, money
cluster 8: svip, games, game, points, fisher, svip points, recharge
cluster 9: channel, create, open channel, create channel, open, limit
```

That output is good. It did not happen by accident. Three pieces of the
configuration in `make_text_matrix` are doing most of the work: the
English stop list, the bigram range, and the `max_df=0.82` upper
filter. None of them generalise cleanly.

This lesson digs into those three knobs. By the end you will know what
`stop_words="english"` actually drops, why a hand-curated stopword set
lives a layer up in
[`build_user_wants_taxonomy.py`](../../scripts/build_user_wants_taxonomy.py),
why bigrams matter for "buy diamonds" but cause a different problem
when most of your text is not English, and what the `TruncatedSVD`
step that follows TF-IDF inside `cluster_texts` is doing to the
6,000-column sparse matrix.

## What `stop_words="english"` actually does

When you pass `stop_words="english"` to `TfidfVectorizer`, sklearn loads
a single hard-coded list of 318 English function words and removes any
token that appears in it before fitting. The list lives in
`sklearn/feature_extraction/_stop_words.py`. It contains exactly what
you would guess: `a`, `the`, `of`, `and`, `or`, `but`, `is`, `was`,
`will`, `can`, `please`... wait. `please` is **not** in that list.
Neither is `hello`, `help`, `thanks`, or `dear`.

This is the first sharp edge. The sklearn list is for **generic
English prose** — Wikipedia, news, novels. It is not for a customer
support corpus where every other ticket starts with `Hello, please
help me`. Without further filtering, those words would appear in every
cluster's top-terms and dominate the labels.

The pipeline solves this with `max_df=0.82` in
[scripts/option2_pipeline.py:1124](../../scripts/option2_pipeline.py).
A token that fires in more than 82% of documents is dropped as a
**corpus-specific stop word**. `please`, `hello`, `help`, `dear`,
`hi`, `support` — anything that bleeds into nearly every ticket — gets
filtered out by frequency rather than by name. You do not need to
maintain a list. You just trust that anything in 82%+ of tickets is
boilerplate, not signal.

The second sharp edge is non-English content. Our corpus contains
Russian phrases like `разблокируйте мне аккаунт`, Spanish `por favor`,
Portuguese `obrigado`. None of these are in sklearn's English list. So
either:

1. They survive into the TF-IDF matrix and pollute the vocabulary, or
2. `max_df=0.82` saves us only because they are rare enough in absolute
   terms that they do not hit the 82% ceiling.

In practice (2) is what happens — the corpus is English-dominant —
but you should know this is a workaround, not a feature. For a corpus
that was 50/50 English/Russian, you would want either two separate
TF-IDF passes by language, or you would skip TF-IDF altogether and
go straight to the multilingual embedding model in Lessons 03–04.

## A project-specific stopword list

There is a second stopword list in this project that does **not** live
inside sklearn. It is hand-written, set-typed, and specific to the
ticket corpus.
[scripts/build_user_wants_taxonomy.py:376-384](../../scripts/build_user_wants_taxonomy.py):

```python
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "had", "you", "your", "but", "not", "can", "could", "should",
    "would", "they", "them", "their", "there", "any", "all", "into", "out",
    "user", "users", "ticket", "tickets", "support", "system", "issue", "issues",
    "feature", "process", "provide", "improve", "implement", "create", "ensure",
    "clear", "clarity", "options", "available", "make", "more", "better",
    "ban", "bans", "banned", "block", "blocked", "blocking",
}
```

This is used inside `label_cluster`
([scripts/build_user_wants_taxonomy.py:430-437](../../scripts/build_user_wants_taxonomy.py))
to name each "user wants" cluster from the LLM-extracted want-strings:

```python
tokens: Counter[str] = Counter()
for text in texts:
    for token in re.findall(r"[A-Za-z][A-Za-z\-']{2,}", text.lower()):
        if token in STOPWORDS or len(token) <= 3:
            continue
        tokens[token] += 1
top = [tok for tok, _ in tokens.most_common(top_n)]
return "_".join(top) if top else "misc"
```

Read the docstring above the set
([scripts/build_user_wants_taxonomy.py:352-374](../../scripts/build_user_wants_taxonomy.py))
to see why each layer is there. There are three:

1. **Generic English filler** — `the, and, with, would`. Same words
   sklearn already filters in the TF-IDF stage. Repeated here because
   this code path does not go through `TfidfVectorizer`.
2. **Domain filler** — `user, users, ticket, tickets, support, system,
   issue, issues, feature, process, provide, improve`. Every want-string
   produced by the LLM contains some of these. If you do not strip them,
   every cluster label starts with `user_ticket_support_...`.
3. **Headline-topic filler** — `ban, bans, banned, block, blocked,
   blocking`. This is the most subtle layer. The dataset is so
   dominated by ban-related complaints that `ban` appears in **most**
   want-strings. If you keep it, every cluster label starts with `ban_`,
   and you cannot tell the appeal cluster from the explanation cluster
   from the compensation cluster.

Verify by reading the actual labels in `user_wants_taxonomy.csv` from
our run:

```
access_account_recover_unban_regain_unblocked
understand_reasons_punishment_recover_access_appeal
group_access_channel_recover_content_restore
account_access_recover_unblocked_blocks_reasons
understand_punishment_account_reason_notifications_want
scam_avoid_fraudulent_activity_detection_prevent
voice_room_access_recover_understand_punishment
community_protect_abusive_behavior_reporting_content
```

Every label is distinct. If `ban` and `block` had stayed in the
vocabulary, the first four would have collapsed into the same prefix.

The lesson generalises: **stopword lists are corpus-specific**. Always
look at your top tokens before clustering and remove the ones that say
"this is a customer-support ticket" rather than "this is **what kind**
of customer-support ticket".

## Why `token_pattern` matters more than the stop list

There is a related failure mode that the explicit `token_pattern`
catches. Look at it again:

```python
token_pattern=r"(?u)\b[\w][\w'-]{2,}\b"
```

This regex requires every token to start with a word character (a
letter, digit, or underscore) and contain at least two more characters.
Two consequences:

- Two-letter words like English `to`, `of`, `is`, Russian `и` (a
  one-letter word) never become tokens in the first place, regardless
  of whether they are in any stop list.
- Pure-digit tokens like the 14-digit UID `3023330656874904` are
  technically allowed (digits are word characters), but they almost
  never recur — `min_df=3` then kills them.

The default sklearn token pattern is `(?u)\b\w\w+\b` — two-or-more
word characters. The project's pattern is one character longer and
disallows leading hyphens and apostrophes. The difference is small in
isolation; in a noisy corpus it is the difference between a clean
vocabulary and one full of `'s`, `-d`, `-ly` fragments.

## Bigrams: why "buy diamonds" needs to be one feature

`ngram_range=(1, 2)` tells the vectorizer to extract every contiguous
pair of tokens **in addition to** the unigrams. After tokenization, the
sentence

```
i want to buy diamonds urgently
```

becomes the unigram bag `{want, buy, diamonds, urgently}` (after the
stop list drops `i` and `to`) **plus** the bigram bag
`{want_buy, buy_diamonds, diamonds_urgently}`. Each bigram gets its own
column in the matrix.

You pay for this. The vocabulary roughly doubles or triples — every
bigram is a new feature. `min_df=3` saves you again: most bigrams are
unique (every ticket has a different sentence), so the same filter that
killed misspellings also kills one-off bigrams. After filtering, only
the bigrams that recur survive. Those are exactly the ones you wanted
in the first place: idioms, named entities, and verb-object pairs that
carry meaning beyond their parts.

The cluster top-terms in `semantic_clusters.csv` make the value
visible. A few rows:

| cluster_id | top_terms |
| ---: | --- |
| 6  | `diamonds, buy, buy diamonds, url, sell, yellow, sent, money, sell diamonds, gift` |
| 9  | `channel, create, open channel, create channel, open, limit, increase, unban channel` |
| 11 | `group, unban group, unban, group blocked, blocked, recommendations, block, unblock group` |
| 19 | `unban, user, block, insults, unban user, points, proofs, block user, insulting, ban` |

In cluster 6 the bigrams `buy diamonds` and `sell diamonds` appear
**alongside** the unigrams `diamonds`, `buy`, and `sell`. Each bigram
is a strictly more specific feature — it fires only when both words
are adjacent in the document. A clustering algorithm that sees
`buy_diamonds` activate but not `sell_diamonds` knows the document is
about buying, not selling.

In cluster 19, `unban user` and `block user` are both bigrams. They
encode the **direction** of the request — the user is asking us to
unban someone or to block someone — that the unigram `user` would not
distinguish. This matters for downstream cluster labels.

The price you pay: bigrams are language-bound. `buy diamonds` only
fires for English-speaking users; the Russian equivalent
`купить алмазы` is a different bigram entirely. This is one more
reason embeddings (Lesson 03) outperform TF-IDF on a multilingual
corpus — they collapse the two phrases into nearby vectors without any
explicit n-gram bookkeeping.

## TruncatedSVD: from 6,000 columns to 80

The TF-IDF backend produces a `(6669, 6000)` sparse matrix. That is
~16% sparse density on average — most cells are zero. UMAP can chew
on sparse input but performs much better on a dense, lower-dimensional
projection. So the pipeline reduces with `TruncatedSVD` first.

[scripts/option2_pipeline.py:1335-1339](../../scripts/option2_pipeline.py):

```python
if used_backend == "tfidf":
    n_components = min(80, max(2, features.shape[1] - 1), max(2, features.shape[0] - 1))
    svd = TruncatedSVD(n_components=n_components, random_state=42)
    dense = normalize(svd.fit_transform(features))
    feature_terms = np.asarray(vectorizer.get_feature_names_out())
```

`TruncatedSVD` is the same algorithm as PCA but it does not centre the
data first — which lets it operate directly on a sparse matrix without
densifying it. It finds the 80 directions in the 6,000-dim TF-IDF
space that carry the most variance, then projects every document onto
those 80 directions.

Why 80 components? Two reasons:

1. **Diminishing returns.** TF-IDF on a corpus of ~7K tickets has a
   long tail of low-variance directions; the first 80 components
   typically capture most of the topical structure (75–90% of the
   total variance is a useful rule of thumb to verify with
   `svd.explained_variance_ratio_.sum()`).
2. **It matches what UMAP wants.** UMAP works best on inputs of a few
   tens to a few hundreds of dimensions; 80 sits comfortably in that
   range. Module 04 covers UMAP's parameter choices.

`normalize(svd.fit_transform(features))` L2-normalises every projected
row. This is the same normalisation that `normalize_embeddings=True`
applies to MiniLM output (Lesson 03). With both backends producing
unit-length vectors, the downstream UMAP / HDBSCAN code works
identically regardless of whether you took the TF-IDF path or the
embedding path.

When the embedding backend is `local` or `openai`, the SVD step is
skipped — those backends already produce dense, low-dimensional
vectors. SVD is specifically the **TF-IDF densifier**.

## Why this all matters

The four knobs in this lesson — sklearn's stop list, the
project-specific `STOPWORDS` set, `max_df`, and `ngram_range` — are not
hyperparameters you can tune blindly. Each one encodes a piece of
domain knowledge:

- `stop_words="english"` is the **base layer**. It assumes your text
  is mostly English. If it is not, you need a different list.
- `max_df=0.82` is the **corpus-specific override**. It catches
  domain-specific stopwords that sklearn does not know about, by
  frequency rather than by name. The 0.82 number was tuned for this
  corpus; on a different corpus you would re-tune it.
- The hand-curated `STOPWORDS` set in `build_user_wants_taxonomy.py`
  is the **last-mile filter**. It runs in a code path that does not
  use sklearn at all, on a much smaller text (LLM-generated
  want-strings, not raw tickets), and it includes domain-specific
  drops (`ban`, `block`) that you can only know about by reading the
  data.
- `ngram_range=(1, 2)` is a **representation choice**. It buys you
  word-pair information at the cost of vocabulary size. On a
  multilingual corpus the cost is higher because bigrams do not
  cross languages.

Every one of these is a place where TF-IDF leaks language assumptions
that embeddings (Lesson 03) handle for free. That is the bridge to the
next half of the module.

## Try it

```python
import re
from collections import Counter
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
import pandas as pd

run_dir = "outputs/option2_20260502_150055"
docs = pd.read_csv(f"{run_dir}/semantic_cluster_assignments.csv")

# How many tickets contain "please"? "hello"? "help"?
for word in ["please", "hello", "help", "dear", "thanks"]:
    n = docs["model_text"].str.contains(rf"\b{word}\b", case=False, na=False).sum()
    print(f"{word:10s}  {n:5d} / {len(docs):5d}  ({n / len(docs):.1%})")

# Are any of those in sklearn's English stop list?
print("\nIn sklearn ENGLISH_STOP_WORDS:")
for word in ["please", "hello", "help", "dear", "thanks"]:
    print(f"  {word:10s}  {word in ENGLISH_STOP_WORDS}")

# Now reproduce label_cluster on cluster 8 ('svip') texts.
sub = docs.loc[docs["cluster_id"] == 8, "model_text"].fillna("").tolist()
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "had", "you", "your", "but", "not", "can", "could", "should",
    "would", "they", "them", "their", "there", "any", "all", "into", "out",
    "user", "users", "ticket", "tickets", "support", "system", "issue", "issues",
    "feature", "process", "provide", "improve", "implement", "create", "ensure",
    "clear", "clarity", "options", "available", "make", "more", "better",
    "ban", "bans", "banned", "block", "blocked", "blocking",
}
counter: Counter[str] = Counter()
for text in sub:
    for token in re.findall(r"[A-Za-z][A-Za-z\-']{2,}", text.lower()):
        if token in STOPWORDS or len(token) <= 3:
            continue
        counter[token] += 1
print("\ncluster 8 label tokens:")
for tok, n in counter.most_common(8):
    print(f"  {tok:20s}  {n}")
```

The first table tells you which "polite filler" words bleed into your
data — most of them are **not** in `ENGLISH_STOP_WORDS`, which is
exactly why `max_df=0.82` is doing the heavy lifting. The second
recreates the cluster-labelling logic you would otherwise read out of
`user_wants_taxonomy.csv`. Tweak the `STOPWORDS` set — drop `block`
and `ban` from it — and re-run; you will see those words flood the
top of the list and confirm why the original authors put them in.
