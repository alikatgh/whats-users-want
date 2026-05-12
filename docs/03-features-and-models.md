# 03 — Features and Models

This page explains every technique used and what each one is *for*. Plain language, no math jargon.

## Part A — Features extracted from raw text

These are the "evidence elements" we look for in each ticket. They feed the context score, the manager comparison, and the LLM candidate selection.

| Feature | What it is | Why it matters |
|---|---|---|
| `has_url` | Any http/https link in the note | The manager attached evidence |
| `has_image_url` | Specifically a `pgc.imostatic.com` or imo CDN link | Screenshot of the violation/state |
| `has_timestamp` | A formatted timestamp like `2026-04-26 14:14:08` | Manager wrote down when the event happened |
| `has_room_or_group_id` | A long numeric ID for a room/group | Lets us trace the actual entity |
| `has_long_uid_or_case_id` | A user UID or case ID | Lets us trace the actual user |
| `has_ban_reason_language` | Phrases like "Insults/personal attacks" or "C category" | The actual policy reason was logged |
| `has_user_claim` | The user's quoted statement (e.g., "I did absolutely nothing") | Captures the user's perspective |
| `has_money_terms` | Words like dealer, diamond, recharge, withdraw | Money is at stake |
| `has_status_or_svip_terms` | Words like SVIP, level, points | Status/loyalty is at stake |
| `has_multiline_note` | The note has multiple lines | Manager wrote a structured story, not a one-liner |

These are combined into **`context_depth_score`**. It is roughly a weighted sum where heavier evidence (screenshots, IDs, ban reasons, multiline notes) is worth more than lighter signals.

## Part B — Models and techniques used

### Sentence Transformers (multilingual MiniLM)

**Model:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

**What it does.** Takes any string and returns a 384-number vector. Strings with similar meaning end up with similar vectors, even across languages. So "не могу разблокировать канал", "unban my channel please", and "канал заблокировали без причины" all land near each other.

**Why this one.** It is small enough to run on a laptop, multilingual (covers Russian/English/Chinese plus more), and fast. We have 6,728 tickets × 384 dimensions — about 10 MB of vectors saved as `embeddings_local.npy`.

**Where it shows up.** Stage 1 (clustering all tickets), Stage 4 (re-clustering outliers), Stage 6 (clustering extracted wants).

### UMAP

**What it does.** Compresses 384-dimensional vectors into 2 dimensions for visualization, while trying to preserve which points are near each other.

**Why this one.** It produces clearer cluster maps than t-SNE for support-ticket data, and it is fast.

**Where you see it.** `semantic_ticket_map.html` and `outlier_subtopic_map.html`. These are the interactive maps where each dot is a ticket; nearby dots have similar meanings.

**Important warning.** A 2D map is for exploration, not proof. Two dots being close on the map does not guarantee they are close in the original 384-dim space.

### HDBSCAN

**What it does.** A density-based clusterer. Finds dense neighbourhoods of similar tickets and labels them as clusters; tickets in low-density regions are labelled `-1` (noise).

**Why this one.** Unlike KMeans, HDBSCAN does not force every ticket into a cluster. That is correct for support data, where many tickets are genuinely unique. The trade-off: when the dataset is small or highly varied (e.g., the 250 LLM extractions), HDBSCAN can leave more than half of points as noise.

**Where it shows up.** Stage 1 main clustering, BERTopic in Stage 2, Stage 6 first-pass attempt.

### KMeans (fallback)

**What it does.** Forces every point into one of `k` clusters. Less honest about ambiguity than HDBSCAN, but useful when you must categorize everything.

**When we use it.** Stage 4 (we *want* every outlier ticket to be assigned somewhere) and Stage 6 (HDBSCAN was too sparse on 250 tickets, so KMeans took over with `k=17`).

### BERTopic

**What it does.** A topic-modeling library that combines embeddings + UMAP + HDBSCAN + a vocabulary technique called **c-TF-IDF** to label each cluster with its most distinctive words. Output: human-readable topic names like `1_diamonds_buy_buy diamonds_money`.

**Why this one.** It is the modern equivalent of LDA topic modeling, but works on multilingual messy data without preprocessing tricks.

**Limitation.** It is reproducible but tuning-sensitive. We used default-ish settings; the resulting 53 topics + a 1,381-ticket noise bucket is consistent with what we see in the embeddings directly.

### c-TF-IDF (term scoring inside BERTopic)

**What it does.** Scores each word by how distinctive it is to a topic vs. the rest of the corpus. That is how we get topic names — the top words by c-TF-IDF become the label.

**Why it matters.** If we just listed the most frequent words in each topic, every topic would look like "the user account block ban". c-TF-IDF strips out words that are common everywhere and surfaces the words that are *unusually* frequent in this specific topic.

### Logistic regression with controls

**Used in Stage 3** for the context-value model. The question we ask: *given category, question kind, role, status, and primary desire, does writing richer notes correlate with higher resolution?*

**Result.** `context_depth_score` has a small positive coefficient (+0.153 probability points per unit) but is *not* statistically significant (p=0.24). Translation: rich notes do not reliably make tickets close faster. They make them *understandable* — which is a different value.

### Linear regression with manager fixed effects

**Used in Stage 1** for `adjusted_manager_context_model.csv`. The question: *after accounting for the kind of work each manager handles, how much more or less evidence do they attach?*

**Result.** Albert is the benchmark. Every other manager scores significantly below Albert (p < 0.05) on adjusted context depth. The next-closest is Danila at -1.39, then most peers cluster at -3 to -7.

### Local LLM (Ollama)

**What it is.** A local open-weights model running through Ollama (a CLI that exposes a local HTTP API at `localhost:11434`). The original run used Gemma 3:4B; new tests default to Mistral Small 3.2 24B.

**What it does in this project.** Reads each rich ticket and produces a JSON record matching `llm_extraction_schema.json`. We extract literal request, actual want, job-to-be-done, emotion, four risk scores, evidence present/missing, support next step, product opportunity, manager note quality, and entities (UIDs, room IDs, timestamps, ban reasons, money amounts, counterparties).

**Trade-offs we accepted.**
- Gemma 3:4B was the smallest model that produced consistently usable JSON in our first smoke tests. 1B and 270M failed.
- Smaller models still over-collapse some categories (e.g., defaulting to `recover_access` when in doubt). We mitigate with deterministic fallback in `ollama_hybrid` and with the rule-based extractor for sanity comparison.
- All extraction is local. No data left the machine. No cost.

### Why we did not use a paid API

The user constraint is "no funding for paid APIs." Within that constraint, the pipeline supports any local Ollama model; `mistral-small3.2:24b` is the current recommended new-run default, and the original Gemma outputs remain available for comparison.

## Summary of the data flow

```
raw text  ──(regex features)──> evidence flags + context score
raw text  ──(embeddings)──> 384-dim vectors  ──(UMAP+HDBSCAN)──> semantic clusters
raw text  ──(BERTopic)──> 53 named topics
clusters  ──(stats)──> opportunity backlog, emerging topics, personas
rich tickets  ──(local Ollama model)──> structured JSON records
records  ──(embeddings + KMeans)──> 17-want taxonomy
```
