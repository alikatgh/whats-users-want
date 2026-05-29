# Doc Reconciliation — run-state audit

**Audit date:** 2026-05-29 · **Status: RESOLVED 2026-05-29** — the 3 stale files
(README.md, docs/02-pipeline.md, docs/08-running-it.md) were fixed in the same pass.
§3 is now a changelog of what was corrected, not a TODO. Re-open only if a future run
supersedes `option2_20260513_030517`.
**Trigger:** docs straddle two pipeline runs. Grep showed the old 250-ticket / Gemma
framing in 13 docs and the current 1,348 / Mistral framing in 10 — six overlap.
This file is the **scan-first artifact**: read it before re-deriving which numbers
are stale. Re-run the audit only if `git log` shows doc or run changes after the date above.

> **Why this file exists (token savings).** The divergence below took ~5 doc reads +
> metadata extraction to map. Don't repeat that. The canonical numbers and the exact
> stale line list are frozen here. If you're about to grep `docs/` for "250" or "1348",
> stop and read this first.

---

## 1. Canonical numbers — single source of truth

**Current "what users want" run:** `outputs/option2_20260513_030517/` (RunPod GPU, Mistral Small 3.2 24B).
Source of these figures: the run's own metadata JSONs (`run_metadata.json`,
`longitudinal_metadata.json`, `user_wants_projection_metadata.json`) — mirrored in
`static/what_users_want_cdn/data/`. Cross-checked against `docs/05-findings.md`
(migrated 2026-05-29), which is the **gold prose reference**.

