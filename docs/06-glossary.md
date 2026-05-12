# 06 — Glossary

Plain-language definitions of every term the audience will hear. If a question lands on one of these, this is the answer.

## Data terms

**Ticket.** One row in the cleaned dataset. Roughly one user complaint or request, with the manager's note attached.

**Rich ticket / forensic ticket.** A ticket whose manager note contains multiple evidence elements (screenshots, room IDs, ban reasons, user quotes). About 10.7% of the dataset.

**Context depth score.** A single number per ticket measuring how much evidence the manager attached. Higher = richer note. Computed from ten boolean flags weighted by importance.

**Evidence element.** One specific kind of evidence: a URL, an image link, a timestamp, a room ID, a UID, a ban reason, a user quote, a money term, a status term, or a multiline note.

## Modeling terms

**Embedding.** A list of 384 numbers that represents the *meaning* of a piece of text. Texts with similar meaning end up with similar lists. This is how "разблокируйте канал" and "unban my channel" get treated as the same concept.

**Sentence Transformer.** The model that produces embeddings. We use a small multilingual one called MiniLM-L12-v2.

**Dimensionality reduction (UMAP).** Squashing 384-number embeddings down to 2 numbers so we can plot them on a map.

**Clustering.** Grouping similar items together. We use HDBSCAN (lets some items stay unclustered) and KMeans (forces every item into a group).

**HDBSCAN noise / outlier bucket.** When HDBSCAN can't confidently assign a ticket to a cluster, it labels it `-1`. With 1,381 such tickets, we re-clustered them on their own (Stage 4) using KMeans to surface 26 sub-themes.

**KMeans.** A simpler clustering algorithm. You tell it how many groups (k); it forces every item into one. Used as fallback when HDBSCAN is too sparse.

**BERTopic.** A library that combines embeddings + UMAP + HDBSCAN + word scoring (c-TF-IDF) to produce *named* topics like `1_diamonds_buy_buy diamonds_money`.

**c-TF-IDF.** The technique that picks distinctive words for each topic name. It rewards words that are unusually frequent inside one topic vs. the rest of the data.

**Logistic regression.** A statistical method that asks "does X correlate with the probability of Y, after controlling for Z?" Used in Stage 3 to ask whether richer notes correlate with higher resolution. (Answer: weak positive, not statistically significant.)

**Linear regression with fixed effects.** Same idea, used to compare managers after accounting for what kinds of tickets they handle.

**p-value.** Probability that a result this big could happen by chance. Below 0.05 = "this is probably real." Albert's manager residual has p < 0.05.

## LLM terms

**Local LLM.** A language model that runs on your own machine. No internet call, no data leak, no per-token cost.

**Ollama.** The local runtime that loads and runs LLMs. Exposes a small HTTP API at `localhost:11434`. Started by `ollama serve`.

**Gemma 3.** A family of open-weights models from Google. We tested 270m, 1B, and 4B sizes. 4B is the smallest that produced consistently usable JSON for ticket extraction.

**Prompt.** The instruction we send to the model with each ticket. See [llm_extraction_prompt.md](../outputs/option2_20260502_150055/llm_extraction_prompt.md).

**Schema.** The exact shape of the JSON we ask the model to return. See [llm_extraction_schema.json](../outputs/option2_20260502_150055/llm_extraction_schema.json).

**Quality flag.** A field we add to each extracted record marking whether the model's output passed validation (`ok`) or had a problem (`invalid_job`, etc.).

## Project-specific terms

**Job to be done.** The goal the user is trying to accomplish, regardless of what they typed. Example: a user types "open my account" — their job is `recover_access`. We use 11 jobs: recover_access, understand_punishment, protect_community, avoid_scam, fix_product_flow, prove_innocence, restore_visibility, buy_or_sell_diamonds, grow_channel, gain_status, other.

**User want.** The deeper desire behind the job. The same job (`recover_access`) can map to different wants ("get unbanned without explanation" vs. "get unbanned and understand why"). We discovered 17 of these.

**Risk levels.** Four 1-5 scores per ticket from the LLM: urgency, trust risk (does this damage user trust in the platform?), money risk (is money at stake?), safety/policy risk (CSAM, harassment, fraud).

**Repeat-user persona.** A behavioural pattern fitted to users with 3+ tickets. Seven personas: creator/channel operator, commerce/scam-risk, repeat-ban-appeal, account-recovery-repeat, SVIP optimizer, multi-problem power user, generic repeat user.

**Opportunity backlog.** A ranked list of what to fix or automate, scored by size × unresolved share × recent lift × risk.

**Emerging topic.** A topic whose volume in the last 30 days is significantly above its baseline. We flag these so the team notices new issues early.

**Outlier subtopic.** A sub-cluster discovered inside the BERTopic noise bucket (Stage 4). 26 of them, e.g. `outlier_13_voice_microphone_voice_room_room_can_t`.
