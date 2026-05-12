# 03 — Defensive prompting

You wrote a clean, polite system prompt. You added the schema. You
turned on JSON mode. You set `temperature=0`. You ran 50 tickets
through `gemma3:4b`.

Then you read the output.

Two of fifty rows have `"job_to_be_done": "angry"`. Three rows
have `"actual_user_want": "investigate_fraud"`. One row has
`"product_opportunity": "improve user experience"` for a ticket
about diamond fraud. Four rows have `"literal_request": "short
string: what the user explicitly asked for"` — the model copied
the schema descriptor verbatim into the field.

None of these failures would happen with GPT-4. They all happen
with `gemma3:4b`. Small models fail differently, and the only fix
is a more defensive prompt.

This lesson teaches you what "defensive prompting" actually looks
like. We'll walk every "do not" sentence in the Ollama prompt
stack, name the failure mode each one was added to fight, and
show why the per-call user prompt inlines the full enum lists
even though the system prompt and the schema already mention
them.

## How small models fail

Failures cluster into four families.

**Schema echo.** The model copies the schema description into the
field instead of replacing it with its own answer. The schema
says `"literal_request": "short string: what the user explicitly
asked for"`, and the model returns `"literal_request": "short
string: what the user explicitly asked for"`. The descriptor
becomes the value. JSON mode doesn't catch this — the bytes are
valid JSON.

**Snake_case in narrative fields.** The model has been trained on
code and on enum-heavy data, so when asked for a free-text answer
it sometimes regresses to a snake_case token like `infer_goal` or
`fix_issue`. These look like valid English to a tokenizer but
they're enum-shaped artifacts, not interpretation.

**Enum drift.** The model picks a value adjacent to your enum but
not in it. You ask for one of `[recover_access, prove_innocence,
..., other]`. The model returns `unblock_account` (synonym for
`recover_access`) or `investigate_fraud` (synonym for `avoid_scam`)
or — much weirder — `angry` (which is an emotion, not a job; the
model confused two fields).

**Over-collapse.** The model picks the same enum value for
everything. In our smoke test, `gemma3:1b` direct-mode classified
9 out of 10 tickets as `recover_access`, regardless of content,
because that was the highest-frequency token in the training
distribution and the model wasn't holding the schema firmly
enough to discriminate.

The four families are not exhaustive. There's also: hallucinating
UIDs that don't appear in the ticket, returning impossible
risk scores like 7 or "high", swapping fields (writing the
emotion into job and vice versa), embedding markdown into the
JSON values, and emitting the entire prompt back unchanged. But
the four above account for most of what we saw, and the prompt
is shaped to fight all four.

## The defensive system prompt

Compare the OpenAI prompt and the Ollama prompt side by side.
[`SYSTEM_PROMPT`](../../scripts/llm_extract_rich_tickets.py),
five lines, used by the OpenAI backend:

```python
SYSTEM_PROMPT = """You are analyzing messy support tickets from IMO/BIGO-style support operations.
Extract what the user actually wants, not only the literal category.
Preserve uncertainty. Do not invent facts. If evidence is missing, say what is missing.
Treat screenshots/URLs/timestamps/ban reasons/IDs as evidence, not noise.
Return exactly one JSON object matching the requested schema. No markdown.
"""
```

Polite. Confident. Assumes the model can figure things out from
context.

[`OLLAMA_SYSTEM_PROMPT`](../../scripts/llm_extract_rich_tickets.py),
same length, but every line is a constraint:

```python
OLLAMA_SYSTEM_PROMPT = """You extract support-ticket meaning into JSON.
Infer the user's real goal from the ticket. Do not copy labels, enum lists, or template placeholders.
Write concrete short phrases, not enum tokens, for literal_request, actual_user_want, support_next_step, and product_opportunity.
If unsure, use "other", "unknown", empty lists, and lower confidence.
Return one valid JSON object only.
"""
```

Read each line as a fight against a specific failure.

Line 1: "You extract support-ticket meaning into JSON." This is
the role. Plain. No "you are an AI assistant", no flattery,
nothing the model could mistake for a chat opening that needs
chat-style filler in the response.

