# 12 - Management Slide Brief

Use this file as source material for NotebookLM to generate a simple management
deck.

The key framing: **this is not a chatbot for users**. This is an internal
decision tool that reads existing support tickets and shows management what
users repeatedly want, where trust is breaking, and which operational changes
would reduce repeated escalation.

## One-Sentence Positioning

We are not replacing direct support conversations. We are using the support
tickets we already have to understand the repeated user wants behind them, so
management can make faster, better operational decisions.

## What This Is Not

- Not a user-facing chatbot.
- Not an automatic reply system.
- Not a plan to stop talking to users directly.
- Not a replacement for support managers.
- Not a black-box decision maker.
- Not a paid API workflow.

## What This Is

- An internal management dashboard.
- A way to turn messy support tickets into repeated user-want patterns.
- A way to see which issues affect trust, money, urgency, safety, and support load.
- A way to identify which playbooks, escalation lanes, and product fixes should come first.
- A private local analysis workflow using RunPod + Ollama/Mistral, not a public chatbot.

## Why We Are Doing This

- Support already talks to users directly, but management still needs to know what repeats across thousands of tickets.
- Individual tickets show one problem; this analysis shows the pattern behind thousands of problems.
- Without this, decisions are based on anecdotes, loud cases, or manually reading spreadsheets.
- With this, management can see repeated user wants, risk levels, and recommended operating changes.
- The output is not "let AI answer users." The output is "show management what users keep asking for."

## Proof Points To Use

- We analyzed `6,702` cleaned support tickets from the export.
- The current local run deeply read `250` rich tickets with a local AI model and mapped all `6,702` cleaned tickets to the discovered wants.
- The next RunPod run is designed to deeply read about `1,348` high-signal tickets for stronger evidence.
- The system found `17` repeated user wants in the current sample.
- The largest repeated wants are about account recovery, unban guidance, group visibility, scams/fraud, diamonds, SVIP access, and ban reason transparency.
- The workflow produces auditable files: CSVs, Excel workbooks, Markdown findings, and dashboard pages.
- Low-confidence mappings are not hidden; they go into a review queue.

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

**Subtitle:** Turning messy support tickets into a management map of repeated user needs.

**On-slide bullets:**

- Internal decision dashboard, not a chatbot.
- Built from existing support tickets.
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
- This analysis turns support history into decision evidence.

**Speaker note:**

Support teams already see many cases every day. The gap is not conversation.
The gap is pattern recognition across thousands of conversations.

### Slide 3 - What This Is And Is Not

**Title:** This is not a user-facing AI assistant

**Two-column slide:**

**Not this**

- Not answering users automatically.
- Not replacing support staff.
- Not deciding punishment or refunds.
- Not sending messages to customers.

**This**

- Reads historical tickets.
- Groups repeated user wants.
- Shows risk and urgency.
- Helps managers choose playbooks, escalation lanes, and product fixes.

**Speaker note:**

This distinction is important. The previous chatbot-style idea sounded like
"AI will talk to users." This project is different: it helps management listen
to what users have already been saying.

### Slide 4 - Data Foundation

**Title:** The analysis starts from real support data

**On-slide bullets:**

- Source: exported support tickets.
- Cleaned tickets: `6,702`.
- Languages: mixed English, Russian, Chinese, and messy manager notes.
- Evidence detected: URLs, screenshots, timestamps, IDs, ban reasons, user claims, money terms.
- Local workflow: no paid API calls required.

**Speaker note:**

The point is not to make an abstract AI demo. The point is to use the messy
data we already have and make it readable for management.

### Slide 5 - Method In Plain English

**Title:** How the system turns tickets into wants

**On-slide flow:**

1. Clean the raw export.
2. Score tickets by evidence and context.
3. Use local Mistral/Ollama to deeply read high-signal tickets.
4. Extract user want, emotion, risk, missing evidence, next step.
5. Cluster repeated wants into a taxonomy.
6. Map the full corpus to those wants with confidence bands.

**Speaker note:**

The AI is not deciding what to do to a user. It is summarizing patterns and
making the repeated intents visible.

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

**Use current sample/full-corpus numbers as starting point:**

- Unban guidance requests: `1,084` mapped tickets.
- Group visibility recovery: `776`.
- Account access appeals: `708`.
- Official dealer fraud reports: `560`.
- Diamond purchase questions: `441`.
- Unclear account restrictions: `439`.
- SVIP access disputes: `418`.
- Abusive reporting and blocking: `376`.

**Speaker note:**

These numbers come from the current 250-ticket AI-read taxonomy projected
across all cleaned tickets. After the 1,348-ticket RunPod extraction, the exact
counts may change, but the pattern is already clear: a small number of wants
repeat many times.

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

### Slide 9 - What Management Can Do With This

**Title:** This turns ticket patterns into operating changes

**On-slide bullets:**

- Create clearer ban and restriction explanation templates.
- Separate recovery-user playbooks from reporting-user playbooks.
- Create a fraud/diamond/dealer escalation lane.
- Add evidence checklists for scam, harassment, and money cases.
- Track repeated wants over time instead of reading raw exports manually.

**Speaker note:**

The deliverable is not a chatbot. The deliverable is a better operating map:
where to standardize replies, where to escalate, and where product/process is
creating repeated support demand.

### Slide 10 - Why This Is Safer Than A Chatbot Proposal

**Title:** This keeps humans in the loop

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
- What users want: filterable taxonomy and ticket examples.
- Browse tables: inspect any generated CSV.
- Full-corpus mapping: see every cleaned ticket mapped to a want.
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

- Current version: 250 AI-read rich tickets, projected to all 6,702 cleaned tickets.
- Next stronger version: about 1,348 high-signal tickets deeply read by Mistral on RunPod.
- Full projection will be rebuilt after the larger read.
- Low-confidence tickets remain reviewable, not overclaimed.

**Speaker note:**

This is already useful as a management map. The 1,348-ticket RunPod pass makes
the evidence stronger before final presentation.

## Must-Have Visuals

Ask NotebookLM or slide designer to create these:

1. **Simple pipeline flow:** Raw tickets -> clean/score -> local AI read -> wants taxonomy -> full-corpus map -> dashboard.
2. **Top wants bar chart:** show the top repeated wants by mapped ticket count.
3. **Risk matrix:** volume on one axis, money/trust risk on another.
4. **Not a chatbot comparison:** two columns, "not user-facing chatbot" vs "internal management intelligence."
5. **Decision ask slide:** three workstreams as large cards.

## Words To Avoid

Avoid these phrases in the management deck:

- "AI will answer users."
- "Chatbot."
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

## Backup Explanation If They Say "We Already Talk To Users"

Yes, and we should continue. This project does not replace direct user contact.
It uses those conversations to help management see the pattern across all
contacts. It is like turning many individual conversations into a map of what
users repeatedly need.

## Backup Explanation If They Ask About Accuracy

This is why the design has three layers:

1. Local AI reads high-signal tickets directly.
2. The system projects the full corpus with confidence bands.
3. Low-confidence or risky rows are put into a review queue.

We do not hide uncertainty. We expose it.

## Suggested Closing Line

This is not a chatbot project. It is a way to listen to thousands of existing
support conversations at once and turn them into clear management decisions.
