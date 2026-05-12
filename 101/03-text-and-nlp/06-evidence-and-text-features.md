# 06 — Evidence flags and structured text features

## The problem

Lessons 03–05 showed how to turn a ticket into a 384-dimensional
embedding. That representation captures **topic** beautifully and
**sentiment** roughly. It does not capture **forensic detail**.

Read these two tickets:

> "I cannot login. Help."

> "Hello, my UID is 3008541181245301. I got a 240-hour voice ban
> Category C on 2025-12-13 16:02:40 in channel bg_voice_45a1c. The
> review reason says 'Abuse/Personal Attack, Severe Abuse'. I have
> a medical certificate showing my jaw is wired shut — I physically
> cannot speak. Screenshots: [URL] [URL] [URL]. The system flagged
> recovery sounds as voice violence. Please review."

Both are about account access. Both will land near each other in
embedding space — the topic is identical. But one is a 7-character
shrug. The other is a 480-character forensic report with a UID, a
timestamp, a room ID, a ban category, a counter-narrative, and three
screenshot URLs.

The pipeline cares about the difference. A long, evidence-rich ticket
is something the support team can act on without bothering the user.
A short ticket forces a back-and-forth. So alongside the embedding
representation, the pipeline computes a **structured text-feature
representation** — eleven hand-written regexes, eleven boolean flags,
and a 0–100 `context_depth_score`. That is what this lesson covers.

This is also the bridge to Modules 04 and 06. Module 04 takes the
embedding representation and clusters on it. Module 06 takes the raw
text and asks an LLM to extract a structured `(want, job, emotion,
next_step)` tuple. The evidence flags are the third leg: a cheap,
deterministic feature that tells you **how much information is in
this ticket** before any modelling happens.

## The eleven regexes

The top of `option2_pipeline.py` contains a wall of compiled regexes,
each commented with what it matches and why it was written that way.
Read [scripts/option2_pipeline.py:79-148](../../scripts/option2_pipeline.py)
in full; the highlights:

```python
URL_RE = re.compile(r"https?://\S+", re.I)

IMAGE_RE = re.compile(r"https?://\S+?\.(?:jpg|jpeg|png|webp|gif)(?:\?\S*)?", re.I)

TIMESTAMP_RE = re.compile(r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?\b")

ROOM_ID_RE = re.compile(r"\b(?:bg|sg|cg|voice|room|channel|group)[._:-]?[a-z0-9][a-z0-9._:-]{5,}\b", re.I)

LONG_ID_RE = re.compile(r"\b\d{12,18}\b")

BAN_REASON_RE = re.compile(
    r"\b(?:ban|banned|block|blocked|blacklist|unban|quick unban|insults?|personal attacks?|severe|violation|abuse|scam|fraud|punishment|kick|source|reason)\b",
    re.I,
)

USER_CLAIM_RE = re.compile(
    r"\b(?:i did nothing|did absolutely nothing|without reason|no reason|by mistake|mistake|unfair|wrongly|false|i don't know|dont know|do not understand|why was i|why i was|i was banned|i got blocked|not guilty|didn't do|did not do)\b",
    re.I,
)

MONEY_RE = re.compile(r"\b(?:money|withdraw|withdrawal|salary|cash|payment|pay|payout|diamonds?|beans?|recharge|top.?up|seller|dealer|reseller|host salary|income|earn)\b", re.I)
```

Each regex has a clear job:

- **Forensic artefacts** (`URL_RE`, `IMAGE_RE`, `TIMESTAMP_RE`,
  `ROOM_ID_RE`, `LONG_ID_RE`) — pieces of evidence the user pasted
  into the ticket. URLs to screenshots, timestamps of when something
  happened, room IDs of where it happened, UIDs of whom it concerns.
- **Vocabulary signals** (`BAN_REASON_RE`, `USER_CLAIM_RE`,
  `MONEY_RE`, `STATUS_RE`, `ACCOUNT_RE`, ...) — the kind of words a
  ticket uses that indicate **what kind** of ticket it is.

