# 01 — From categories to wants

## What problem does this solve

The raw `data_2may.csv` has a column called `category` (and its Chinese
sibling `分类`) that classifies every ticket: "Consulting info",
"Unblocking & Banning", "Account", "SVIP", "Top-up & Channels", and
so on. A first instinct would be to count tickets per category and
declare the result *what users want*.

That's what most analyses look like. It's also wrong here.

## Why category counts mislead

Three reasons in this dataset:

**1. Categories are a manager-side classification, not a user-side
intent.** A manager who handles a ticket about "I cannot login because
my UID was stolen by a scammer who took 50,000 diamonds" will tag it
with one category, but the user has *three* needs: recover access,
recover money, prove innocence. Counting that ticket once in
"Account" hides two-thirds of the demand.

**2. Categories are coarse.** The "Unblocking & Banning" bucket has
2,575 tickets. Inside that bucket are at least seven different user
wants:
- Get unbanned and don't care why.
- Get unbanned and need to know why so it doesn't happen again.
- Appeal a ban they think was wrong.
- Get a *group* unbanned (a different operational flow than account
  unbanning).
- Get a *voice room* unbanned.
- Report someone *else* who should be banned.
- Understand the ban policy without being banned themselves.

A bar chart of categories puts all seven into one tall bar.

**3. Categories were filled in by colleagues for their own
spreadsheets.** Recall from the pipeline cleanup (module 02) that the
`分类` column literally contained `咨询信息Consulting info` because
colleagues prefixed the Chinese label to the English one. The values
weren't a controlled vocabulary; they were colleagues annotating their
own pivot tables.

So the analysis went a different way.

## What the pipeline did instead

Instead of trusting the category column, the pipeline:

1. **Treated long manager notes as evidence**, not noise. The
   `context_depth_score` rewards tickets that contain screenshots,
   timestamps, room IDs, ban reasons, user quotes — the things that
   make downstream analysis possible. The richest 250 tickets carry
   the most signal.
2. **Embedded every ticket** into a multilingual semantic vector
   (Module 03 lessons 03-04). Now "I cannot login" and "разблокируйте
   мне аккаунт" are close in vector space regardless of which category
   the manager picked.
3. **Clustered in that vector space** to discover *which tickets talk
   about similar things* (Module 04 lessons 03-04). 53 BERTopic
   topics emerged plus a 1,381-ticket noise bucket.
4. **Split the noise bucket** with KMeans into 26 sub-themes (Module
   04 lesson 04). Now the "couldn't classify" rows yielded actionable
   sub-themes like *outlier_13_voice_microphone_voice_room* (59
   tickets).
5. **Asked a local LLM to read the rich tickets** and extract
   structured fields: `actual_user_want`, `job_to_be_done`,
   `user_emotion`, four risk levels, `support_next_step`,
   `product_opportunity` (Module 06).
6. **Re-clustered the LLM-extracted want strings** to discover what
   users *say* they want, not what category was applied (Module 04
   lesson 04 + lesson 06).
7. **Used Gemma to write friendly titles** for each cluster (lesson
   05 of the script tutorial — `scripts/label_user_wants.py`).

The result: a 17-cluster taxonomy where each cluster is *what users
in this cluster are trying to accomplish*, in plain English.

## How that 17-cluster taxonomy compares to categories

| Source | Granularity | What it represents |
|---|---|---|
| `category` column | 9 buckets | Manager-side classification |
| BERTopic topics | 53 + 1 noise | Semantic similarity in raw ticket text |
| User-want clusters | 17 + summaries | What users are trying to accomplish |

For the team, the user-want clusters are the headline. They're the
table showing *"recover access" 11.6%, "understand reasons +
appeal" 9.2%, "channel/group access" 7.2%...* — actionable, specific,
and discovered from the data rather than imposed by a labelling form.

## The code path

If a teammate asks "where did this finding come from", the chain is:

1. [scripts/option2_pipeline.py](../../scripts/option2_pipeline.py) —
   read CSV, drop colleague pivot rows/columns, featurize, embed,
   cluster.
2. [scripts/bertopic_from_run.py](../../scripts/bertopic_from_run.py) —
   53 topics with c-TF-IDF labels.
3. [scripts/split_outlier_bucket.py](../../scripts/split_outlier_bucket.py)
   — break the noise bucket into 26 sub-themes.
4. [scripts/llm_extract_rich_tickets.py](../../scripts/llm_extract_rich_tickets.py)
   — local Gemma extracts structured fields per ticket.
5. [scripts/build_user_wants_taxonomy.py](../../scripts/build_user_wants_taxonomy.py)
   — re-embed and cluster the extracted want strings.
6. [scripts/label_user_wants.py](../../scripts/label_user_wants.py)
   — Gemma writes friendly cluster titles.

Each stage is one script, ~200-1,000 lines, tested in isolation.
Together they convert "the category bar chart everyone keeps
showing" into "what users actually want."

## What the categorical breakdown WOULD have shown

For comparison, here are the raw counts from the cleaned
`enriched_tickets.csv`:

| Category | Tickets | Share |
|---|---|---|
| Consulting info | ~2,300 | 34.3% |
| Unblocking & Banning | ~2,500 | 37.3% |
| Account | ~600 | 9.0% |
| SVIP | ~470 | 7.0% |
| Top-up & Channels | ~370 | 5.5% |
| (others) | ~460 | 6.9% |

Useful at a glance, but: "Consulting info" tells you *nothing* about
what the user wanted. It tells you the manager didn't have a better
bucket to put it in. Same for "Unblocking & Banning" — what *kind* of
unbanning?

The user-want taxonomy answers those questions:

| Want cluster | Tickets in extracted set | Story |
|---|---|---|
| Recover account access | 29 | "open my account" |
| Understand reasons + appeal | 23 | "why was I banned?" |
| Group/channel restore | 18 | "open my group" |
| Repeat-block frustration | 18 | "why does this keep happening?" |
| Demand explanation for ban | 17 | "tell me what I did" |
| Block a scammer | 17 | "this user is a fraud" |
| Voice room ban appeal | 16 | "I didn't say what they say I said" |
| Remove abusive users | 16 | "this user harasses everyone" |
| ...12 more clusters | 96 | various |

The story has changed. Categories said "37% are unbanning issues"; the
LLM-extracted taxonomy said "people overwhelmingly want *explanations*
of bans, not just removal."

## The thing this lesson is really teaching

You can't analyze your way out of bad inputs. If the input column
classifies tickets the way the *operations team* organizes work, no
amount of pivoting that column will produce *user-side* insights. You
have to go to the source: the user's actual words, semantically
clustered, and structured by an LLM.

This is the central design choice of the entire pipeline. Everything
in modules 02-06 of this course is in service of one decision: **don't
trust the category column; learn the wants from the text**.

## Try it

Compare the two:

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)

# The category breakdown
.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/enriched_tickets.csv')
print('CATEGORY BREAKDOWN:')
print(df['category'].value_counts().head(10))
"

# The user-want breakdown
.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('$RUN_DIR/user_wants_taxonomy.csv')
print('USER-WANT BREAKDOWN:')
print(df[['want_label', 'size']].head(10))
"
```

Notice that the first one is generic and the second one is specific.
The first one is what a Google Sheets pivot would produce; the second
is what this pipeline produces. The difference is the rest of the
course.
