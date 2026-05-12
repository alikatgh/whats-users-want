# 01 — What is a prompt

You have 250 tickets you want to interpret. You have a small
language model running on `localhost:11434`. You need each ticket to
come back as a JSON object with the same thirteen fields. You will
call the model 250 times.

What you put in front of the model on each of those 250 calls is
the prompt. The prompt is the only thing you control at runtime.
Everything else — the model weights, the architecture, the
training data — is fixed. Get the prompt right or you get garbage
back 250 times.

This lesson teaches you the prompt anatomy used by the project's
extraction script: the system / user split, why the system
message is more defensive on the Ollama backend than on the
OpenAI backend, why we set `temperature=0`, and why the per-ticket
metadata gets injected via `str.format` rather than `f""`.

## Prompt versus API parameter

A prompt is a string of text the model reads. An API parameter is
a flag you pass to the API alongside the prompt. They are different
levers and they do different things.

In the Ollama call at
[`ollama_chat_json`](../../scripts/llm_extract_rich_tickets.py)
the payload looks like this:

```python
payload = {
    "model": model,
    "stream": False,
    "format": "json",
    "options": {
        "temperature": 0,
        "num_ctx": 8192,
    },
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
}
```

`model`, `stream`, `format`, `options.temperature`, `options.num_ctx`
are API parameters. They tell the runtime *how* to call the model
— which weights to load, how creative to be, how big a window to
allocate. You set them once and forget them.

`messages` is the prompt. It's a list of role-tagged strings. The
model reads them and generates a continuation. You rewrite this
content for every ticket.

The split matters because the controls are independent. Setting
`temperature=0` does not stop the model from copying the schema
back at you. Tightening the system prompt does not change the
context window size. You need both right.

## The system / user split

Chat-style APIs accept a list of messages, each tagged with a
role: `system`, `user`, or `assistant`. The system message sets
the persona and the rules. The user message is the per-call
payload. The assistant message is the model's reply (you don't
write that — you read it).

The script ships two system prompts. One for the OpenAI backend,
one for Ollama. They look different on purpose.

The OpenAI version is at
[`SYSTEM_PROMPT`](../../scripts/llm_extract_rich_tickets.py):

```python
SYSTEM_PROMPT = """You are analyzing messy support tickets from IMO/BIGO-style support operations.
Extract what the user actually wants, not only the literal category.
Preserve uncertainty. Do not invent facts. If evidence is missing, say what is missing.
Treat screenshots/URLs/timestamps/ban reasons/IDs as evidence, not noise.
Return exactly one JSON object matching the requested schema. No markdown.
"""
```

