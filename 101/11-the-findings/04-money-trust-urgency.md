# 04 — Money, trust, urgency

## The finding in one sentence

**The diamond/dealer transaction-dispute cluster has the sharpest
combined risk profile in the entire dataset (money 4.08, trust 3.92,
urgency 3.92 out of 5). It deserves its own escalation lane.**

## How risk gets onto each ticket

In Module 06 (the LLMs lessons) Gemma was asked to score four risk
levels per rich ticket, each on a 1-5 integer scale:

- **`urgency_level`** — how time-pressured the user feels.
- **`trust_risk_level`** — does this damage user trust in the platform.
- **`money_risk_level`** — is money at stake.
- **`safety_policy_risk_level`** — CSAM, harassment, severe abuse.

The pipeline's [validation step](../../scripts/llm_extract_rich_tickets.py)
clamps these to [1, 5] and rejects anything else as `bad_output`. The
rules-based fallback in `call_rules` produces analogous scores
deterministically — see [Module 06 lesson 04](../06-llms-and-prompts/04-validation-and-quality-flags.md)
for the formulas.

For each cluster discovered in Stage 6, the pipeline averages these
scores over the cluster's tickets. The averages are how we find the
highest-risk cluster.

## The risk averages by cluster

Sorted by combined risk (money + trust + urgency) descending. Top six:

| Cluster | n | Money | Trust | Urgency | Combined |
|---|---:|---:|---:|---:|---:|
| Diamond/dealer transaction disputes | 12 | 4.08 | 3.92 | 3.92 | 11.92 |
| Investigate fraud claim | 12 | 3.75 | 3.92 | 3.92 | 11.59 |
| Diamonds: recover money / black-listed | 14 | 2.86 | 3.43 | 3.71 | 10.00 |
| Stop a scammer | 17 | 2.59 | 3.88 | 3.88 | 10.35 |
| Remove abusive users | 16 | 1.12 | 3.75 | 4.00 | 8.87 |
| Voice room ban | 16 | 1.00 | 3.00 | 3.75 | 7.75 |

The top cluster — diamond/dealer transaction disputes — is the only
one where all three axes are above 3.5. Money is the differentiator:
the *diamonds_scam_avoid_transactions_transaction_money* cluster has
twice the average money risk of "remove abusive users" (which has
nothing to do with money).

## Why this cluster is different

A typical ticket in this cluster, paraphrased:

> "Amirsho the dealer sent 20,000 rubles for diamonds and the buyer
> refused to send them. Here is the chat. UID 1117348902837465. He
> blocked me. I want my diamonds or my money back."

Three things make this kind of ticket unusually risky:

1. **Money has actually changed hands.** Unlike a "they harassed me"
   report, the loss is concrete and quantifiable. A refund or
   investigation has direct financial consequences.
2. **Trust in the dealer ecosystem is at stake.** The platform
   advertises "official dealers" — when one cheats a user, the trust
   damage spreads to every other transaction the user might consider.
3. **Time-pressure is real.** Users worry that the offending dealer
   will keep scamming others; they want the account banned NOW. The
   urgency score matches.

Compare to the largest cluster ("recover account access", n=29):

| | Money | Trust | Urgency |
|---|---:|---:|---:|
| Diamond/dealer disputes | 4.08 | 3.92 | 3.92 |
| Account access recovery | 1.24 | 2.72 | 3.38 |

Both are anxious users wanting the platform to fix something. But the
account-recovery user lost *their account*, not *money + trust*.
Different operational SLA, different escalation path, different
investigation depth.

## Why this matters operationally

Three clusters in the "money & trust" macro group total 38 tickets in
the rich-extraction set. Two observations:

1. **38 of 250 = 15.2%** of rich tickets. Extrapolated to the full
   inbox of 6,728 tickets, on the order of 1,000+ tickets per year
   carry real money risk.
2. **They share infrastructure with low-risk reports.** A "this user
   is annoying" complaint and a "this user took my 20,000 rubles" report
   currently flow through the same support queue with the same SLA.
   That is wrong.

The recommendation that emerged: **dedicated escalation lane for
diamond/dealer transaction disputes**, with:

- Faster triage SLA (24 hours, not 72).
- Escalation to a fraud-investigations specialist by default (not
  general support).