Line 2: "Do not copy labels, enum lists, or template placeholders."
This is anti-schema-echo. Without it, `gemma3:4b` sometimes
returns `"job_to_be_done": "one of: recover_access, prove_innocence,
..."` — the literal enum-list string. With it, the model knows
copying the prompt is forbidden.

Line 3: "Write concrete short phrases, not enum tokens, for
literal_request, actual_user_want, support_next_step, and
product_opportunity." This is anti-snake_case. Naming the four
narrative fields explicitly tells the model: these are *not* the
enum fields. Enum tokens belong in `job_to_be_done` and
`user_emotion`. Here you write English.

Line 4: "If unsure, use 'other', 'unknown', empty lists, and
lower confidence." This is the graceful-failure clause. Without
it, an uncertain model invents. With it, the model has explicit
permission to admit uncertainty, and a defined vocabulary for
doing so. `"other"` is in the job enum specifically as the
safe-uncertain choice. `"unknown"` is in the emotion enum for
the same reason.

Line 5: "Return one valid JSON object only." Combined with JSON
mode, this is belt-and-suspenders. JSON mode forces the bytes;
this line tells the model not to also write a preamble.

The hybrid backend's system prompt
([`HYBRID_OLLAMA_SYSTEM_PROMPT`](../../scripts/llm_extract_rich_tickets.py))
adds another constraint:

```python
HYBRID_OLLAMA_SYSTEM_PROMPT = """You write concise human interpretation fields for support-ticket analysis.
A deterministic rules layer already extracted IDs, evidence, risk levels, and job classification.
Do not reclassify the ticket. Do not invent facts. Use the supplied evidence and uncertainty.
Return one valid JSON object only.
"""
```

"A deterministic rules layer already extracted IDs, evidence,
risk levels, and job classification" tells the model: those
fields are not yours to write. "Do not reclassify the ticket"
is the explicit prohibition. The hybrid backend ships the rules-layer
output inside the user prompt with the instruction "you must
respect this", and the system prompt reinforces that the model's
job is interpretation, not classification.

## The defensive user prompt

The system prompt sets persona. The user prompt carries the
per-call payload. For the Ollama backend, the user prompt is
also a defensive instrument.

[`call_ollama`](../../scripts/llm_extract_rich_tickets.py)
builds it line by line:

```python
user_prompt = (
    candidate_prompt(row)
    + "\n\nFill the JSON template below with inferred values from the ticket."
    + "\nDo not repeat the template placeholders. Do not output the enum lists."
    + "\nliteral_request: summarize what the user explicitly asks, in plain English."
    + "\nactual_user_want: infer the outcome the user needs, in plain English."
    + "\nsupport_next_step: write a concrete support action, starting with a verb."
    + "\nproduct_opportunity: write a concrete product/system improvement; avoid just 'unknown'."
    + "\nDo not use vague phrases like 'infer_goal', 'resolve issue', 'analyze', or just an enum token."
    + "\nUse exactly one job_to_be_done token from: "
    + ", ".join(JOB_VALUES)
    + "\nUse exactly one user_emotion token from: "
    + ", ".join(EMOTION_VALUES)
    + "\nUse evidence_present values only from: "
    + ", ".join(EVIDENCE_VALUES)
    + "\nUse manager_note_quality from: "
    + ", ".join(NOTE_QUALITY_VALUES)
    + "\nInteger risk levels must be 1 to 5. confidence must be 0.0 to 1.0."
    + "\nReturn JSON only:\n"
    + template_text
)
```

Walk each block.

`candidate_prompt(row)` is the rendered ticket metadata + ticket
text from lesson 01.

"Fill the JSON template below with inferred values from the
ticket." This is the framing: not "produce JSON matching this
schema" but "overwrite this skeleton". The skeleton is the
[`local_json_template`](../../scripts/llm_extract_rich_tickets.py)
output — every key already present with safe defaults.

"Do not repeat the template placeholders. Do not output the
enum lists." Anti-schema-echo, repeated. Once in the system
prompt isn't enough for small models; the user prompt repeats
it because the model's attention to recent text is stronger
than to the system message.

