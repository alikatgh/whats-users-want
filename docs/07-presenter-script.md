# 07 — Presenter Script

A slide-by-slide script for a 15-20 minute presentation. Each section has: what to say, what to show, and what to do if challenged.

---

## Slide 1 — Title

**Say:** "What users actually want, from 6,728 support tickets — without paid AI."

**Show:** Just the title and the one-line headline finding: *"Users do not just want to be unbanned. They want to know why."*

---

## Slide 2 — Why this is hard

**Say:** "The CSV has 6,728 tickets, but the categories and statuses are inconsistent across English, Russian, and Chinese. Half the long detailed tickets look like noise to a counting tool. So 'just count categories' would tell us how the labelling form was filled in, not what users want."

**Show:** A few rows from `data_2may.csv` with messy multilingual content.

**If challenged:** "Yes, we still report category counts (Stage 1 produces them). They are useful as cross-checks, just not as the answer."

---

## Slide 3 — The pipeline in one picture

**Say:** "We built a six-stage pipeline. Stages 1-4 cluster tickets by meaning, in two languages we don't speak. Stage 5 uses a free local LLM through Ollama — Gemma 3:4B in the original run, Mistral Small 3.2 for new tests — to actually *read* the rich tickets. Stage 6 collapses what the LLM extracted into a real taxonomy of user wants."

**Show:** [docs/02-pipeline.md](02-pipeline.md) diagram.

**Talking point:** "Everything ran on the laptop. Zero paid API calls."

---

## Slide 4 — Stage 1-2: semantic clustering

**Say:** "Every ticket gets converted to a 384-number 'meaning vector' using a multilingual sentence-transformer. That lets 'разблокируйте канал' and 'unban my channel' end up next to each other on a 2D map. Then BERTopic labels each cluster with its most distinctive words."

**Show:** [semantic_ticket_map.html](../outputs/option2_20260502_150055/semantic_ticket_map.html) — hover a few clusters live.

**Numbers to drop:** 53 BERTopic topics. Top topics: account-restore, diamonds-buy, scammed-by-dealer, ban-reason-class, voice-room-block, SVIP-points.

---

## Slide 5 — Stage 3: opportunities, not just topics

**Say:** "Topics alone are descriptive. We score each topic on volume, unresolved share, recent growth, money/trust risk, and evidence depth — to get a ranked product/support backlog."

**Show:** [opportunity_backlog.csv](../outputs/option2_20260502_150055/opportunity_backlog.csv) sorted by score, top 10.

**Top items to mention:** diamonds + money journey (62.6), account recovery self-serve (51.1), pornography/abuse escalation (42.8), scam/dealer disputes (39.4).

---

## Slide 6 — Stage 4: rescuing 1,331 "noise" tickets

**Say:** "BERTopic dumps everything it can't confidently cluster into a single noise bucket. With 1,381 tickets in there, that bucket was the largest single group in the dataset. We re-clustered just the noise into 26 sub-themes — and found things like 59 voice/microphone tickets and 104 points/account-number disputes that BERTopic missed."

**Show:** [outlier_subtopic_map.html](../outputs/option2_20260502_150055/outlier_subtopic_map.html).

---

## Slide 7 — Stage 5: the LLM actually reads tickets

**Say:** "Statistics tells us *what topics exist*. To learn *what users want, how they feel, and what is at stake*, we need a model that reads. The current run uses Mistral Small 3.2 24B on a rented GPU through Ollama; the original free run used Gemma 3:4B on a laptop. Either way: no API key, no ticket text leaving the machine."

**Show:** [llm_extraction_prompt.md](../outputs/option2_20260502_150055/llm_extraction_prompt.md) and [llm_extraction_schema.json](../outputs/option2_20260502_150055/llm_extraction_schema.json) briefly.

**Numbers (current Mistral run):** 1,348 rich tickets extracted — 1,348 valid, 0 auto-flagged, 0 errors. (The original free Gemma run did 250: 248 valid, 2 flagged.) No ticket text left the machine.

**If challenged on model size:** "We tested 270M and 1B too — 270M was unusable, 1B over-collapsed jobs. 4B was the smallest that produced consistently usable JSON. See [local_llm_model_comparison.md](../outputs/option2_20260502_150055/local_llm_model_comparison.md)."

---

## Slide 8 — Stage 6: the taxonomy of wants

**Say:** "We re-embedded the LLM-extracted want/job/opportunity fields and clustered them into 20 user wants with zero outliers (the original Gemma run gave 17)."

**Show:** [user_wants_findings.md](../outputs/option2_20260513_030517/user_wants_findings.md), the top section.

---

## Slide 9 — Finding 1: the dominant want is *understanding*, not just access

**Say:** "Recovery/access wants are ~37% of the 1,348 tickets — and 'understand why I was punished' is its own top want (n=74), on top of the understanding thread running through the SVIP and channel-visibility wants. This is not a support-volume problem — it is a product-transparency gap."

**Show:** Top 5 from [docs/05-findings.md](05-findings.md), Finding 1.

**Pause for impact.** Let this land.

---

## Slide 10 — Finding 2: the highest-risk cluster