- Dedicated tooling: verified dealer status, transaction history
  lookup by UID, freeze-pending-review on the offending account.
- Separate metrics so the cluster's resolution time isn't averaged
  away by the high-volume low-risk tickets.

That's the operational change the finding implies. The pipeline
didn't generate the change directly, but it produced the evidence
that motivated it.

## Where it sits in the dashboard

Open the dashboard, navigate to **Opportunities ranked by impact**. The
*opportunity_score* combines volume, unresolved share, recent lift, and
trust/money risk:

```
score = sqrt(volume) * (1 + 2.2*unresolved + 1.2*min(lift-1, 3) + 1.4*risk)
        + 8 * rich_share + 0.06 * avg_context
```

(See [Module 05 / opportunity_score formula](../05-statistics/04-two-proportion-z-test.md).)

The 1.4× weight on trust/money risk is what makes the diamond/dealer
cluster rise to the top. Without that weight, a high-volume low-risk
cluster would rank above it. The weight is a deliberate editorial
decision: *we believe trust and money are more important than volume*.

The chart on the page shows topic size on X (log-scale), score on Y,
color by trust/money risk. The red bubbles up and to the right are
the high-risk, high-impact opportunities. Diamond/dealer is one of
them.

## The supporting code path

For someone who wants to verify the finding from scratch:

1. [scripts/llm_extract_rich_tickets.py](../../scripts/llm_extract_rich_tickets.py)
   produces per-ticket risk scores.
2. [scripts/build_user_wants_taxonomy.py](../../scripts/build_user_wants_taxonomy.py)
   averages them by cluster in `summarize()`.
3. [outputs/option2_<TS>/user_wants_taxonomy.csv](../../outputs/option2_20260502_150055/user_wants_taxonomy.csv)
   — the per-cluster risk averages live here, columns
   `avg_money_risk`, `avg_trust_risk`, `avg_urgency`,
   `high_money_risk_share`, `high_trust_risk_share`.
4. [scripts/insight_layer.py](../../scripts/insight_layer.py)
   `build_opportunity_backlog` blends those averages into the
   `opportunity_score`.
5. [outputs/option2_<TS>/opportunity_backlog.csv](../../outputs/option2_20260502_150055/opportunity_backlog.csv)
   ranks topics by score; the dashboard's Opportunities page reads
   from here.

Five steps from raw ticket text to "build a fraud-investigations
escalation lane." Every step is auditable.

## Confidence

How sure are we?

- **Within-run consistency**: the same 250 tickets yield the same risk
  averages every time the pipeline reruns (deterministic embedding +
  `temperature=0` Gemma).
- **Cross-model consistency**: comparing Gemma 1b vs 4b risk scores on
  the same tickets (Module 06 lesson 06), the *ranking* of clusters by
  combined risk is identical. The absolute values differ slightly
  (1b is more conservative on money risk).
- **Hand-validation**: spot-checking the 12 tickets in the
  diamond/dealer-disputes cluster confirms each one involves a real
  monetary loss. Gemma's risk scores are plausible.
- **Selection bias**: the cluster is small (n=12) and the
  rich-extraction set was sampled to favour high-risk tickets. The
  *existence* of this cluster is real; its *exact size* depends on
  sampling. Scaling Stage 5 to 1,000+ tickets is the next step
  (module 09 of the engineering docs flags this).

The headline survives every robustness check. The exact n=12 is the
weakest claim; the cluster's existence and risk profile are strong.

## Try it

Generate the per-cluster risk view directly:

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)

.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/user_wants_taxonomy.csv')
df['combined_risk'] = df['avg_money_risk'] + df['avg_trust_risk'] + df['avg_urgency']
top = df.sort_values('combined_risk', ascending=False).head(8)
cols = ['want_label', 'size', 'avg_money_risk', 'avg_trust_risk', 'avg_urgency', 'combined_risk']
print(top[cols].to_string(index=False))
"
```

The first row will be the diamond/dealer disputes cluster with the
combined risk near 12. The next several rows will all be commerce-
or scam-related. The first non-money cluster will be ~3 below the
top.

This is the empirical core of the finding. Reproducing it should take
under a second. Defending it in front of a stakeholder takes the
preceding 4 modules of context — which is why this lesson sits at
the end of the course.