The patterns are intentionally English-leaning, because the team
read several hundred tickets and these are the actual words and
shapes that appeared. A multilingual extension would add cyrillic
and CJK alternations to each pattern; the project punts that to the
LLM-extraction stage in
[scripts/llm_extract_rich_tickets.py](../../scripts/llm_extract_rich_tickets.py)
(Module 06).

## Boolean flags from regex matches

Each regex feeds a boolean flag. Some are derived from `count > 0`,
some from `bool(re.search(...))`. The full list is the
`EVIDENCE_LABELS` at [scripts/option2_pipeline.py:179-190](../../scripts/option2_pipeline.py):

```python
EVIDENCE_LABELS = [
    "has_url",
    "has_image_url",
    "has_timestamp",
    "has_room_or_group_id",
    "has_long_uid_or_case_id",
    "has_ban_reason_language",
    "has_user_claim",
    "has_money_terms",
    "has_status_or_svip_terms",
    "has_multiline_note",
]
```

Ten labels. The flags are computed inside `featurize_tickets`
([scripts/option2_pipeline.py:744-754](../../scripts/option2_pipeline.py)):

```python
out["has_url"] = out["url_count"].gt(0)
out["has_image_url"] = out["image_url_count"].gt(0)
out["has_timestamp"] = out["timestamp_count"].gt(0)
out["has_room_or_group_id"] = out["room_or_group_id_count"].gt(0)
out["has_long_uid_or_case_id"] = out["long_uid_or_case_id_count"].gt(0)
out["has_ban_reason_language"] = q.map(lambda s: bool(BAN_REASON_RE.search(s)))
out["has_user_claim"] = q.map(lambda s: bool(USER_CLAIM_RE.search(s)))
out["has_money_terms"] = q.map(lambda s: bool(MONEY_RE.search(s)))
out["has_status_or_svip_terms"] = q.map(lambda s: bool(STATUS_RE.search(s)))
out["has_multiline_note"] = out["line_count"].ge(3)
```

Note the two patterns. Counts → booleans via `.gt(0)` for the regexes
that the pipeline also wants to count (URLs, images, timestamps —
each may appear multiple times in a ticket). Direct `bool(re.search(...))`
for the vocabulary regexes, where one occurrence is enough to
classify the ticket.

`evidence_element_count` is the sum of the ten booleans
([scripts/option2_pipeline.py:765](../../scripts/option2_pipeline.py)):

```python
out["evidence_element_count"] = out[EVIDENCE_LABELS].sum(axis=1)
```

This produces an integer 0–10 per ticket: "how many kinds of
evidence did this ticket include?". Tickets at 0 are pure shrugs.
Tickets at 6+ are forensic-grade.

## The `context_depth_score` formula

The ten flags compress into a single 0–100 score that everything
downstream sorts and aggregates by.
[scripts/option2_pipeline.py:767-787](../../scripts/option2_pipeline.py):

```python
char_cap = max(float(out["char_count"].quantile(0.95)), 1.0)
line_cap = max(float(out["line_count"].quantile(0.95)), 1.0)
url_cap = max(float(out["url_count"].quantile(0.95)), 1.0)
out["context_depth_score"] = (
    18 * np.minimum(out["char_count"] / char_cap, 1)
    + 10 * np.minimum(out["line_count"] / line_cap, 1)
    + 10 * np.minimum(out["url_count"] / url_cap, 1)
    + 10 * out["has_image_url"].astype(int)
    + 8 * out["has_timestamp"].astype(int)
    + 8 * out["has_room_or_group_id"].astype(int)
    + 8 * out["has_long_uid_or_case_id"].astype(int)
    + 10 * out["has_ban_reason_language"].astype(int)
    + 8 * out["has_user_claim"].astype(int)
    + 5 * out["has_money_terms"].astype(int)
    + 5 * out["has_status_or_svip_terms"].astype(int)
).round(2)
out["context_depth_band"] = pd.cut(
    out["context_depth_score"],
    bins=[-1, 15, 35, 60, 101],
    labels=["thin", "basic", "rich", "forensic"],
).astype(str)
```

