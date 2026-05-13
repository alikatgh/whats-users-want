# 12 - Management Slide Brief

Use this file as source material for NotebookLM to generate a simple management
deck.

The key framing: **this is a different AI use case from user-facing chat**.
This is an internal decision tool that reads the real support record managers
already maintain and shows management what users repeatedly want, where trust
is breaking, and which operational changes would reduce repeated escalation.

## One-Sentence Positioning

We are not replacing direct support conversations. We are using the real
support document managers already build every day to understand the repeated
user wants behind it, so management can make faster, better operational
decisions.

## Framing Guardrail

Do not describe the source as a cleanup problem in the presentation. The source
is a living operational support record: managers write into it, add evidence,
attach context, record IDs, and preserve the practical history of user cases.
That is why the project is credible. RunPod, Ollama, Mistral, and the code do
not make the evidence legitimate; they only help read the manager-created
record at management scale.

## Scope Clarification

- It does not send messages to users.
- It does not replace support managers.
- It does not decide punishment, refunds, or enforcement.
- It does not stop the team from talking to users directly.
- It does not require a paid API workflow.

## What This Is

- An internal management dashboard.
- A way to turn a living support record into repeated user-want patterns.
- A way to see which issues affect trust, money, urgency, safety, and support load.
- A way to identify which playbooks, escalation lanes, and product fixes should come first.
- A private local analysis workflow using RunPod + Ollama/Mistral.

## Why We Are Doing This

- Support already talks to users directly, but management still needs to know what repeats across thousands of tickets.
- Individual tickets show one problem; this analysis shows the pattern behind thousands of problems.
- Without this, decisions are based on anecdotes, loud cases, or manually rereading a very large operational record.
- With this, management can see repeated user wants, risk levels, and recommended operating changes.
- The output is "show management what users keep asking for."
- The source document is legitimate because managers manually add context, evidence, screenshots, IDs, and notes as work happens.

## Proof Points To Use

- We analyzed `6,702` analysis-ready support records from the export.
- The current RunPod run deeply read `1,348` high-signal records with Mistral Small 3.2 24B and mapped all `6,702` analysis-ready records to the discovered wants.
- The system found `20` repeated user-want clusters in the current evidence layer.
- The model output is not just counts: it separates literal request from actual user intent, extracts user emotion, trust/money/safety risk, missing evidence, support next step, and product/process opportunity.
- The dashboard now includes a model-only readout: category-vs-intent mismatch, intents crossing multiple source categories, missing-evidence patterns, and an AI-created operating backlog.
- The dashboard now includes a longitudinal layer over `11` complete months (`2025-06` through `2026-04`), excluding the partial `2026-05` month from trend comparisons.
- The longitudinal layer found `1,233` repeat users with 2+ records, `772` repeat users with 3+ records, and `5,512` repeat-user journey events.
- The largest repeat-user archetype is not a row count: `304` multi-problem users generated `2,943` records across account, group, scam, dealer, visibility, and status issues.
- The system now shows individual UID roadmaps: first ticket, latest ticket, want path, status path, managers touched, unresolved share, and recommended operating action.
- If we decide to spend remaining RunPod credits, the same run can resume and deeply read about `6,681` useful non-empty records.
- The largest repeated wants are about account recovery, unban guidance, group visibility, scams/fraud, diamonds, SVIP access, and ban reason transparency.
- The workflow produces auditable files: CSVs, Excel workbooks, Markdown findings, and dashboard pages.
- Low-confidence mappings are not hidden; they go into a review queue.
- The analysis is only possible because managers created the underlying operational record.

## Executive Message

Users are not complaining randomly. The same few wants repeat:

- "Unban me and explain why I was blocked."
- "Restore my account, group, room, or visibility."
- "Protect me or others from scammers and abusive users."
- "Help me understand money, diamonds, dealer, or SVIP issues."
- "Give me a clear next step instead of a vague answer."

The management opportunity is to turn those repeated wants into clearer
support playbooks, better escalation lanes, and product/process fixes.

## Recommended Slide Deck

### Slide 1 - Title

**Title:** What Users Actually Want