Five lines. Sets the role ("you are analyzing messy support
tickets"), the goal ("extract what the user actually wants"),
the epistemic policy ("preserve uncertainty, do not invent"),
the evidence convention ("IDs as evidence, not noise"), and the
output format ("one JSON object, no markdown").

That's enough for GPT-4-class models. They have the capacity to
infer everything else.

The Ollama version is at
[`OLLAMA_SYSTEM_PROMPT`](../../scripts/llm_extract_rich_tickets.py):

```python
OLLAMA_SYSTEM_PROMPT = """You extract support-ticket meaning into JSON.
Infer the user's real goal from the ticket. Do not copy labels, enum lists, or template placeholders.
Write concrete short phrases, not enum tokens, for literal_request, actual_user_want, support_next_step, and product_opportunity.
If unsure, use "other", "unknown", empty lists, and lower confidence.
Return one valid JSON object only.
"""
```

Same length, different content. Read the second sentence: "Do
not copy labels, enum lists, or template placeholders." That is
not a stylistic preference. That is a scar. Small models like
`gemma3:4b` will, when stressed, copy the schema literally back
at you — they will write `"literal_request": "short string: what
the user explicitly asked for"` because that string was in the
prompt and the model decided it was a reasonable continuation.

The third sentence: "Write concrete short phrases, not enum
tokens, for literal_request, actual_user_want, support_next_step,
and product_opportunity." This is also a scar. Small models leak
snake_case into narrative fields. Without this line, you get
`"actual_user_want": "investigate_fraud"` instead of `"actual_user_want":
"the user wants their money back from a scammer"`.

The fourth sentence: "If unsure, use 'other', 'unknown', empty
lists, and lower confidence." This is a graceful-failure
instruction. Without it, the model invents. With it, the model
admits uncertainty in a way you can detect downstream.

The OpenAI prompt assumes capacity. The Ollama prompt assumes
fragility. Module 03 of this module ("Defensive prompting") will
walk every "do not" line and trace it to a specific failure mode
we saw in production.

## The user template and `str.format`

The system prompt is the same for every ticket. The user prompt
changes per ticket. The change is mechanical — same template,
different ticket metadata — so we use a string template.

[`USER_TEMPLATE`](../../scripts/llm_extract_rich_tickets.py):

```python
USER_TEMPLATE = """Ticket metadata:
source_row: {source_row}
manager: {manager}
date: {date_raw}
category: {category}
question_kind: {question_kind}
status: {status_en}
primary_desire_rule_based: {primary_desire}
semantic_issue_label: {issue_label}
context_depth_score: {context_depth_score}

Ticket text:
{text}
"""
```

Nine metadata slots and one text slot. Notice what's *not* in
the template: nothing about jobs to be done, nothing about
emotions, no mention of risk levels. The system prompt and the
schema (which we'll see in lesson 02) cover those. The user
template is *just* the per-ticket payload.

The rendering happens at
[`candidate_prompt`](../../scripts/llm_extract_rich_tickets.py):

```python
def candidate_prompt(row: pd.Series) -> str:
    return USER_TEMPLATE.format(
        source_row=row.get("source_row", ""),
        manager=row.get("manager", ""),
        date_raw=row.get("date_raw", ""),
        category=row.get("category", ""),
        question_kind=row.get("question_kind", ""),
        status_en=row.get("status_en", ""),
        primary_desire=row.get("primary_desire", ""),
        issue_label=row.get("issue_label", ""),
        context_depth_score=row.get("context_depth_score", ""),
        text=row.get("llm_input_text", ""),
    )
```

Two design choices worth understanding.

First: `str.format(**kwargs)` instead of an f-string. `f""`
needs the variables to exist at the time the string literal is
parsed. The template lives at module level, before any `row`
object exists — it has to. So we declare the template once with
`{name}` placeholders and substitute per call.

Second: `row.get(key, default="")` instead of `row[key]`. Pandas
Series support both, but `row.get` returns the default if the
column is missing rather than raising `KeyError`. This forgiveness
matters because `enriched_tickets.csv` has evolved over runs;
older versions might not have `issue_label`, and we don't want
the prompt to crash when an optional column is absent. The empty
string is a safe substitution — `str.format("category: {x}",
x="")` produces `"category: "` and the model handles it.

## Ticket metadata as context

The user prompt does not just contain the ticket text. It also
contains everything the upstream pipeline already knows about
the ticket: which manager handled it, what category and
question_kind it got tagged with, what `primary_desire` slug the
rules layer picked, what `issue_label` BERTopic gave it, what
its `context_depth_score` is.

Why hand all that to the model? Why not let it figure out from
the text what the topic is?

Because the model is small and weak, and the upstream pipeline
already did the work. The rules layer in
[`call_rules`](../../scripts/llm_extract_rich_tickets.py) ran
twelve regex patterns and computed `primary_desire`. BERTopic
ran on 384-dimensional multilingual embeddings and assigned a
cluster ID. Those classifications are deterministic, fast, and
reproducible. Asking the LLM to redo them is wasteful — and on
small models, *worse than wasteful*. The LLM is unreliable at
classification but reliable at narrative interpretation. So the
prompt grounds the model in upstream work and asks it for the
part only the model can do.

This is sometimes called "prompt grounding" or "in-context
retrieval". You give the model a snapshot of what other systems
already know, and the model treats that as authoritative
context. It frees up the model's capacity for the part you
actually need.

You can see this principle taken to its extreme in the hybrid
backend (lesson 06). There the user prompt explicitly contains
the rules-layer's job classification, evidence list, and risk
levels with the instruction "you must respect this", and the
model is asked *only* for narrative fields. We'll cover that in
detail later. For now: notice that the prompt is teaching the
model what the rest of the system already concluded.

## Why temperature = 0

`temperature` controls how creative the model is. It scales the
probability distribution over next-token choices before sampling.
At `temperature=1` the model picks tokens roughly proportional to
their predicted probability. At `temperature=0` the model always
picks the single most likely next token — generation becomes
greedy and deterministic.

For extraction, you want determinism. Three reasons.

Reproducibility. The pipeline runs nightly. Operators look at the
diff between runs to spot drift. If the model produces a different
extraction for the same ticket on each run, the diff is meaningless
— every row changes. With `temperature=0`, identical input produces
identical output, so any change in the diff reflects either a
ticket update or a prompt change.

Truthfulness. Higher temperature makes the model sample
lower-probability tokens. For creative writing that's a feature
(prose gets more interesting). For factual extraction it's a bug
(the model invents). At `temperature=0` you get the model's best
guess, not its most stylish one.

Debugging. When something goes wrong in a deterministic system,
you can re-run with the same input and reproduce the bug. With
non-zero temperature you can't — you have to either save the seed
(if the API exposes it) or accept that 1 in 50 runs of the same
prompt produces a weird output you'll never see again.

`temperature=0` shows up twice in the same payload.
[`ollama_chat_json`](../../scripts/llm_extract_rich_tickets.py)
sets `"options": {"temperature": 0, "num_ctx": 8192}`.
[`call_openai`](../../scripts/llm_extract_rich_tickets.py) sets
`temperature=0` on the OpenAI client call. Same value, different
APIs, same intent.

## What the rendered prompt actually looks like

The script writes a sample rendered prompt to disk on every run, so
you can read what was actually sent. After a run completes,
[`llm_extraction_prompt.md`](../../outputs/option2_20260502_150055/llm_extraction_prompt.md)
contains the system prompt and one rendered user prompt.

The first candidate ticket in our reference run is row 615.
After `candidate_prompt(row)` runs on it, the user message
starts with:

```
Ticket metadata:
source_row: 615
manager: Albert
date: 2025-12-13
category: <whatever category was assigned>
question_kind: appeal_or_dispute
status: closed
primary_desire_rule_based: clear_name_or_get_fairness
semantic_issue_label: ban audit, ban verification, ban resolution
context_depth_score: 64.21

Ticket text:
<the actual ticket question>
```

The model sees nine metadata fields and the ticket text. The
metadata is "what the rest of the system thinks". The text is
"what the user actually wrote". The system prompt is "this is
the kind of answer I expect."

The model's first job is to *not* repeat what's already in the
metadata. The fields it has to fill — `literal_request`,
`actual_user_want`, `support_next_step`, `product_opportunity` —
are sentences. Sentences cannot be derived from category labels,
no matter how good the labels are. That is the part of the work
only a language model can do.

## Try it

Generate the rendered system prompt and user prompt for one
ticket without calling the model. The script supports this via
`--dry-run`.

```python
import json
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, "scripts")
from llm_extract_rich_tickets import (
    SYSTEM_PROMPT,
    OLLAMA_SYSTEM_PROMPT,
    USER_TEMPLATE,
    candidate_prompt,
)

run_dir = Path("outputs/option2_20260502_150055")
candidates = pd.read_csv(run_dir / "llm_extraction_candidates.csv")
row = candidates.iloc[0]

print("=== SYSTEM (OpenAI backend) ===")
print(SYSTEM_PROMPT)

print("\n=== SYSTEM (Ollama backend, more defensive) ===")
print(OLLAMA_SYSTEM_PROMPT)

print("\n=== USER (rendered for first candidate) ===")
print(candidate_prompt(row)[:1500])
```

Run it. You should see the same three blocks the script writes to
[`llm_extraction_prompt.md`](../../outputs/option2_20260502_150055/llm_extraction_prompt.md).
Read both system prompts side by side and circle every sentence
in the Ollama version that does not appear in the OpenAI version.
Each of those sentences is a defensive addition; in lesson 03
you will trace each one to a specific failure mode.

Then change `temperature=0` to `temperature=0.5` in
[`ollama_chat_json`](../../scripts/llm_extract_rich_tickets.py)
locally (don't commit), call the model on the same ticket twice
in a row, and confirm the outputs differ. Restore `temperature=0`
and confirm two consecutive calls now match byte-for-byte. That
is the property the rest of the pipeline depends on.