Read the formula slowly. It is a **weighted sum**.

The first three terms are continuous, normalised by their 95th
percentile:

```
18 * min(char_count / char_cap, 1)
10 * min(line_count / line_cap, 1)
10 * min(url_count  / url_cap , 1)
```

`np.minimum(x / cap, 1)` clips the ratio to `[0, 1]`. The 95th
percentile cap prevents one outlier ticket — someone pasted 50,000
characters — from saturating the formula and stealing the signal
from average-rich tickets. Anything at or above the 95th percentile
gets the full weight; everything below scales linearly.

The remaining eight terms are boolean (0 or full weight):

```
10 * has_image_url
 8 * has_timestamp
 8 * has_room_or_group_id
 8 * has_long_uid_or_case_id
10 * has_ban_reason_language
 8 * has_user_claim
 5 * has_money_terms
 5 * has_status_or_svip_terms
```

The weights encode the team's investigative priors:

- **18 — chars** is the bulkiest signal. A long ticket is almost
  always a more thorough ticket.
- **10 — image evidence** is gold. A screenshot is the closest thing
  to seeing what the user saw.
- **10 — ban-reason language** signals a moderation case, which is
  the single most common ticket type and warrants a structured
  treatment.
- **8 — timestamp / room ID / long UID** are the three dimensions of
  "where, when, whom". Each one moves a ticket from "I have a
  problem" to "here is the specific incident".
- **5 — money / status terms** signal escalation but are not
  forensic. A ticket can mention "money" without including any
  evidence; the weight reflects that.

Maximum theoretically achievable: `18 + 10 + 10 + 10 + 8 + 8 + 8 + 10
+ 8 + 5 + 5 = 100`. In practice, scores above 80 are rare; the
forensic example at the top of this lesson scores around 75.

`pd.cut` then bins the score into four labelled bands:
`thin` (0–15), `basic` (15–35), `rich` (35–60), `forensic` (60+).
The lower bound is `-1` so a literal 0 score lands in `thin`; the
upper bound is `101` so a hypothetical 100-score ticket lands in
`forensic`.

## What the score actually surfaces

The numbers from our run, aggregated by manager, are in
`manager_context_quality.csv`:

```
manager   tickets  avg_context_score  forensic_share  rich_or_forensic_share
Albert     2247    25.29              0.046           0.299
Danila     1441    13.91              0.001           0.017
Leonid      116    11.19              0.000           0.017
Alexander   381     9.40              0.000           0.005
Aziz       2518     9.29              0.000           0.008
Firuz        20     9.72              0.000           0.000
```

Albert's tickets average 25.29; Aziz's average 9.29. That is a 2.7×
gap, and the underlying drivers are visible in the per-manager
column shares: Albert's tickets carry a URL 38% of the time and an
image 30% of the time; Aziz's only 2% and 2%.

This is exactly what the `context_depth_score` was designed to make
visible. Without it, the question "is Albert better at documenting?"
would be hand-waved with a few example tickets. With it, you have a
quantitative answer that each weight in the formula is auditable
against. (Module 02 Lesson 03 covered the formula; this lesson is
about why those weights are an NLP feature engineering choice rather
than a pandas trick.)

## Structured evidence vs free-form text

You now have three parallel representations of the same ticket:

1. **Embeddings** (Lesson 03–05). 384 dense floats. Capture topic and
   sentiment. Language-agnostic. Cluster nicely. Cannot tell you
   what specific evidence the ticket includes.
2. **TF-IDF vectors** (Lesson 01–02). 6,000 sparse columns. Capture
   topical vocabulary. Interpretable per-column. Used for cluster
   labelling. Language-bound and noisy.