The four "field: instruction" lines name each narrative field
and tell the model what shape of answer is expected. Notice the
verbs: "summarize", "infer", "write a concrete support action,
starting with a verb", "write a concrete product/system
improvement". Each instruction is operational, not abstract. The
model isn't asked to "be helpful" — it's asked to start with a
verb.

"Do not use vague phrases like 'infer_goal', 'resolve issue',
'analyze', or just an enum token." Each of these phrases is in
the
[`GENERIC_PHRASES`](../../scripts/llm_extract_rich_tickets.py)
set used by the validator. The blacklist is duplicated in the
prompt because it's cheaper to discourage the failure than to
reject it after the fact. The prompt and the validator share
vocabulary on purpose.

"Use exactly one job_to_be_done token from: " followed by
`", ".join(JOB_VALUES)` inlines the enum directly. Not "from
the schema above" — actually `recover_access, prove_innocence,
restore_income, grow_channel, avoid_scam, buy_or_sell_diamonds,
gain_status, understand_punishment, restore_visibility,
protect_community, fix_product_flow, customize_identity, other`
spelled out as a comma-separated list. The same for emotion,
evidence, and note quality.

Why inline the enums in the user prompt when they're already in
the schema dict embedded earlier? Because the model's attention
is recency-biased. The enum list immediately before "Return JSON
only:" carries more weight than the same list buried in a schema
description higher up. With small models you reinforce. The
phrase "use exactly one X token from: a, b, c" is the strongest
forcing signal you can write short of constrained decoding.

"Integer risk levels must be 1 to 5. confidence must be 0.0 to
1.0." Type plus range. Without it, the model sometimes returns
`"urgency_level": 7` or `"urgency_level": "high"`. The validator
catches both, but the prompt prevents most.

"Return JSON only:" plus the template text is the final
forcing instruction. The model sees a complete JSON object with
neutral defaults and is told to overwrite. Not "produce" — overwrite.
This in-fill framing is the single biggest reliability boost we
got on small models.

## Why "do not" works

You might worry that a long string of "do not" sentences would
confuse the model. In practice, the opposite is true. Each "do
not" specifies a *named failure*, and naming the failure tells
the model what it should not do. "Do not use snake_case" is
specific. "Be helpful" is vague.

There's a Bayesian framing: each constraint cuts the space of
acceptable outputs and concentrates the model's probability mass
on the part that satisfies all the constraints. With enough
constraints, the model has only one reasonable thing to write,
and it writes that thing.

There's also a behavioral framing: small models trained on
internet text will, by default, pick the high-probability
generic answer ("improve user experience"). The prompt has to
out-shout the training distribution. "Do not use vague phrases"
plus a list of specific vague phrases is what out-shouting looks
like.

The tradeoff: longer prompts use more context and cost more
inference time. For a 250-row run that's a few extra seconds per
call. For a 6,728-row run on `gpt-4o` it would be real money. We
accept the cost because the alternative is bad data.

## Each "do not" is a scar

Every defensive sentence in the Ollama prompt was added in
response to a specific bad output we saw. A short genealogy:

- "Do not copy labels" was added after the first run produced
  `"job_to_be_done": "abuse_or_scam"` (a `primary_desire` slug
  copied from the user prompt's metadata block).
- "Do not output the enum lists" was added after a row came back
  with `"user_emotion": "neutral, confused, anxious, angry,
  desperate, betrayed, urgent, hopeful, unknown"` — the entire
  enum as the value.
- "Do not use vague phrases like 'infer_goal'" was added after
  three out of fifty rows had `"actual_user_want": "infer_goal"`
  — the model regressed to a snake_case placeholder it must have
  seen in code training data.
- "Use exactly one job_to_be_done token from: <enum>" was added
  after the model picked `"unblock_account"` or `"account_recovery"`
  instead of `"recover_access"`. Some of those got captured by
  the alias map (lesson 05), but inlining the enum in the prompt
  reduces the rate.
- "Integer risk levels must be 1 to 5" was added after a row
  came back with `"urgency_level": 7`.
- "needs_human_review" defaulting to `True` in the skeleton was
  added after rows with weak extractions still had
  `needs_human_review: false`, which would have routed them to
  auto-resolve.

