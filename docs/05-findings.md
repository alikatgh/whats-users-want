# 05 — Findings (Presentation-Ready)

Four findings, each with the supporting numbers and where to point if challenged.

---

## Finding 1 — The dominant want is "ban removal AND an explanation," not just "ban removal"

**Claim.** Across the 250 rich tickets we LLM-extracted, two of the top five user wants are about *understanding punishment*, not just reversing it.

**Evidence (from [user_wants_taxonomy.csv](../outputs/option2_20260502_150055/user_wants_taxonomy.csv)):**

| # | Want | Size | Share | Top job |
|---|---|---|---|---|
| 1 | access_account_recover_unban_regain_unblocked | 29 | 11.6% | recover_access |
| 2 | understand_reasons_punishment_recover_access_appeal | 23 | 9.2% | understand_punishment + recover_access |
| 3 | group_access_channel_recover_content_restore | 18 | 7.2% | recover_access |
| 4 | account_access_recover_unblocked_blocks_reasons | 18 | 7.2% | recover_access |
| 5 | understand_punishment_account_reason_notifications_want | 17 | 6.8% | understand_punishment |

**Why it matters.** This is a product-transparency gap, not a support-volume gap. Tickets like "I want to understand the reason for my block" cannot be solved by adding more support agents. They are solved by clearer ban notifications and a self-serve appeals view.

**One-line takeaway.** *Users do not just want to be unbanned — they want to know why.*

---

## Finding 2 — Diamond/dealer transaction disputes are the sharpest money + trust + urgency cluster

**Claim.** Among the 17 discovered wants, `diamonds_scam_avoid_transactions_transaction_money` has the highest combined risk profile.

**Evidence:**

| Risk dimension | Score | Population avg |
|---|---|---|
| Money risk | 4.08 / 5 | 1.46 |
| Trust risk | 3.92 / 5 | 3.40 |
| Urgency | 3.92 / 5 | 3.66 |
| Cluster size | 12 tickets | — |
| Top emotion | angry | anxious |

Combined with the adjacent `fraud_scam_avoid_investigate_fraudulent_activity` cluster (n=12, money 3.75) and `diamonds_access_recover_money_wants_black` (n=14, money 2.86), the **money + trust risk theme is 38 tickets / 15.2% of rich tickets**.

**Why it matters.** These tickets carry real financial risk for users *and* legal/reputational risk for the platform. They should not be in the same queue as voice-room ban appeals.

**One-line takeaway.** *Diamond/dealer disputes deserve a dedicated escalation lane with verified-transaction tooling.*

---

## Finding 3 — "Protect community" tickets are angry, not anxious

**Claim.** Most user-want clusters are dominated by `anxious` users (recovery wants). Three clusters are dominated by `angry` users — and they are all **community-protection** wants where the user is *reporting someone else*, not asking for their own access back.

**Evidence:**

| Want | Top emotion | Anger share | What user is asking for |
|---|---|---|---|
| scam_avoid_fraudulent_activity_detection_prevent | angry (15/17) | 88% | "Block this scammer" |
| community_protect_abusive_behavior_reporting_content | angry (12/16) | 75% | "Remove abusive user" |
| community_protect_reporting_behavior_action_dealer | angry (6/8) | 75% | "Protect dealers from harassment" |

**Why it matters.** The default support response (apologize, investigate, get back to user) is wrong for this class. The user is not anxious about their account — they are angry that the platform has not already acted on a clear violation. The right response is fast acknowledgement of action taken, not reassurance.

**One-line takeaway.** *Recovery tickets need empathy. Reporting tickets need speed.*

---

## Finding 4 — Long, detailed tickets are evidence, not noise

**Claim.** One manager (Albert) writes notes 2-3× richer than peers, and after statistical controls, his evidence advantage is real.

**Evidence (from [manager_context_residuals.csv](../outputs/option2_20260502_150055/manager_context_residuals.csv) and the adjusted manager model):**

| Manager | Raw context score | Expected from ticket mix | Residual (delta) |
|---|---|---|---|
| **Albert** | **25.29** | 16.41 | **+8.89** |
| Alexander, Aziz | 13.15 | 11.95 | +1.20 |
| Danila | 13.91 | 15.31 | -1.39 |
| Leonid | 11.19 | 14.55 | -3.36 |
| Aziz, Alexander | 12.68 | 16.41 | -3.72 |
| Alexander | 9.40 | 15.29 | -5.89 |
| Aziz | 9.29 | 15.31 | -6.02 |
| Firuz | 9.72 | 17.28 | -7.56 |

The "expected" column is what the manager's score *would* be if they handled an average ticket mix. The residual is the manager's individual evidence behaviour after stripping out ticket-mix differences. Albert's +8.89 is statistically significant (p < 0.05 in the adjusted model).

**Why it matters.** Detailed tickets carry the raw material — screenshots, room IDs, ban reasons, user quotes — that everything downstream depends on:
- the LLM extraction step works on rich tickets (we sampled 250 from the top of the context-score distribution);
- the user-wants taxonomy needs the LLM extraction;
- escalation playbooks need the evidence elements.

Treating long notes as "messy noise" would have killed half the analysis.

**Important nuance — not a productivity claim.** The context-value model in Stage 3 shows context depth has a small positive but *not* statistically significant correlation with resolution. So we do **not** claim "richer notes close tickets faster." We claim "richer notes make tickets *understandable* — they are the input to every downstream analysis."

**One-line takeaway.** *Albert's notes are the dataset's most valuable rows. The reward system should reflect that.*

---

## Numbers worth memorizing for Q&A

- 6,728 tickets analyzed; 2,422 unique users
- Date range 2025-06-09 → 2026-05-02
- 53 BERTopic semantic topics + 26 outlier sub-themes
- 17-want taxonomy from 250 LLM-extracted rich tickets
- 0 paid API calls — Gemma 3:4B running locally via Ollama
- 248/250 valid extractions (2 auto-flagged invalid_job)
- Albert's adjusted context residual: +8.89; next-best: -1.39
- Highest-risk cluster: diamonds/dealer disputes — money 4.08, trust 3.92, urgency 3.92
