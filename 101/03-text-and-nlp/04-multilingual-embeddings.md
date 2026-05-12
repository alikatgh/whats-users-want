# 04 — Multilingual embeddings: choosing the model

## The problem

Lesson 03 said "an embedding model takes a string and returns a
vector". There are hundreds of those models. The pipeline picks
exactly one by default, named with a 56-character string:

```
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

That string appears in two places in the codebase. Once in
[scripts/option2_pipeline.py:1219](../../scripts/option2_pipeline.py)
as `model_name`, passed in from a CLI argument that defaults to this
exact value. Once hard-coded in
[scripts/build_user_wants_taxonomy.py:221](../../scripts/build_user_wants_taxonomy.py)
where it embeds the LLM-extracted want-strings.

Every word in the model name is a deliberate choice. This lesson
unpacks them in order — `sentence-transformers`, `paraphrase`,
`multilingual`, `MiniLM`, `L12`, `v2` — and then explains where the
weights live, how big they are, what the actual download log looks
like, and the trade-offs versus the OpenAI embedding endpoint that
the pipeline supports as a third backend.

## `sentence-transformers/`

The first segment is the HuggingFace organisation that publishes the
model. `sentence-transformers` is a Python library and a model family.
The library is what the pipeline imports
([scripts/option2_pipeline.py:1217](../../scripts/option2_pipeline.py)):

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(model_name)
```

Under the hood, `SentenceTransformer` wraps a HuggingFace transformer
model with a **pooling layer** that turns per-token output vectors
into a single sentence vector. Default pooling for this model is
mean-pooling: take the mean over all token vectors, then optionally
normalise. The `1_Pooling/` directory inside the model cache contains
the pooling-layer config — visible in the cache listing:

```
~/.cache/huggingface/hub/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/snapshots/<hash>/
├── 1_Pooling/
├── README.md
├── config.json
├── config_sentence_transformers.json
├── model.safetensors      (the weights — 449 MB)
├── modules.json
├── sentence_bert_config.json
├── special_tokens_map.json
├── tokenizer.json         (~8.7 MB)
└── tokenizer_config.json
```

You do not interact with any of these files directly. The
`SentenceTransformer(...)` constructor reads `modules.json` to
discover the pipeline (transformer + pooling), instantiates each
module, and exposes the combined `model.encode(...)` API.

## `paraphrase-` — what the model was trained for

There are two main training objectives in the sentence-transformers
zoo: **NLI** (natural language inference) and **paraphrase**.

NLI models are trained to detect entailment — does sentence A imply
sentence B? They produce embeddings where logically related sentences
land near each other.

Paraphrase models are trained on pairs of sentences that mean the same
thing — e.g. "I cannot login" and "I'm unable to access my account".
The training objective pushes paraphrases close together in vector
space and pushes unrelated sentences apart.

For our task — clustering customer support tickets where the same
user-want is expressed in many different ways — paraphrase is the
right objective. Two tickets saying "please open my channel" and
"unblock my channel for me" should land near each other regardless of
the exact wording.

The NLI variant would also work, but its objective is subtly different
(directional implication rather than symmetric similarity), and the
clusters it produces tend to be coarser. For clustering, prefer
paraphrase models.

## `multilingual` — the language coverage

The `multilingual` segment of the name signals that this model was
trained on parallel paraphrase data spanning ~50 languages. The
single model handles English, Russian, Spanish, Portuguese, Tagalog,
Indonesian, Vietnamese, Chinese (simplified and traditional), Arabic,
and others. The training pairs explicitly included
**cross-language** pairs, so an English sentence and its Russian
translation produce nearly the same embedding.

This is what lets the support corpus cluster cleanly. The
`semantic_cluster_assignments.csv` rows mix English, Russian, and
Spanish tickets in the same cluster IDs without any language-detection
preprocessing. Compare: a monolingual English model would give
sensible embeddings for English tickets, useless embeddings for
Russian tickets, and mixed-language clusters would fragment.

The trade-off is modelling capacity. A multilingual model spreads its
parameters across many languages. A single-language model with the
same parameter count is typically a few percentage points more
accurate **on its single language**. For English-only corpora, the
monolingual `all-MiniLM-L6-v2` is faster and slightly better. For
this corpus, the multilingual variant wins by default.