**Subtitle:** Turning the living support record into a management map of repeated user needs.

**On-slide bullets:**

- Internal decision dashboard.
- Built from the real ticket record managers maintain every day.
- Goal: identify repeated user wants, risks, and operational fixes.

**Speaker note:**

This is not about replacing direct conversations with users. The team can keep
talking to users directly. This work helps management understand what those
conversations are repeatedly about.

### Slide 2 - Why This Exists

**Title:** Direct support conversations are valuable, but they do not scale into strategy

**On-slide bullets:**

- One ticket tells us one user problem.
- Thousands of tickets show repeated patterns.
- Management needs the pattern, not only individual cases.
- This analysis turns the support record into decision evidence.

**Speaker note:**

Support teams already see many cases every day and write down the operational
context. The gap is not conversation. The gap is pattern recognition across
thousands of documented conversations.

### Slide 3 - Scope: Different AI Use Case

**Title:** This is internal support intelligence

**Two-column slide:**

**User-facing AI/chat use case**

- Talks directly with users.
- Helps answer common questions.
- Needs careful tone, policy, and service ownership.
- Useful in some contexts, but not the focus here.

**This project**

- Reads historical tickets.
- Groups repeated user wants.
- Shows risk and urgency.
- Helps managers choose playbooks, escalation lanes, and product fixes.

**Speaker note:**

This distinction is important because management may hear "AI" and assume
user-facing chat. This project is a different use case: it helps management
listen to what users have already been saying across thousands of tickets.

### Slide 4 - Data Foundation

**Title:** The analysis starts from a real operational document

**On-slide bullets:**

- Source: exported support tickets manually maintained by managers.
- Analysis-ready support records: `6,702`.
- Languages: mixed English, Russian, Chinese, and manager-written operational notes.
- Evidence detected: URLs, screenshots, timestamps, IDs, ban reasons, user claims, money terms.
- This document is the foundation of the project; the GPU and code only help read it at scale.
- Local workflow: no paid API calls required.

**Speaker note:**

The point is not to make an abstract AI demo. The point is to respect the
document managers already created and make its repeated patterns readable for
management.

### Slide 5 - Method In Plain English

**Title:** How the system turns tickets into wants

**On-slide flow:**

1. Prepare the manager-maintained support record for analysis.
2. Score tickets by evidence and context.
3. Use local Mistral/Ollama to deeply read high-signal records.
4. Extract user want, emotion, risk, missing evidence, next step.
5. Cluster repeated wants into a taxonomy.
6. Map the full corpus to those wants with confidence bands.

**Speaker note:**

The AI is not deciding what to do to a user. It is summarizing patterns and
making the repeated intents visible.

### Slide 5B - Why This Is Not Just A Pivot Table

**Title:** The model adds the layer a spreadsheet cannot infer

**On-slide bullets:**

- A category pivot counts the label managers used; the model infers what the user is trying to accomplish.
- The same intent can appear across many source categories, managers, languages, and wording styles.
- The model separates "what the user literally asked" from "what they actually need."
- It extracts missing evidence from free-text notes: ban reason, transaction proof, voice sample, screenshots, IDs, timestamps.
- It synthesizes support playbooks and product/process fixes from repeated cases.
- It links repeat tickets by UID into journeys, so management can see a user's problem path instead of isolated rows.
- It compares complete months and creates an early-warning view of which wants are gaining momentum.

**Speaker note:**

This is the strongest defense of the GPU/model work. If the presentation only
shows bars, it looks like a spreadsheet. The value is the semantic layer:
intent, risk, missing evidence, and operating actions that are not present as
clean spreadsheet columns.

### Slide 5C - Macro And Micro Reality

**Title:** The GPU work is useful when it connects time + people + intent

**On-slide bullets:**

- Macro view: which wants rose or fell month by month.
- Early warning: which wants are likely to need attention next month.
- Micro view: which UIDs keep returning, what sequence of problems they bring, and whether the latest state is solved, failed, or still open.
- Operating view: repeat-user archetypes show which playbooks need ownership.

**Speaker note:**

