# 02 — The want taxonomy emerged

## What problem does this solve

Lesson 01 set up the question: what do users actually want? This
lesson shows the taxonomy that emerged and walks through how to read
it. The four headline findings ([Module 11 README](README.md))
all reference rows from the table built here.

## The 17-cluster taxonomy

After Stage 5 (Gemma 4B extraction over 250 rich tickets) and Stage 6
(KMeans clustering of the extracted want strings), the pipeline
discovered 17 clusters. The Gemma labels (from
`scripts/label_user_wants.py`) named them:

| # | Tickets | Want cluster (Gemma label) | Top jobs to be done |
|---:|---:|---|---|
| 1 | 29 | Requesting account access restoration assistance | recover_access (28), fix_product_flow (1) |
| 2 | 23 | Requesting ban removal and explanations | understand_punishment (11), recover_access (11) |
| 3 | 18 | Requesting group access restoration assistance | recover_access (9), restore_visibility (6) |
| 4 | 18 | Account recovery and immediate unblocking requests | recover_access (11), other (3) |
| 5 | 17 | Requesting account unblocking and penalties | understand_punishment (14), other (2) |
| 6 | 17 | Preventing scams and protecting users | avoid_scam (12), protect_community (4) |
| 7 | 16 | Requesting assistance with voice room bans | recover_access (8), understand_punishment (6) |
| 8 | 16 | Removing abusive users from platform | protect_community (14), recover_access (2) |
| 9 | 15 | Understanding punishment and wanting to fix | understand_punishment (12), recover_access (1) |
| 10 | 14 | Requesting diamond purchase assistance and returns | recover_access (6), buy_or_sell_diamonds (4) |
| 11 | 14 | Requesting account access and unblocking | recover_access (14) |
| 12 | 12 | Users seeking to block abusive behavior | protect_community (9), other (3) |
| 13 | 12 | Investigating fraud claims and protecting accounts | avoid_scam (11), prove_innocence (1) |
| 14 | 12 | Investigating diamond scams and recovery | avoid_scam (7), recover_access (3) |
| 15 | 8 | Protecting the community from abuse | protect_community (7), other (1) |
| 16 | 5 | Understanding account punishment and block reasons | understand_punishment (3), other (2) |
| 17 | 4 | Checking SVIP status and gift delivery | gain_status (2), buy_or_sell_diamonds (1) |

Total: 250 tickets — the full LLM-extracted set.

## How to group them

Stare at the table for a minute and natural groupings appear. Here's
how the team rolls them up for headline talks:

**Recovery & punishment understanding** (155 tickets, 62%):
clusters 1, 2, 3, 4, 5, 7, 9, 11, 16. Either the user can't get in,
or they got banned and want to know why.

**Community protection / abuse reporting** (53 tickets, 21%):
clusters 6, 8, 12, 15. The user is reporting *someone else* who
should be banned.

**Money & diamond trust risk** (38 tickets, 15%):
clusters 10, 13, 14. Money/diamonds are at stake; the user is either
trying to recover them or report a scam.

**Status / SVIP** (4 tickets, 2%):
cluster 17.

The four-way macro split is what the next two lessons turn into the
specific findings about emotion (lesson 03) and risk (lesson 04).

## How clustering produced this shape

The mechanic from earlier modules:

1. **Extract structured fields** — Gemma reads each rich ticket and
   produces a JSON record with `actual_user_want`, `job_to_be_done`,
   `product_opportunity`, `literal_request`. (Module 06.)
2. **Concatenate the four fields** into a single string per ticket.
   The redundancy makes the embedding more stable. (Module 04 lesson
   04 + the `WANT_TEXT_FIELDS` constant in
   [scripts/build_user_wants_taxonomy.py](../../scripts/build_user_wants_taxonomy.py).)
3. **Embed** with multilingual sentence-transformers. (Module 03.)
4. **Cluster** with HDBSCAN, fall back to KMeans on small datasets.
   For 250 rows HDBSCAN was too sparse, so KMeans with k=17 ran. (Module
   04.)
5. **Label** each cluster with Gemma. The script asks for "3-7 words,
   plain English, sentence case." (Module 06 + `label_user_wants.py`.)

Every step had to work for the taxonomy to emerge. If embeddings had
been monolingual, ticket text in Russian and English wouldn't have
clustered together. If we'd used HDBSCAN's strict mode, we'd have had
124 outliers and 5 wants. If we'd let Gemma name *and classify*, the
labels would drift to whatever phrasing the model favored that day.

The pipeline factored those decisions: clustering = math (deterministic,
reproducible), labelling = LLM (descriptive, friendly). Each step does
the thing it's good at.

## What's robust and what isn't

**Robust:** the macro shape. Recovery + understanding dominates; abuse
reporting is the second-largest theme; money/diamond disputes are
small-but-explosive. Re-running with different sampling strategies,
different LLM models (270m, 1b, 4b), and different cluster counts (k=15
to k=20) all preserve this shape.

**Less robust:** specific cluster boundaries. Cluster 1 (29 tickets,
"requesting account access restoration") and cluster 4 (18 tickets,
"account recovery and immediate unblocking") and cluster 11 (14
tickets, "requesting account access and unblocking") are *very*
similar. KMeans split them based on subtle wording differences in the
extracted want text. With a slightly different seed or k they might
merge.

When presenting this to the team, the headline is the macro split. The
specific 17 clusters are the drill-down for someone investigating a
particular intent. Don't quote the size of cluster 11 as a hard
number; quote the size of "recovery & punishment understanding" as
62%.

## A specific example

Take cluster 13: "Investigating fraud claims and protecting accounts."
Twelve tickets. Click into the dashboard's **What users actually want**
page, drill into this cluster.

Sample ticket text (paraphrased to protect privacy):

> "I was scammed by an official dealer. I sent 20,000 rubles for diamonds
> and they didn't send them. Here is the chat screenshot. Take a look."

The LLM extracted:
- `actual_user_want`: "investigate the fraud claim and recover funds"
- `job_to_be_done`: "avoid_scam"
- `user_emotion`: "angry"
- `money_risk_level`: 4
- `trust_risk_level`: 4

Multiple tickets like this cluster together because their extracted
fields point at the same thing: *I want the platform to investigate
fraud, refund me, and prevent it from happening again.*

That's a different ask than cluster 1 ("recover account access"). Same
"recover" verb, different object: account vs money.

## Try it

Open the dashboard and look at the table:

```bash
./scripts/run_dashboard.sh
# In the sidebar, navigate to "What users actually want"
```

In the page, you'll see:

1. The 17-bar horizontal chart of cluster sizes.
2. The full per-want summary table.
3. Three heatmap tabs: want × emotion, want × money risk, want × manager.
4. A drill-down dropdown — pick any cluster and see the actual tickets
   that landed there.

Pick cluster "Investigating diamond scams and recovery" from the
drill-down. Read the actual ticket texts. Notice that several of them
have similar structure: *"I sent X rubles, the dealer took the money,
they didn't deliver, here's a screenshot."* The cluster discovered a
real, repeating user behavior — not a category label someone typed in.

This is the headline finding's foundation: clusters discovered from
text + LLM extraction reveal user intents that the category column
hides.