## `MiniLM` — small and fast

The base architecture is a transformer encoder. The full-size
predecessor — Multilingual BERT (mBERT) — has ~178M parameters and
produces 768-dimensional vectors. **MiniLM** is a knowledge-distilled
version: a smaller transformer (12 layers, 384-dim hidden state) that
was trained to reproduce mBERT's outputs.

The result is a model with ~118M parameters that runs roughly 2× faster
than the full mBERT and produces 384-dim vectors at 99% of the
clustering quality. For a workload like ours — embed 6,669 tickets,
re-embed when the data updates — that's the right trade.

The size you see on disk:

```bash
$ du -sh ~/.cache/huggingface/hub/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2
458M    .../models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2
```

That 458 MB is dominated by `model.safetensors` (449 MB) and the
tokenizer (~8.7 MB for the SentencePiece vocabulary, which has to
cover ~50 languages and therefore a large character set).

For comparison, the older mBERT base model is ~1.6 GB, and OpenAI's
`text-embedding-3-large` is unspecified but accessed only through the
API — you do not host it. MiniLM is a sweet spot: small enough to ship
in a Docker image, big enough to give clustering-grade embeddings.

## `L12-v2` — twelve layers, second iteration

The `L12` segment is the layer count. Twelve transformer layers stack
above the input embeddings. Each layer is a self-attention block
followed by a feed-forward block. More layers = more representational
capacity, at proportionally more compute.

`v2` is the version tag. The original `paraphrase-multilingual-MiniLM-L12`
shipped in 2020; `v2` shipped in 2021 with improved training data
(more languages, more pairs, better filtering). When you specify a
sentence-transformers model, always use the latest version unless you
are pinning for reproducibility.

There is also `paraphrase-multilingual-mpnet-base-v2` — same training
data, larger architecture (12 layers, 768-dim output, ~278M
parameters). It produces slightly better clusters at roughly 2× the
inference cost. For our corpus, the MiniLM variant is enough; the
larger model would not move the cluster IDs in any meaningful way.

## Why 384 dimensions

The output vector has 384 floats. That number was chosen for a few
reasons:

1. **It matches the transformer's hidden state.** MiniLM has a 384-dim
   internal representation, and the pooling layer just averages
   token-level vectors. There is no separate projection.
2. **It's a power-of-two-friendly size.** 384 = 128 × 3, which works
   well for SIMD operations on modern CPUs and GPUs.
3. **Cosine similarity is roughly as good at 384 as at 768.** For
   clustering and nearest-neighbour search, beyond ~200 dimensions you
   get diminishing returns. The information density per dimension
   drops as you add more.