This is the production pattern: prompt iteration is a feedback
loop. You run the model, you read the failures, you add a "do
not" sentence for each named failure, you ship. Over time the
prompt grows and the failure rate drops. After several rounds,
the failure rate on `gemma3:4b` reached 2 out of 250 (0.8%) on
our reference run.

## The output of all this

[`ollama_extractions.jsonl`](../../outputs/option2_20260502_150055/ollama_extractions.jsonl)
in the reference run has 250 lines. Of those:

- 248 lines have `"_status": "ok"` — the model produced a valid,
  in-enum, non-vague JSON object on the first try.
- 2 lines have `"_status": "bad_output"` and `"_quality_flag":
  "invalid_job"` — both from enum drift in the
  `job_to_be_done` field.

The two failures are educational because they show what the
defensive prompt did *not* prevent. Row 5990 has
`"job_to_be_done": "angry"` — the model confused job with
emotion. Even with "Use exactly one job_to_be_done token from:
recover_access, prove_innocence, ...", it picked an emotion
token. Row 2739 has `"job_to_be_done": "gain_status_or_privileges"`
— the model invented a verbose synonym that isn't in the alias
map.

Both failures got caught by the validator (lesson 04). Both
could be reduced by adding more constraints, but at some point
the prompt becomes longer than the ticket and you accept the
remaining 0.8% failure rate as the cost of using a 4 B-parameter
model on a laptop.

## Try it

Read the system prompts side by side and count the defensive
deltas. Then induce a failure on purpose to see what un-defensive
output looks like.

```python
import sys
sys.path.insert(0, "scripts")
from llm_extract_rich_tickets import (
    SYSTEM_PROMPT,
    OLLAMA_SYSTEM_PROMPT,
    HYBRID_OLLAMA_SYSTEM_PROMPT,
    GENERIC_PHRASES,
    JOB_VALUES,
    EMOTION_VALUES,
)

# 1. Side-by-side line counts
print("OpenAI prompt lines:", SYSTEM_PROMPT.strip().count("\n") + 1)
print("Ollama prompt lines:", OLLAMA_SYSTEM_PROMPT.strip().count("\n") + 1)
print("Hybrid prompt lines:", HYBRID_OLLAMA_SYSTEM_PROMPT.strip().count("\n") + 1)

# 2. The defensive vocabulary
print("\nGENERIC_PHRASES blacklist:")
for p in sorted(GENERIC_PHRASES):
    print(f"  - {p}")

# 3. The job enum is repeated in the user prompt
print(f"\nJOB_VALUES (inlined per call): {len(JOB_VALUES)} values")
print(f"EMOTION_VALUES (inlined per call): {len(EMOTION_VALUES)} values")

# 4. Find the two real failures in the reference run
import json
from pathlib import Path
run_dir = Path("outputs/option2_20260502_150055")
with (run_dir / "ollama_extractions.jsonl").open() as f:
    for line in f:
        r = json.loads(line)
        if r.get("_status") == "bad_output":
            print(f"\nrow {r['source_row']}: flag={r['_quality_flag']}")
            print(f"  job_to_be_done = {r['job_to_be_done']!r}")
            print(f"  literal_request = {r['literal_request']!r}")
```

You should see:

- The OpenAI prompt is 5 lines, the Ollama prompt is 5 lines but
  with explicit anti-failure constraints, the hybrid prompt is
  4 lines focused on "don't reclassify".
- 17 phrases in the blacklist, ranging from `unknown` to
  `improve user experience`.
- 13 job values and 9 emotion values, each inlined per call.
- Row 5990 with job = `'angry'` and row 2739 with job =
  `'gain_status_or_privileges'`. Both are caught and tagged
  `bad_output`.

Bonus exercise: edit
[`OLLAMA_SYSTEM_PROMPT`](../../scripts/llm_extract_rich_tickets.py)
locally to remove the line "Do not copy labels, enum lists, or
template placeholders". Run the extraction on a 10-ticket sample
(`--limit 10`). Read the JSONL. You'll see at least one row with
schema-text leaked into a narrative field. Restore the line and
the leakage stops. That single sentence is doing real work.
