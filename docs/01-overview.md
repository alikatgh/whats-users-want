# 01 — Overview

## What this project is

A data-science pipeline that turns 6,728 raw customer-support tickets — many of them long, multilingual, full of screenshot links and user quotes — into a structured picture of **what users actually want and which of their problems carry real money/trust risk**.

The CSV is `data_2may.csv` in the project root. Date range: 2025-06-09 to 2026-05-02. The platform context is imo: voice rooms, channels, groups, dealers, diamonds (in-app currency), SVIP (status tiers).

## Why we did not just count categories

The starting CSV has columns like Category and Status, but they are:

- **Inconsistent** — values mix English, Russian, and Chinese; many entries are blank or "Done" without explanation.
- **Multi-line per ticket** — long manager notes break naive row counting (the file looks like 15k rows, but is really 6,728 tickets).
- **Anti-rewarding for good notes** — long, detailed tickets (with screenshots, user quotes, room IDs) look like noise to a counting tool, even though they carry the most evidence.

So a "what users want" analysis built on category counts would mostly measure how the labelling form was filled in. We needed something that reads the text.

## What "what users want" means here

Three layers of meaning, in order from cheap to deep:

1. **Literal request** — what the user typed ("unban me", "open my channel").
2. **Job to be done** — what the user is actually trying to accomplish ("recover access", "understand punishment", "avoid scam").
3. **Underlying want / product opportunity** — what the platform should provide so the ticket never has to be filed ("clearer ban explanations", "verified dealer transactions").

Layer 1 is in the CSV already. Layer 2 we extract with a local LLM. Layer 3 we extract too, then cluster across tickets to discover repeated wants.

## The headline finding

The dominant want across rich tickets is **not** "ban removal." It is **"ban removal *and* an explanation."**

- Two of the top five user-want clusters are about *understanding punishment*, not just reversing it.
- 81% of the rich tickets have a dominant emotion of **anxious** or **angry**.
- The single highest-risk cluster (combined money + trust + urgency, all ≥3.9 / 5) is **diamond/dealer transaction disputes**. That should own a dedicated escalation lane.

This reframes the work: it is not a support-volume problem, it is a **product-transparency problem**. A non-trivial share of tickets exist because users cannot self-serve the information they need.

## Two engineering claims this project also makes

These are secondary but worth defending if asked:

1. **Long, detailed tickets are evidence, not noise.** Albert (one of the managers) writes notes 2-3× richer than peers. After controlling for category, question kind, role, status, and month, his average context score is +8.89 above the next manager. Rich notes carry screenshots, room IDs, ban reasons, user quotes, and timestamps — exactly what classifiers and LLMs need.
2. **The whole pipeline is reproducible and free.** No paid APIs were used. Embeddings are local sentence-transformers; LLM extraction runs through local Ollama models. The original run used Gemma 3:4B; new runs can use Mistral Small 3.2. A new run on a new CSV is a single command.

## Where the work lives

- `data_2may.csv` — input.
- `scripts/` — six Python scripts that form the pipeline.
- `outputs/option2_<timestamp>/` — every run drops a self-contained output folder here. The latest is `outputs/option2_20260502_150055/`.
- `docs/` — this folder.