4. **Storage and memory matter.** With 6,669 rows, 384-dim float32
   embeddings are 10.2 MB on disk
   (`6669 * 384 * 4 = 10,243,584` bytes plus a small NumPy header).
   At 768 dims it would be 20.5 MB. At 1536 dims (OpenAI
   `text-embedding-3-small`'s default), 41 MB. The differences scale
   linearly with corpus size, and at 1M tickets they are not trivial.

## The download flow

The first time you run `option2_pipeline.py --embedding-backend local`
on a fresh machine, the line

```python
model = SentenceTransformer(model_name)
```

triggers a network download. The HuggingFace `transformers` library
prints log lines like:

```
Downloading (…)/config.json: 100% 645/645 [00:00<00:00, 4.22MB/s]
Downloading (…)/model.safetensors: 100% 471M/471M [00:23<00:00, 19.8MB/s]
Downloading (…)/tokenizer.json: 100% 9.08M/9.08M [00:01<00:00, 8.31MB/s]
```

The files land in `~/.cache/huggingface/hub/`, organised by repository
name with a `models--` prefix and `--` substituted for `/`. The
directory structure splits **blobs** (content-addressed by SHA-256)
from **snapshots** (named by Git commit hash, with symlinks to the
blobs). This is the same content-addressable layout `git` uses, and
it lets multiple revisions of the same model coexist without
duplicating data.

The cache is shared across processes and across pipeline runs. Once
the first download completes, every subsequent
`SentenceTransformer(...)` call across every script in the project
loads from local disk in seconds. This is why both
`option2_pipeline.py` and `build_user_wants_taxonomy.py` happily
hard-code or default to the same model name without coordinating —
they share the same cache.

You can override the cache location with the environment variables
`HF_HOME` or `TRANSFORMERS_CACHE`. The default in 2026 is
`~/.cache/huggingface/hub/`. Keep this in mind if you containerise:
mount a volume there to avoid re-downloading on every container
start.

## OpenAI as the alternative — when and why

The pipeline supports a third backend, `openai`
([scripts/option2_pipeline.py:1198-1212](../../scripts/option2_pipeline.py)):

```python
if backend == "openai":
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    from openai import OpenAI

    client = OpenAI()
    vectors: list[list[float]] = []
    batch_size = 256
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = client.embeddings.create(model=model_name, input=batch)
        vectors.extend([item.embedding for item in response.data])
    arr = np.array(vectors, dtype=np.float32)
    np.save(cache, arr)
    return arr, None, f"openai:{model_name}"
```

OpenAI's `text-embedding-3-large` produces 3072-dim vectors that score
slightly higher than MiniLM on most public benchmarks. On a customer
support corpus, the gap is real but small — the clusters look
similar; a few borderline tickets land in different buckets. The
trade-offs:

- **Cost.** ~$0.13 per 1M tokens at the time of writing. Our 6,669
  tickets at ~80 tokens each is ~533k tokens, so a single full
  embedding pass costs about $0.07. Cheap, but per-run cost is
  non-zero, and over hundreds of iterations it adds up.
- **Latency.** Each batch is a network round-trip. Even with
  `batch_size=256` and parallel requests, embedding 6,669 tickets
  takes 30–60 seconds. The local model on a laptop GPU is faster.
- **Privacy.** OpenAI receives the ticket text. If your tickets
  contain PII (UIDs, phone numbers, anything regulated), this may
  fail compliance review.
- **Reproducibility.** OpenAI may change the model behind a name
  without notice. The local MiniLM cache pins the exact bytes.
- **Offline operation.** The local backend works on a plane. The
  OpenAI backend does not.

The pipeline therefore defaults to `local` for day-to-day work. The
`openai` branch is there for the case where you want a one-shot
quality benchmark, not as the default.

There is one feature OpenAI buys you: dimensions. At 3072 dims, the
embeddings preserve subtle semantic distinctions that 384-dim MiniLM
cannot. For a corpus where tickets are short and topical clusters are
broad, this rarely matters. For a corpus of long, nuanced documents
(legal briefs, scientific abstracts, news articles), the larger
embedding may earn its keep.

The TF-IDF backend remains as the third option, free of any model
dependency at all. Three backends, three points on the cost-quality
curve: TF-IDF (cheapest, language-blind), MiniLM (multilingual,
recommended default), OpenAI (highest fidelity, paid).

## Try it

```python
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer

# Confirm the cache is populated; otherwise this triggers a 458 MB download.
cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
target = "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
print("model in cache:", (cache_dir / target).exists())

# Embed three paraphrases in three languages and check pairwise similarities.
model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

sentences = [
    "I cannot login to my account",                # English
    "разблокируйте мне аккаунт",                   # Russian
    "no puedo entrar a mi cuenta",                 # Spanish
    "increase my channel limit please",            # English, different topic
]
emb = model.encode(sentences, normalize_embeddings=True)
print("shape:", emb.shape)   # (4, 384)

# Pairwise cosine similarity (== dot product since rows are unit-length).
sim = emb @ emb.T
import numpy as np
np.set_printoptions(precision=3, suppress=True)
print(sim)
```

The 3×3 sub-matrix for the first three sentences should sit comfortably
above ~0.65 — three paraphrases across three languages, all pulling
toward each other. The fourth sentence ("increase my channel limit
please") will sit lower, around 0.2–0.4, with all three "login"
paraphrases. That matrix is the entire payoff of using this specific
model: 384 numbers per row, no language preprocessing, and the
similarities make sense across the corpus.

The next lesson takes the same `embeddings_local.npy` file and shows
how the pipeline computes cluster centroids and per-row similarities
to find the most representative ticket in each cluster.