3. **Evidence flags + score** (this lesson). 11 booleans + 1 float.
   Hand-engineered, explainable, deterministic. Tell you **what is in
   the ticket** rather than what it is about.

Each representation answers a different question. Embeddings answer
"which other tickets is this similar to?". TF-IDF answers "what words
make this cluster distinct?". Evidence flags answer "how much
investigative material did this ticket arrive with?".

The pipeline keeps all three and never tries to collapse them into
one. They feed different dashboards (the dashboard's "Manager
Context Quality" page reads `manager_context_quality.csv`; the
"Semantic Map" page reads `semantic_cluster_assignments.csv`) and
they support different decisions (which manager to coach vs which
issue is emerging).

The trade-off is maintenance. The eleven regexes are corpus-specific.
Adding a new evidence type means writing a new regex, adding a new
boolean column, choosing a weight, and making sure no downstream
report assumes the old column count. The taxonomy in
`build_user_wants_taxonomy.py` punts most of this to an LLM — see
Module 06 — at the cost of replacing deterministic regex matching
with stochastic LLM extraction.

## Bridge to the next modules

You now have the full text-side picture for Module 03:

- Embeddings (cheap multilingual, dense, semantic).
- TF-IDF (cheap-to-cheaper sparse, interpretable, language-bound).
- Evidence regexes + score (deterministic, structured, hand-tuned).

The next module, Module 04, takes the embeddings produced here and
runs them through UMAP and HDBSCAN. It also formalises the
**c-TF-IDF** labelling step you saw informally in Lesson 01 — the
BERTopic version with its own normalisation. Module 06 covers the
fourth representation: ask an LLM (`gemma3:4b` via Ollama in our
run, or OpenAI / Anthropic via API) to extract structured tuples
from the same `model_text` column, and then **re-cluster** those
extractions using the same multilingual MiniLM embeddings you saw
here. The pipeline is the same; the inputs are an LLM's
abstractions of the tickets, not the tickets themselves.

## Try it

```python
import re
import numpy as np
import pandas as pd

run_dir = "outputs/option2_20260502_150055"
docs = pd.read_csv(f"{run_dir}/enriched_tickets.csv")

# Drop ten worst-scoring tickets and ten best to see the score in action.
print("Lowest 5 context_depth_score (band: thin):")
for _, r in docs.nsmallest(5, "context_depth_score").iterrows():
    print(f"  score={r['context_depth_score']:.1f}  band={r['context_depth_band']:8s}  {r['question'][:80]}")

print("\nHighest 5 context_depth_score (band: forensic):")
for _, r in docs.nlargest(5, "context_depth_score").iterrows():
    print(f"  score={r['context_depth_score']:.1f}  band={r['context_depth_band']:8s}  {r['question'][:80]}")

# Run the BAN_REASON_RE on a sample manually.
BAN_REASON_RE = re.compile(
    r"\b(?:ban|banned|block|blocked|blacklist|unban|quick unban|insults?|personal attacks?|severe|violation|abuse|scam|fraud|punishment|kick|source|reason)\b",
    re.I,
)
sample = "I was banned without reason. Please review my case."
print(f"\nMatches in sample: {BAN_REASON_RE.findall(sample)}")

# Cross-tab: how does context_depth_band distribute by manager?
print("\nContext band share by manager:")
ct = pd.crosstab(docs["manager"], docs["context_depth_band"], normalize="index")
print((ct * 100).round(1).fillna(0))
```

You should see the lowest-scoring tickets are short single-line
messages ("Help me", "Open my account", three-word complaints), and
the highest-scoring are the multi-paragraph forensic reports with
URLs, timestamps, and ban reasons. The cross-tab reproduces the
manager-level pattern visible in `manager_context_quality.csv`:
Albert's row has a meaningful `forensic` and `rich` share; Aziz's
row is mostly `thin` and `basic`.

This is the end of Module 03. You now know everything the pipeline
does to text **before** clustering. Module 04 picks up from
`embeddings_local.npy` and shows what UMAP and HDBSCAN do with
it.
