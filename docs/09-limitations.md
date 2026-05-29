# 09 — Limitations and Honest Caveats

Read this before Q&A. Every concern below has a sensible answer and we should not pretend they are not real.

## 1. The extraction sample skews to evidence-rich tickets (now 1,348, not 250)

**The issue.** Stage 5 selects candidates with the `risk_balanced` strategy, which favours evidence-rich, high-risk tickets. So the resulting want-taxonomy describes *what high-context, high-stakes tickets are about*, not the full ticket mix. The current RunPod/Mistral run scaled this from 250 to **1,348** tickets (5.4×), but the same selection bias still applies.

**Why we did it that way.** A local model needs raw evidence to extract anything useful. Feeding it a one-line ticket like "open my account" produces garbage. So we sampled where the model could actually work.

**What this means for the headline finding.** The "ban removal AND explanation" finding is robust within the rich subset and held when we scaled to 1,348 tickets. Whether *all* tickets follow the same pattern is still open; the projection layer (`project_user_wants_full_corpus.py`) maps the remaining records by embedding similarity with confidence bands. A full Mistral census of all ~6,702 useful records is the remaining step.

**Recommended response in Q&A.** *"This taxonomy is calibrated for the rich-evidence tickets that drive escalations. We are not yet generalizing to the full inbox."*

---

## 2. Model quality (Gemma 3:4B → Mistral Small 3.2 24B)

**The issue.** Small 4B models hallucinate, over-collapse categories, and miss subtle distinctions — the original Gemma 3:4B defaulted to `recover_access` in ambiguous cases. The current run upgrades to **Mistral Small 3.2 24B** on a rented GPU, which is materially stronger (the 1,348-ticket run was 100% schema-valid: 0 bad, 0 errors).

**What we did to mitigate.**
- Each output validated against a JSON schema; bad outputs flagged with `_quality_flag`, not silently kept.
- Two safer fallbacks exist: `ollama_hybrid` (combines deterministic rules for hard fields with the model for human-language fields) and pure `rules` (no model at all).
- Three model sizes were tested side-by-side; comparison is in [local_llm_model_comparison.md](../outputs/option2_20260502_150055/local_llm_model_comparison.md).

**What we did NOT do.**
- Human spot-check of the outputs. We have not yet hand-verified extraction quality at scale (now 1,348 rows).
- Calibration of the four risk scores against a ground-truth set. **Note:** risk scores are model-dependent — diamond "money risk" was 4.08 under the keyword rules path and ~1.6 under Mistral. Treat absolute risk scores cautiously.

**Recommended response.** *"We started with Gemma 3:4B locally, then ran Mistral Small 3.2 24B on a cheap rented GPU for the real run — 1,348 tickets, all schema-valid. Swapping in a paid API is still a one-flag change if a budget appears."*

---

## 3. Rich notes do NOT statistically reduce time-to-resolution

**The issue.** The Stage 3 logistic regression of resolution on context depth gives:
- coefficient: +0.153 probability points per unit
- p-value: 0.241
- 95% CI: [-0.103, +0.409]

Translation: rich notes have a small positive correlation with resolution but **the effect is not statistically significant**. We cannot claim that detailed notes close tickets faster.

**What we DO claim.** Rich notes are the raw material every downstream analysis depends on:
- The LLM extraction step needs rich tickets to produce structured records.
- The user-wants taxonomy needs the LLM extraction.
- The risk + emotion + evidence-missing fields all come from notes.

So the value of rich notes is in *understanding*, not in *productivity*.

**Recommended response.** *"We are not making a productivity claim. We are making an evidence-quality claim. The numbers back the second, not the first — and we say so explicitly in the report."*

---

## 4. UMAP 2D maps are for exploration, not proof

**The issue.** The interactive ticket map projects 384 dimensions down to 2. Two dots being close on the map does not guarantee they are close in the original embedding space.

**What we did.** We use UMAP only for visualization. The actual clustering happens in the full 384-dim embedding space (HDBSCAN, BERTopic) or on KMeans of the high-dim vectors. The map is a presentation aid, not the source of truth.

**Recommended response.** *"The map is for intuition. The clusters live in 384 dimensions. Cluster membership is computed there, not on the map."*

---

## 5. We are inferring "what users want" from manager-written notes

**The issue.** The text we analyze is mostly the manager's note, not the user's own message. The manager's framing colors what we extract.

**What we did.** Several extraction fields try to recover the user's voice directly:
- `entities.user_claim` captures quoted user statements.
- `literal_request` captures what the user said.
- The context-depth flag `has_user_claim` is a feature in its own right.

**What we did NOT do.** We did not separately analyze user-only text vs manager-only text. The two are entangled in the source CSV.

**Recommended response.** *"Manager framing is a real source of bias. The pipeline tries to extract user voice where it appears, but the dataset itself does not separate them. A future improvement is to separate the two channels at ingestion."*

---

## 6. The manager comparison controls are imperfect

**The issue.** The Stage 1 adjusted-context model controls for category, question kind, role, status, and month. There are unobserved factors it does not control for: what time of day a manager works, which user segments they handle, whether they are a senior reviewer.

**What we did.** Reported coefficients with p-values and 95% CIs. Albert's residual is +8.89 with p<0.05; the magnitude and direction are robust to reasonable perturbations of the control set.

**What this means.** The conclusion *"Albert writes meaningfully richer notes than peers, on average"* is sound. The conclusion *"Albert is the best manager"* is **not** what we are claiming — note richness is one dimension among many.

**Recommended response.** *"This compares one specific behaviour: how much evidence is attached to a ticket. It is not a holistic manager rating. We are explicit about that scope."*

---

## 7. The category count percentages we cite are approximate

**The issue.** Multilingual category labels were normalized with a coarse mapping. About 5-8% of tickets ended up in catch-all buckets like "consulting" or "unblocking" because their original labels were ambiguous.

**What we did.** Reported the categorical breakdown as a starting point, then moved to embedding-based topics for the actual analysis. Topic-based numbers are not affected by the label-normalization issue.

**Recommended response.** *"The category counts in the first cut are directional. The headline findings come from the embedding and LLM layers, which work directly on the text and are not subject to label normalization."*

---

## 8. The "emerging topics" detector is volatile on small topics

**The issue.** A topic with 4 tickets last month and 8 tickets this month shows a 100% increase. That looks alarming but may be noise.

**What we did.** Reported lift *and* z-score relative to the topic's own baseline volatility. We flag topics with z > 2 as emerging. We do not flag tiny topics.

**Recommended response.** *"Small topics can produce large percentage changes. We use z-scores against each topic's own variance to filter for real shifts."*

---

## What would I want to do next, given infinite time

1. **Done:** scaled LLM extraction from 250 to **1,348** tickets via Mistral Small 3.2 24B on RunPod. **Remaining:** a full census of all ~6,702 useful records (runbook Step 12B).
2. Hand-label 100 random extractions to estimate the model's accuracy per field.
3. Add a second-language validation pass — re-run extraction on the Russian/Chinese-only subset and compare.
4. Build a Streamlit dashboard so the team can filter the taxonomy interactively without running scripts.
5. Wire a weekly cron that re-runs the pipeline on the latest CSV and emails a delta report.
