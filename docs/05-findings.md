# 05 — Findings (Presentation-Ready)

Four findings, each with the supporting numbers and where to point if challenged.

> **Run basis (updated 2026-05-29).** The "what users want" findings (1–3) now come
> from the **1,348-ticket Mistral Small 3.2 24B run** (`outputs/option2_20260513_030517/`,
> RunPod GPU) — 5.4× the original 250-ticket Gemma sample, with a clean
> **1,348 ok / 0 bad / 0 error** extraction. Finding 4 (manager evidence) is Stage 1
> and run-independent. The BERTopic / outlier / opportunity-backlog layers still live
> only in the original free local run (`option2_20260502_150055/`, Gemma 3:4B) — that
> run used the same `data_2may.csv`. Both runs are valid; they cover different stages.
> See `runpod-mistral-run-state` notes and `docs/engineering/CODE_VERIFICATION.md`.

---

## Finding 1 — The dominant want is "ban removal AND an explanation," not just "ban removal"

**Claim.** Across the 1,348 Mistral-read tickets, recovery/access wants dominate, and *understanding the punishment* is a distinct top want — not a footnote.

**Evidence (from [user_wants_taxonomy.csv](../outputs/option2_20260513_030517/user_wants_taxonomy.csv), 20 wants).** Six recovery/access clusters total ~495 tickets (**~37%** of the sample). The largest wants:

| # | Want (label abbreviated) | n | Share | Dominant job |
|---|---|---|---|---|
| 1 | access_account_recover_appeal_unban | 121 | 9.0% | recover_access |
| 2 | diamonds_sell_scam_recover_avoid | 95 | 7.0% | buy_or_sell_diamonds + avoid_scam |
| 3 | unban_access_recover_request | 93 | 6.9% | recover_access |
| 4 | account_access_recover_restore | 91 | 6.8% | recover_access |
| 5 | protect_community_reporting_harassment | 86 | 6.4% | protect_community |
| 6 | **understand_punishment_reason_appeal** | **74** | **5.5%** | **understand_punishment** |

"Understand why I was punished" is its own 74-ticket want — and the *understand* theme also threads through the SVIP want (n=77; many ask why rewards changed) and the channel-visibility want (n=67; "why was my channel de-listed").

**Why it matters.** Unchanged and *stronger* at 5.4× scale: this is a product-transparency gap, not a support-volume gap. Tickets asking "why was I blocked" are solved by clearer ban notifications and a self-serve appeals view, not by more agents.

**One-line takeaway.** *Users do not just want to be unbanned — they want to know why. Holds at 1,348 tickets.*

---

## Finding 2 — Diamond/dealer disputes are a major repeat-user theme — but the old "money risk 4.08" number does not survive the better model

**Claim (revised).** Diamond/dealer/scam issues remain one of the largest, most repeat-driven themes — but the previously-cited risk scores were inflated by the keyword-based rules path and do **not** reproduce on Mistral.

**What changed.** The original slide cited the diamond cluster at **money 4.08 / trust 3.92 / urgency 3.92 (all ≥3.9)**. On the 1,348-ticket Mistral run, the diamond/scam want (n=95) scores **money 1.61 / trust 2.8 / urgency 3.04**, and money risk sits at **~1.0–1.6 across all 20 wants**. The 4.08 came from the rules formula `money_risk = 1 + 3·has_money` — any ticket mentioning "diamond" scored ~4. Mistral, reading context, classifies most as delivery/tracking issues, not money-at-risk loss.

**Where the recommendation still stands.** The "dedicated transaction/dealer lane" call survives — now grounded in **volume and repeat behavior**, not an inflated score. The longitudinal layer's `money_or_dealer_dispute` archetype covers **339 users / 965 records (14.2% failed/open)** — the second-largest archetype — and the analysis's own recommended action is exactly *"route to a transaction/dealer evidence lane with a proof checklist and decision SLA."*

**One-line takeaway.** *Diamond/dealer disputes deserve a dedicated lane — justified by 339 repeat users, not by a risk score that doesn't reproduce.*

---

## Finding 3 — "Protect community" tickets are angry, not anxious

**Claim.** Holds and strengthens. The community-protection wants — where the user is *reporting someone else* — are angry-dominated.

**Evidence (1,348-ticket run):**

| Want | n | Anger share | What user asks for |
|---|---|---|---|
| protect_community_reporting_harassment | 86 | 60/86 = 70% | "Block this harasser" |
| scam_protect_community_fraud | 84 | 58/84 = 69% | "Block this scammer" |
| community_protect_group_prevent | 73 | 45/73 = 62% | "Remove this disruptive user" |

**Why it matters.** The default support response (apologize, investigate, get back to you) is wrong for this class. The user is not anxious about their own account — they are angry the platform has not already acted. The right response is fast acknowledgement of action taken.

**One-line takeaway.** *Recovery tickets need empathy. Reporting tickets need speed.*

---

## Finding 4 — Long, detailed tickets are evidence, not noise

**Claim.** Unchanged — and run-independent (Stage 1, same `data_2may.csv`). Albert writes the richest notes by a wide margin.

**Evidence (adjusted OLS, [adjusted_manager_context_model.csv](../outputs/option2_20260513_030517/adjusted_manager_context_model.csv)).** Albert is the model baseline; every other manager sits **8.8–16.4 context points below** him after controlling for category, question kind, role, status, and month (R²=0.35):

| Manager | Δ vs Albert | p |
|---|---|---|
| **Albert** | **baseline** | — |
| Alexander, Aziz | −8.78 | 0.81 |
| Leonid | −12.86 | <0.01 |
| Danila | −13.26 | <0.01 |
| Aziz, Alexander | −13.63 | <0.01 |
| Alexander | −14.24 | <0.01 |
| Firuz | −15.27 | <0.01 |
| Aziz | −16.40 | <0.01 |

The original free run reported the same gap the other way round (Albert **+8.89** above the next manager). **Important nuance unchanged:** this is an evidence-quality claim, not a productivity claim — context depth has only a small, *non-significant* correlation with resolution (see `docs/09-limitations.md` §3).

**One-line takeaway.** *Albert's notes are the dataset's most valuable rows — confirmed across both runs.*

---

## Numbers worth memorizing for Q&A

- 6,728 raw tickets → 6,702 analysis-ready; 2,422 unique users; date range 2025-06-09 → 2026-05-02
- **Current want taxonomy: 1,348 Mistral-read tickets → 20 wants** (RunPod GPU, May 2026); clean **1,348 ok / 0 bad / 0 error**
- Original free baseline: 250 Gemma-read tickets → 17 wants; **53 BERTopic topics + 26 outlier sub-themes** (these layers exist only in the May-2 run)
- Albert is the top note-writer by **8.8–16.4 points** over every peer (adjusted OLS; p<0.01 for all but one)
- ⚠️ **Do not cite diamond "money risk 4.08"** — keyword-inflated; drops to ~1.6 on Mistral. Use the **339-user money/dealer archetype** instead.
- Longitudinal layer (May-13 run): **1,233 repeat users** (2+ tickets), **772** (3+); top momentum = group-limit requests **+25.6%**, scammer-reports **57.8% failed/open**
