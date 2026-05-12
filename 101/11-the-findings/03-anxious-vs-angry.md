# 03 — Anxious vs angry

## The finding in one sentence

**Recovery tickets are anxious. Reporting tickets are angry. The
default support response template is wrong for the angry ones.**

## What "emotion" is in this dataset

Module 06 (LLMs) covered the extraction step. For every rich ticket,
Gemma 4B was asked to label the user's emotion as one of nine values:
`neutral, confused, anxious, angry, desperate, betrayed, urgent,
hopeful, unknown`.

The pipeline's
[validation step](../../scripts/llm_extract_rich_tickets.py)
rejected any value not in that list. If Gemma wrote
`stressed` instead of `anxious`, the alias map normalised it; if it
wrote something completely off-list, the row was flagged
`bad_output` and excluded from headline counts.

Of the 250 extracted tickets, the breakdown across all clusters:

| Emotion | Count | Share |
|---|---|---|
| anxious | 126 | 50.4% |
| angry | 77 | 30.8% |
| confused | 40 | 16.0% |
| desperate | 4 | 1.6% |
| hopeful | 1 | 0.4% |
| neutral | 1 | 0.4% |
| urgent | 1 | 0.4% |

81% of the rich tickets are either anxious or angry. The split
between those two is the interesting part.

## Where anxiety dominates

Look at the per-cluster `top_emotions` column from Stage 6's output.
For every recovery cluster, anxiety is the dominant emotion:

| Cluster | Top emotions | Dominant |
|---|---|---|
| Account access recovery (29) | anxious 18, confused 8, angry 2 | anxious 62% |
| Understand reasons + appeal (23) | anxious 18, confused 3, angry 2 | anxious 78% |
| Group access recovery (18) | anxious 11, confused 6, hopeful 1 | anxious 61% |
| Repeat-block frustration (18) | anxious 14, angry 3, urgent 1 | anxious 78% |
| Voice room ban (16) | anxious 12, angry 2, desperate 1 | anxious 75% |
| Account ban appeal (14) | anxious 9, confused 2, desperate 2 | anxious 64% |

The user has lost access to something they care about and is asking
for it back. The emotional register is *worried, vulnerable*.

## Where anger dominates

Three clusters are angry-dominant. They have one thing in common: in
each one, the user is *reporting someone else*, not asking for their
own access.

| Cluster | Top emotions | Dominant |
|---|---|---|
| Stop a scammer (17) | angry 15, anxious 2 | angry 88% |
| Remove abusive users (16) | angry 12, anxious 3, desperate 1 | angry 75% |
| Block bullies / dealer harassment (8) | angry 6, anxious 1, confused 1 | angry 75% |

The user has *evidence* (often screenshots and chat URLs) and a
clear ask: "this user is doing X, ban them." They are not anxious.
They are frustrated that the platform hasn't already acted.

## Why the distinction matters operationally

The default support response in many ticket systems is some variant of:

> "Hi <name>, thank you for reaching out. We've received your report and
> our team is investigating. We appreciate your patience."

This works for **anxious** users. They're worried; you're reassuring
them; the path forward is investigation; "we'll get back to you" is
acceptable.

It does not work for **angry** users. They've already done the
investigation work — they have screenshots, timestamps, the offender's
UID. They want acknowledgement that the platform is acting on the
evidence they gave you. "We're investigating" implies they did
something wrong; what they need to hear is "we acted."

A better response for the reporting cluster:

> "Confirming receipt of your report against UID <X>. We've removed
> the user pending review based on the evidence you provided.
> We'll close the loop within 48 hours."

Two tone changes: (1) acknowledgement that *they did the work*, and
(2) a concrete commitment to a deadline.

## Where this finding sits in the data

Walk the page that surfaces it:

```bash
./scripts/run_dashboard.sh
# Open: What users actually want → tab "Want × emotion"
```

The heatmap shows clusters on rows, emotions on columns, ticket counts
in cells, blue intensity matching the count. Three rows are dark in
the *angry* column: scam_avoid, community_protect_abusive,
community_protect_dealer. Every other row is dark in the *anxious*
column.

Reading the heatmap takes about ten seconds. Recognising what it
implies — that one operational template covers both behaviors — is
where the value comes from.

## The supporting numbers

From [05-findings.md](../../docs/05-findings.md) Finding 3:

| Want | Top emotion | Anger share | What the user is asking for |
|---|---|---|---|
| Stop a scammer (cluster 6) | angry (15/17) | 88% | "Block this scammer" |
| Remove abusive users (cluster 8) | angry (12/16) | 75% | "Remove abusive user" |
| Protect dealers from harassment (cluster 15) | angry (6/8) | 75% | "Protect dealers from harassment" |

Three clusters totalling 41 tickets — 16% of the rich extracted set.
At full pipeline scale (extending Stage 5 to 1,000+ extractions), the
expected share is similar. Extrapolating to all 6,728 tickets, on the
order of 1,000+ tickets per year fall in the angry / reporting class
where the default template is the wrong response.

That's the operational impact of the finding.

## Confidence

How robust is this finding? Several checks:

- **Re-running Stage 5** with different LLM models (1b, 4b, hybrid)
  produced similar emotion distributions per cluster. The 4B model
  agreed with the 1B model 73% of the time on emotion; both agreed
  with the rules-based extractor's emotion proxy on the dominant
  category.
- **Hand-spot-checking** 30 random tickets confirmed the emotion
  labels visually. Gemma 4B was generous with `anxious` and
  conservative with `desperate`; angry tickets reading as angry to a
  human read as angry to the model.
- **Sampling bias**: the 250 tickets came from `risk_balanced`
  selection — biased toward evidence-rich, risky tickets. Within that
  bias, the angry/anxious split is real. Whether the *full* inbox has
  the same split is an open question (module 09 of the engineering
  docs flags this as Limitation 1).

## What this lesson taught

Three things that generalise:

1. **Categorical extraction (anxious / angry / ...) lets you cross-tab
   with anything else.** Once Gemma labelled emotion per ticket, every
   downstream view can split by emotion: emotion × cluster, emotion ×
   manager, emotion × topic, emotion × time. That's the power of
   structured extraction (module 06).
2. **Operational implications come from cross-tabs, not from
   individual labels.** "31% of users are angry" is a fact;
   "angry users are concentrated in reporting clusters and need a
   different template" is an actionable finding. The cross-tab is what
   makes the finding actionable.
3. **A heatmap is the right visual for this kind of finding.** Two
   categorical dimensions, one quantity. Reading the heatmap takes
   seconds; reading 17 cluster summary tables takes minutes.

## Try it

Generate the want×emotion crosstab manually:

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)

.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/user_wants_assignments.csv')
ct = pd.crosstab(df['want_label'], df['user_emotion'])
print(ct.to_string())
"
```

You'll see the full crosstab. Look at the rows for `scam_avoid_*`,
`community_protect_abusive_*`, and `community_protect_dealer_*`.
The `angry` column dominates those rows. Every other row peaks at
`anxious`.

The finding is in the data. The pipeline surfaced it. The dashboard
makes it visible. Module 11 lesson 04 covers the highest-risk cluster.