This is the slide that prevents the project from looking like a spreadsheet
demo. The value is not only "how many rows." It is "what changed over time,
which users are stuck in loops, and what operating system should change."

### Slide 6 - Headline Finding

**Title:** The dominant problem is not only "unban me"

**On-slide bullets:**

- Many users want access restored.
- But many also want to know why they were blocked.
- Recovery users often sound anxious or desperate.
- Reporting users often sound angry and want visible enforcement.
- One default support response does not fit all of these situations.

**Speaker note:**

This is the first practical insight. The same "account issue" can mean very
different emotional states and different support needs.

### Slide 7 - Top Repeated Wants

**Title:** The same few user wants repeat

**Use current full-corpus mapped numbers as starting point:**

- Account recovery / access appeal: `657` mapped records.
- Channel visibility changes: `602`.
- Account recovery / phone or ownership recovery: `590`.
- Group member limit requests: `524`.
- Diamond transaction issues: `521`.
- Dealer recognition requests: `489`.
- Banned group restoration: `441`.
- Harassment reports: `373`.

**Speaker note:**

These numbers come from the current 1,348-record Mistral-read taxonomy
projected across all 6,702 analysis-ready support records. If we later run a
full AI census over the remaining useful short records, the exact counts may
move, but the pattern is already clear: a small number of wants repeat many
times.

### Slide 8 - Risk Is Not Equal Across Wants

**Title:** Some wants are high volume; others are high risk

**On-slide bullets:**

- Account recovery and unban guidance are high volume.
- Fraud, scam, dealer, and diamond issues carry higher trust and money risk.
- Group visibility and recommendation issues affect creators and communities.
- SVIP/status issues are lower volume but reputationally sensitive.

**Speaker note:**

Management should not prioritize only by volume. Some smaller clusters deserve
priority because they affect trust, money, or platform fairness.

### Slide 8B - Repeat-User Journeys

**Title:** Some tickets are not separate cases; they are continuing user stories

**On-slide bullets:**

- `1,233` users appear in the support record more than once.
- `772` users appear three or more times.
- The top repeated UID has `70` records over `292` days.
- Multi-problem users generated `2,943` records.
- Recommendation: assign an owner for repeated high-severity users instead of treating every row as a fresh isolated ticket.

**Speaker note:**

This is where the project becomes operationally serious. A repeated UID is not
just another count. It is a roadmap of where support, policy, product, and
trust decisions are failing to close the loop.

### Slide 9 - What Management Can Do With This

**Title:** This turns ticket patterns into operating changes

**On-slide bullets:**

- Create clearer ban and restriction explanation templates.
- Separate recovery-user playbooks from reporting-user playbooks.
- Create a fraud/diamond/dealer escalation lane.
- Add evidence checklists for scam, harassment, and money cases.
- Track repeated wants over time instead of asking managers to re-read the entire support record manually.

**Speaker note:**

The deliverable is a better operating map: where to standardize replies, where
to escalate, and where product/process is creating repeated support demand.

### Slide 10 - Human-In-The-Loop Design

**Title:** The tool supports judgment; it does not replace it

**On-slide bullets:**

- The system does not message users.
- Managers can inspect example tickets.
- Low-confidence rows are flagged for review.
- Outputs are downloadable and auditable.
- Final decisions remain with the team.

**Speaker note:**

This project supports management judgment. It does not automate user contact
or policy decisions.

### Slide 11 - What The Dashboard Shows

**Title:** The dashboard is the management interface

**On-slide bullets:**

- Executive briefing: decision ask, KPIs, top wants, risk landscape.
- Macro and micro reality: timelines, early warning, repeat-user journeys, and journey archetypes.
- What users want: filterable taxonomy and ticket examples.
- Browse tables: inspect any generated CSV.
- Full-corpus mapping: see every analysis-ready record mapped to a want.
- Review queue: inspect uncertain or risky rows.

**Speaker note:**

The dashboard is not for users. It is for managers and analysts to understand
patterns and prepare action.

### Slide 12 - Decision Ask

**Title:** Decision to ask from management

**On-slide bullets:**

Approve three operational workstreams:

1. Clearer account-ban and restriction explanations.
2. Dedicated fraud/diamond/dealer escalation lane.
3. Separate playbooks for anxious recovery users versus angry reporting users.

**Speaker note:**

The evidence is not that users are random. The evidence is that the same few
intents repeat. We should operationalize those repeated intents.

### Slide 13 - Caveat And Next Step

**Title:** What is proven now, and what improves next

**On-slide bullets:**

- Current version: 1,348 AI-read high-signal records, projected to all 6,702 analysis-ready support records.
- Optional stronger version: resume the RunPod extraction and deeply read about 6,681 useful non-empty records.
- Full projection should be rebuilt after any larger read.
- Low-confidence tickets remain reviewable, not overclaimed.

**Speaker note:**

This is already useful as a management map. The 1,348-record RunPod pass gives
us strong evidence; a full AI census would make the final readout stronger.

## Must-Have Visuals

Ask NotebookLM or slide designer to create these:

1. **Simple pipeline flow:** Manager-maintained support record -> prepare/score -> local AI read -> wants taxonomy -> full-corpus map -> dashboard.
2. **Top wants bar chart:** show the top repeated wants by mapped ticket count.
3. **Risk matrix:** volume on one axis, money/trust risk on another.
4. **AI use-case comparison:** two columns, "user-facing chat" vs "internal support intelligence."
5. **Decision ask slide:** three workstreams as large cards.

## Phrases To Use Carefully

These phrases are not wrong in every context, but they can make management hear
"user-facing automation" instead of "internal decision support":

- "AI will answer users."
- "Chatbot" as the first label for this project.
- "Automated support replacement."
- "We can stop talking to users."
- "The model decides."
- "Fully automated moderation."

## Better Phrases

Use these instead:

- "Internal decision dashboard."
- "Support intelligence."
- "Repeated user-want map."
- "Evidence-based operating priorities."
- "Human-in-the-loop review."
- "Local model analysis of historical tickets."
- "Management readout."

## Backup Explanation If They Ask Why Not Just Read Tickets Manually

Manual reading is useful for individual cases, but it does not scale across
thousands of tickets. This analysis keeps the examples but adds structure:

- which wants repeat,
- how often they repeat,
- which are risky,
- which are unclear,
- which need escalation,
- which support playbooks should change.

## Backup Explanation If They Ask How The Timeline Numbers Were Calculated

The timeline is not a keyword search and not a manual Excel filter.

Method:

1. Start from the manager-maintained ticket export.
2. Clean it into `6,702` analysis-ready support records.
3. Use local Mistral/Ollama to deeply read high-signal records and extract the
   actual user want.
4. Cluster those extracted wants into repeated user-want groups.
5. Map every analysis-ready support record to the closest discovered want using
   multilingual sentence embeddings.
6. Count mapped records by month.

Formula for one point on the chart:

```text
records = count(support records)
where semantic want = selected line
and month(date_raw) = selected month
```

Why this differs from filtering for `"restore"` in Google Sheets:

- A keyword filter only finds rows containing that exact word.
- The semantic want count also catches "unban", "blocked account", "cannot
  access", "whitelist", "recover", screenshots/IDs with little text, and
  multilingual wording that means the same operational problem.
- In the current run, the literal keyword `"restore"` appears in about `196`
  rows, while the semantic "Regain access to my account" family is much larger
  because many users ask for the same outcome without using the word "restore".
- The dashboard now has an audit panel where one chart point can be opened and
  the exact underlying ticket rows can be downloaded.

## Backup Explanation If They Say "We Already Talk To Users"

Yes, and we should continue. This project does not replace direct user contact.
It uses those conversations to help management see the pattern across all
contacts. It is like turning many individual conversations into a map of what
users repeatedly need.

## Backup Explanation If They Ask About Accuracy

This is why the design has three layers:

1. Local AI reads high-signal records directly.
2. The system projects the full corpus with confidence bands.
3. Low-confidence or risky rows are put into a review queue.

We do not hide uncertainty. We expose it.

## Suggested Closing Line

This is a way to listen to thousands of existing support conversations at once
and turn them into clear management decisions.