| Quantity | Value | Note |
|---|---|---|
| Raw CSV tickets | **6,728** | `rows_in_csv` |
| Dropped as summary rows | 26 | |
| Analysis-ready tickets | **6,702** | `rows_after_cleaning` = `records` = `source_rows` |
| Tickets clustered (Stage 1) | 6,669 | `tickets_clustered` |
| **LLM-confirmed (Mistral-read)** | **1,348** | `llm_confirmed_rows`; quality = 1,348 ok / 0 bad / 0 error |
| Embedding-projected (rest of corpus) | **5,354** | `projected_rows`; 1,348 + 5,354 = 6,702 |
| **Want taxonomy size** | **20 wants** | `wants` / `emerging_wants` (was 17 on the old run) |
| Repeat users (2+ tickets) | **1,233** | `repeat_users` |
| Repeat users (3+ tickets) | 772 | `repeat_users_3_plus` |
| Journey events | 5,512 | `journey_events` |
| Complete months | 2025-06 → 2026-04 (11) | `complete_months` |
| Assignment threshold | 0.4561 | `assignment_threshold` |
| Review-queue rows | 800 | `review_queue_rows` |
| Unique users (whole corpus) | 2,422 | `05-findings.md` L94 |
| Date range | 2025-06-09 → 2026-05-02 | |
| Extraction model | Mistral Small 3.2 24B | local via Ollama, RunPod RTX 4090 ~$0.69/hr |
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` | local sentence-transformers, 384-d |

**Money-risk correction (do not regress this):** the diamond/scam want (n=95) scores
**money 1.61 / trust 2.8 / urgency 3.04** on Mistral. The old slide's **4.08** was a
keyword artifact of the rules formula `money_risk = 1 + 3·has_money` and does **not**
reproduce. Justify the dealer/transaction lane with the **`money_or_dealer_dispute`
archetype: 339 users / 965 records / 14.2% failed-open**, not the score.

**Old run (still valid — but only for its layers):** `outputs/option2_20260502_150055/`
(Gemma 3:4B). It owns the **BERTopic (53 topics), outlier-split (26 sub-themes,
1,381 noise bucket), opportunity-backlog, and DuckDB** layers — these were never
re-run on Mistral. Citing 250-Gemma / 17-wants / 53-topics **is correct** when the text
is explicitly about the 0205 run. It is **stale** when presented as the current want layer.

---

## 2. Per-file verdict

| Doc | Verdict | Action |
|---|---|---|
| `docs/01-overview.md` | ✅ **Accurate** | none — 250/Gemma mentions are deliberate contrast |
| `docs/05-findings.md` | ✅ **Gold reference** | none — migrated 2026-05-29; use as numbers source |
| `docs/10-runpod-gpu-101.md` | ✅ ~Accurate | trivial: L29 "250-ticket extraction" budget example (L167 `--limit 1400` is correct) |
| `README.md` | ✅ **Fixed 2026-05-29** | was stale — see §3 changelog |
| `docs/02-pipeline.md` | ✅ **Fixed 2026-05-29** | was stale — see §3 changelog |
| `docs/08-running-it.md` | ✅ **Fixed 2026-05-29** | was stale — see §3 changelog |

---

## 3. Stale lines to fix (the 3 files that need it)

### `README.md` — describes the project as if Gemma-250 is current
- **L175–180** "Local model notes from the first smoke tests" frames `gemma3:4b` as
  "best local result" and `mistral-small3.2:24b` as "**current recommended local model
  to test next**." Mistral already ran (May 13, 1,348 tickets). → reframe as the run that happened.
- **L187, L207** "After local LLM extraction (mistral… recommended for new runs)" — future tense; it's the current run.
- **L147–162, L226–233** all extraction examples use `--limit 250`. The canonical run used `--limit 1400` → 1,348 confirmed.
- **Missing entirely:** the 1,348/20-want result, the longitudinal layer (1,233 repeat users), and the money-risk correction. README never mentions the current state.

### `docs/02-pipeline.md` — Stage 5–7 numbers are pre-Mistral
- **L3** "The current latest run is `outputs/option2_20260502_150055/`" → for the **want layer** it's `option2_20260513_030517`. (0205 is right only for BERTopic/outlier/DuckDB — say so.)
- **L120** "Picks **250** candidate tickets" → 1,348.
- **L143** "`gemma3:4b` — usable… **This is what the current run uses.**" → Mistral Small 3.2 24B now.
- **L144** "`mistral-small3.2:24b` — recommended next local model to **test**" → already ran.
- **L165** "For 250 tickets, KMeans… gives **17 wants**" → 1,348 → **20 wants**.
- **L176** "`user_wants_taxonomy.csv` — **17 rows**" → 20.
- **L177** "`user_wants_assignments.csv` — **250 rows**" → 1,348.
- *(Stages 1–4 numbers — 53 topics, 1,381 noise, 26 sub-themes — are correct for the 0205 run; just label them as such.)*

### `docs/08-running-it.md` — commands default to the old limit
- **L38 / L42** "Stage 5 — local LLM extraction (**250** rich tickets…)" / `--limit 250` → primary path should be the 1,400-limit run that produced the current state.
- **L128** runtime table "5 (**250** tickets…)" and **L129** "6 | 30 s | **250** short texts" → 1,348.
- *(L115 DuckDB example pointing at `option2_20260502_150055` is correct — that run owns the DuckDB store.)*

> **How 08 was actually fixed:** because 08 is a *laptop* repro guide, the Stage-5 `--limit 250`
> was kept but explicitly relabeled the **laptop smoke path**, with a pointer to the GPU run
> (`--limit 1400` → 1,348, `docs/11-runpod-mistral-runbook.md`). The free `rules`, `ollama_hybrid`,
> and optional `openai` examples (in 08 and README) intentionally keep `--limit 250` — they are
> illustrative/optional, not the canonical run. Only the **primary `ollama` Mistral** path in
> README was bumped to `--limit 1400`.

---

## 4. Grep cheat-sheet (scan-first before any doc edit)

```bash
# stale tokens — each should be the current value UNLESS inside a deliberate "old baseline" callout
grep -rn -- "--limit 250"            docs/ README.md   # → 1,400-limit / 1,348-confirmed path
grep -rn -e "17 wants" -e "17 rows"  docs/             # → 20
grep -rn -e "250 candidate" -e "250 short texts" -e "250 rich tickets" docs/  # → 1,348
grep -rn "to test next\|recommended next local model" docs/ README.md         # → Mistral already ran (May 13)
grep -rn "current latest run is.*0205\|150055.*current"  docs/                # → want layer is 0513
grep -rn "4\.08"                     docs/ README.md   # → corrected to ~1.6; cite 339-user archetype
```

Gold reference for any disputed number: **`docs/05-findings.md` → "Numbers worth memorizing for Q&A."**