**Say:** "Diamond/dealer disputes are one of the largest *repeat-user* themes: the money/dealer-dispute archetype spans 339 users and ~965 records — second only to multi-problem power users. They should not share a queue with voice-room appeals; they need a transaction/dealer evidence lane with a proof checklist and a decision SLA."

**Show:** [docs/05-findings.md](05-findings.md), Finding 2.

**If challenged on the old "4.08 money risk" number:** "That came from a keyword-based rules path (`1 + 3·has_money`) and did not survive the better model — Mistral reads context and scores it ~1.6. We now justify the lane by repeat-user volume, not that score."

---

## Slide 11 — Finding 3: angry vs anxious

**Say:** "Recovery tickets are anxious. Reporting tickets are angry. The default support response — apologize, investigate, get back to user — is wrong for angry tickets where the user has already provided evidence and just wants the platform to act."

**Show:** [docs/05-findings.md](05-findings.md), Finding 3 table.

---

## Slide 12 — Finding 4: detailed notes are evidence

**Say:** "One of our managers — Albert — writes notes 2-3× richer than peers. After we statistically control for the kind of work each manager handles, his evidence advantage is +8.89 points over the next-best in the original run — and the larger Mistral run confirms it: every other manager sits 8.8 to 16.4 points below him. P-value below 0.05. This isn't an artifact."

**Show:** [docs/05-findings.md](05-findings.md), Finding 4 table.

**Important nuance to say out loud:** "We do *not* claim this resolves tickets faster. Our regression on resolution is positive but not statistically significant. We claim that detailed notes are the *raw material* every downstream analysis depends on. The LLM extraction needed rich tickets. The taxonomy needed the LLM extraction. Without Albert's notes, half the analysis would have been impossible."

---

## Slide 13 — What's free vs what's paid

**Say:** "Everything here is local and free of paid APIs. Embeddings, clustering, topic modeling, LLM extraction — Gemma ran on a laptop; the bigger Mistral extraction ran on a rented GPU at about \$0.69/hour. No ticket text hit a paid API. Swapping in OpenAI/GPT later is a one-line change; the prompt and schema stay the same."

**Show:** A reminder of the stack: Python + DuckDB + Polars + Pandas + sentence-transformers + UMAP + HDBSCAN + BERTopic + scikit-learn + statsmodels + Ollama (Gemma 3:4B on laptop, Mistral Small 3.2 24B on a rented RunPod GPU).

---

## Slide 14 — What we should do (recommendations)

**Say:** Three concrete actions:

1. **Build a self-serve "why was I banned" view.** Users want the explanation more than they want a faster appeal.
2. **Create a dedicated escalation lane for diamond/dealer disputes.** Different SLA, verified-transaction tooling, separate queue.
3. **Treat Albert's note style as the standard.** Convert his evidence elements into a checklist; coach other managers against it. Per-manager checklists are already in [manager_evidence_coaching.csv](../outputs/option2_20260502_150055/manager_evidence_coaching.csv).

---

## Slide 15 — Limitations

**Say:** "Three honest caveats."

1. **The extraction still skews to evidence-rich tickets.** `risk_balanced` sampling favours high-context, high-stakes tickets, so the taxonomy describes *what high-context tickets are about*. We scaled from 250 to 1,348 (5.4×) on a GPU; a full ~6,702-record census is the remaining step.
2. **Model quality.** The current run uses Mistral Small 3.2 24B — a real upgrade over the original Gemma 3:4B (which over-collapsed to `recover_access`). The 1,348-ticket run was 100% schema-valid. We still haven't hand-verified accuracy at scale, and risk scores are model judgments (diamond "money risk" dropped from 4.08 under rules to ~1.6 under Mistral).
3. **Context-value model is honest.** Rich notes have a small positive but *not* statistically significant correlation with resolution. We do not claim productivity, we claim understandability.

---

## Slide 16 — Q&A primer

If asked "why not just use ChatGPT?" → "No paid-API budget. We ran local models instead — Gemma 3:4B on a laptop, then Mistral Small 3.2 24B on a ~\$0.69/hr rented GPU. The pipeline is structured so swapping in a hosted model is one line."

If asked "is this reproducible?" → "Yes. One command per stage; the GPU path is in `docs/11-runpod-mistral-runbook.md`. Current run: `outputs/option2_20260513_030517/` (Mistral); BERTopic/opportunity layers: `outputs/option2_20260502_150055/` (Gemma)."

If asked "what about Russian/Chinese?" → "The embedding model is multilingual, so clustering works across languages. The LLM prompt accepts any language and emits English."

If asked "is the manager comparison fair?" → "We controlled for category, question kind, role, status, and month with linear fixed effects. Albert's residual is +8.89, p<0.05. The control is not perfect — there are unobserved factors — but it is the right direction."

If asked "what if the LLM hallucinates?" → "Each output is validated against a JSON schema. Bad outputs get a `_quality_flag`. The 1,348-ticket Mistral run was 1,348 ok, 0 flagged, 0 errors (the original 250-ticket Gemma run had 248 ok, 2 flagged). Hand-verifying accuracy at scale is the next step."
