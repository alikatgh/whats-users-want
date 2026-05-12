# 02 — JSON mode and schemas

You ask the model to "return JSON with these thirteen fields". The
model returns:

```
Sure, here's the JSON for that ticket:

```json
{
  "literal_request": "I want my account back",
  ...
}
```

Hope that helps!
```

Three problems. There's prose before the JSON. There's a markdown
code fence wrapping it. There's prose after the JSON. None of
those are valid JSON. `json.loads(content)` throws.

You can defend with regex (the script does — see
[`parse_json_object`](../../scripts/llm_extract_rich_tickets.py),
which strips the fence and slices to the outermost `{...}`).
But the better fix is to never let the model emit the wrapper
in the first place. Both Ollama and OpenAI expose a "JSON mode"
that does exactly this.

This lesson teaches you what JSON mode does at the API level,
why it's not enough on its own, why we still embed a `SCHEMA`
dict in the prompt body, and how the post-hoc validation in
[`output_quality_flag`](../../scripts/llm_extract_rich_tickets.py)
fills the remaining gap.

## What JSON mode does

At the API level, JSON mode is a constraint applied to the
decoder. Normally the model picks the highest-probability token
at every step (with `temperature=0`) from its full vocabulary
of about 30,000 to 130,000 tokens, depending on tokenizer.

In JSON mode, the runtime intercepts the decoding loop and masks
the probability distribution: any token that would produce
invalid JSON gets its probability zeroed out before sampling.
The model is *forced* to stay inside the grammar of
`{...}` / `[...]` / `"..."` / numbers / booleans / null /
whitespace.

The result: whatever the model picks is, by construction, parseable
by `json.loads`.

In OpenAI's Chat Completions, you turn this on with one parameter:

```python
response = client.chat.completions.create(
    model=model,
    temperature=0,
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ],
)
```

That's the full call from
[`call_openai`](../../scripts/llm_extract_rich_tickets.py).
`response_format={"type": "json_object"}` is the magic flag.
With it on, the response body's `choices[0].message.content` is
guaranteed valid JSON — no fences, no prose, no apologies.

In Ollama, the equivalent flag is `format: "json"` inside the
top-level payload, sitting next to `model` and `messages`. From
[`ollama_chat_json`](../../scripts/llm_extract_rich_tickets.py):

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

Different shape (Ollama puts `format` at the payload root, OpenAI
puts it inside `response_format`), same intent. After the call,
`body["message"]["content"]` is parseable JSON.

## What JSON mode does NOT do

JSON mode guarantees the bytes parse. It does not guarantee:

- The keys match what you asked for. The model can return
  `{"foo": "bar"}` and JSON mode is happy.
- The values match the types you wanted. The model can return
  `{"urgency_level": "very high"}` when you wanted an integer 1-5.
- The enum values are in your enum. The model can return
  `{"job_to_be_done": "investigate_fraud"}` even though your
  schema lists thirteen specific values and that isn't one of them.
- The narrative fields are real prose. The model can return
  `{"actual_user_want": "unknown"}` for a ticket that clearly
  expresses a want.

JSON mode is a syntactic guarantee. It does not understand your
schema. The model's *content* is still up to the model.

This is why the script does three things on top of JSON mode:

1. Embeds the schema in the user prompt as a literal description
   the model can read.
2. Validates each parsed JSON dict against enum lists and field
   requirements after the call.
3. Tags failed validations as `_status: "bad_output"` and keeps
   them in the dataset rather than throwing them away.

Lessons 03 and 04 cover the validation. This lesson covers the
schema in the prompt.

## The SCHEMA dict

[`SCHEMA`](../../scripts/llm_extract_rich_tickets.py) is a
Python dict with the field names as keys and English descriptions
as values:

```python
SCHEMA: dict[str, Any] = {
    "source_row": "string",
    "literal_request": "short string: what the user explicitly asked for",
    "actual_user_want": "short string: deeper user want behind the request",
    "job_to_be_done": "one of: recover_access, prove_innocence, restore_income, grow_channel, avoid_scam, buy_or_sell_diamonds, gain_status, understand_punishment, restore_visibility, protect_community, fix_product_flow, customize_identity, other",
    "user_emotion": "one of: neutral, confused, anxious, angry, desperate, betrayed, urgent, hopeful, unknown",
    "urgency_level": "integer 1-5",
    "trust_risk_level": "integer 1-5",
    "money_risk_level": "integer 1-5",
    "safety_policy_risk_level": "integer 1-5",
    "evidence_present": ["screenshots", "urls", "timestamps", "uid", "room_or_group_id", "ban_reason", "money_amount", "counterparty", "user_claim", "none"],
    "evidence_missing": ["list of evidence needed to resolve or escalate safely"],
    "entities": {
        "uids": ["string"],
        "room_or_group_ids": ["string"],
        "timestamps": ["string"],
        "ban_reasons": ["string"],
        "money_or_diamond_amounts": ["string"],
        "counterparties": ["string"],
        "url_count": "integer",
    },
    "support_next_step": "specific next operational action",
    "product_opportunity": "what product/system should exist so user does not need to ask again",
    "manager_note_quality": "one of: thin, adequate, rich, forensic",
    "needs_human_review": "boolean",
    "confidence": "number 0-1",
}
```

Read it as a contract. The keys are the fields the model owes
us. The values are descriptions the model uses to figure out what
to put in each field.

Notice the value types:

- For free-text fields, the value is a description in English
  ("short string: what the user explicitly asked for"). The
  description tells the model *what* to write.
- For enum fields, the value is a literal "one of: a, b, c"
  string. The model sees the legal values inline and can pick
  one.
- For list fields, the value is either a list of legal element
  values (`evidence_present`) or a list with a description
  (`evidence_missing`).
- For nested objects, the value is itself a dict with the same
  pattern (`entities`).
- For numerics and booleans, the value is the type description
  ("integer 1-5", "boolean", "number 0-1").

This dict serves three purposes: it documents the schema for
humans reading the script, it gets serialized into the prompt
for the model, and it sets the field list that
[`output_quality_flag`](../../scripts/llm_extract_rich_tickets.py)
validates against.

## Embedding the schema in the prompt

In the OpenAI backend, the schema gets serialized to a JSON
string and appended to the user prompt:

```python
def call_openai(row: pd.Series, model: str) -> dict[str, Any]:
    from openai import OpenAI
    client = OpenAI()
    schema_text = json.dumps(SCHEMA, ensure_ascii=False, indent=2)
    user_prompt = candidate_prompt(row) + "\n\nReturn JSON with this schema:\n" + schema_text
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    result = parse_json_object(content)
    result.setdefault("source_row", str(row.get("source_row", "")))
    return result
```

The model sees the user template (ticket metadata + ticket text)
followed by `Return JSON with this schema:` and a pretty-printed
copy of `SCHEMA`. Two pieces of information for the model: what
to do (extract from this ticket) and what shape the answer
should take (this dict).

You might wonder: why embed the schema if JSON mode is on?
Because JSON mode forces *valid JSON*, not *the right JSON*. The
schema in the prompt tells the model which keys to emit, which
enums to pick from, and which types each field should have. JSON
mode is the syntactic floor. The schema is the semantic ceiling.

Together they cover the easy 95% of failures. The remaining 5%
gets caught by the validator in lesson 04.

## A different prompt strategy for Ollama

The Ollama backend doesn't append the SCHEMA dict the same way.
Read
[`call_ollama`](../../scripts/llm_extract_rich_tickets.py):

```python
def call_ollama(row: pd.Series, model: str, ollama_url: str, timeout: int) -> dict[str, Any]:
    template_text = json.dumps(local_json_template(row), ensure_ascii=False, indent=2)
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
    result = ollama_chat_json(model, ollama_url, timeout, OLLAMA_SYSTEM_PROMPT, user_prompt)
    result.setdefault("source_row", str(row.get("source_row", "")))
    return result
```

Notice: instead of `json.dumps(SCHEMA)`, the Ollama prompt
appends `local_json_template(row)` — a fully-populated dict with
neutral defaults already in place.
[`local_json_template`](../../scripts/llm_extract_rich_tickets.py)
returns:

```python
return {
    "source_row": str(row.get("source_row", "")),
    "literal_request": "",
    "actual_user_want": "",
    "job_to_be_done": "other",
    "user_emotion": "unknown",
    "urgency_level": 3,
    "trust_risk_level": 3,
    "money_risk_level": 1,
    "safety_policy_risk_level": 1,
    "evidence_present": [],
    "evidence_missing": [],
    "entities": {
        "uids": [],
        "room_or_group_ids": [],
        "timestamps": [],
        "ban_reasons": [],
        "money_or_diamond_amounts": [],
        "counterparties": [],
        "url_count": 0,
    },
    "support_next_step": "",
    "product_opportunity": "",
    "manager_note_quality": "adequate",
    "needs_human_review": True,
    "confidence": 0.5,
}
```

This is a "pre-filled scaffold" or "JSON in-fill" prompt. The
small model isn't asked to construct a JSON object matching a
schema. It's asked to *overwrite* the values in a complete object
that already has every key. If the model fails to fill a field,
the safe default ("other", "unknown", 3, [], True, 0.5) survives.

Why two strategies for the same job? Capacity. GPT-4-class models
hold the schema description, the ticket, and the output structure
in working memory at once and produce a clean dict. Small models
struggle with that and routinely emit dicts with missing keys or
wrong shapes. Handing them the full skeleton with defaults
removes the construction step entirely; their job is just to
overwrite.

The defaults are also conservative on purpose. `needs_human_review:
True` means "if the model fails, escalate to a human" — the
fallback bias is toward human review, not toward auto-resolve.
`confidence: 0.5` means "I have no information" — neither
confident nor confidently wrong. Risk levels at 3 (the middle)
keep a missing extraction from biasing the dashboard either way.

## The schema artifact

After every run, the script writes the schema to disk as JSON so
operators can audit the contract.
[`write_static_assets`](../../scripts/llm_extract_rich_tickets.py)
emits three files:

```python
candidates.to_csv(run_dir / "llm_extraction_candidates.csv", index=False)
(run_dir / "llm_extraction_schema.json").write_text(json.dumps(SCHEMA, indent=2, ensure_ascii=False), encoding="utf-8")
sample_prompt = candidate_prompt(candidates.iloc[0]) if len(candidates) else USER_TEMPLATE
(run_dir / "llm_extraction_prompt.md").write_text(
    "# System Prompt\n\n" + SYSTEM_PROMPT + "\n\n# Sample User Prompt\n\n```text\n" + sample_prompt + "\n```\n",
    encoding="utf-8",
)
```

You can read
[`llm_extraction_schema.json`](../../outputs/option2_20260502_150055/llm_extraction_schema.json)
in your text editor without running anything. The point is: the
schema is the contract between your code and the model, and the
contract is checked into version control as JSON, not just hidden
inside a Python dict.

## Validating after the fact

JSON mode + schema in prompt + scaffold defaults still doesn't
guarantee correctness. The model can:

- Return a different `source_row` than the one we asked about
  (the `source_row_mismatch` flag).
- Return the literal string `"string"` for `source_row` because
  it copied the schema descriptor (`source_row_schema_echo`).
- Leave required text fields blank (`empty_required_fields`).
- Embed schema descriptors like `"one of:"` or `"short string"`
  in the narrative fields (`schema_echo`).
- Pick a `job_to_be_done` value not in the enum (`invalid_job`).
- Pick a `user_emotion` value not in the enum (`invalid_emotion`).
- Fill narrative fields with placeholders like "unknown" or
  "investigate" (`too_vague`).

[`output_quality_flag`](../../scripts/llm_extract_rich_tickets.py)
checks all seven and returns a tag string (or `None` if the
output is good). Lesson 04 walks each flag in detail. For now,
the principle: validate the parsed JSON against your schema with
explicit code, *after* the call, even when JSON mode is on.

## Try it

Read the schema, embed it in a fake prompt, parse the actual
extractions, and confirm every row has every key.

```python
import json
import pandas as pd
from pathlib import Path

run_dir = Path("outputs/option2_20260502_150055")

# 1. The schema as serialized to disk
schema = json.loads((run_dir / "llm_extraction_schema.json").read_text())
print("Schema fields:", list(schema.keys()))
print("Job enum legal values:", schema["job_to_be_done"])

# 2. The actual extractions
records = []
with (run_dir / "ollama_extractions.jsonl").open() as f:
    for line in f:
        records.append(json.loads(line))
print(f"\n{len(records)} extractions")

# 3. Are all schema keys present in every extraction?
required_keys = set(schema.keys())
for r in records:
    missing = required_keys - set(r.keys())
    if missing:
        print(f"row {r['source_row']}: missing {missing}")

# 4. Are all job_to_be_done values inside the enum?
job_values = {
    "recover_access", "prove_innocence", "restore_income", "grow_channel",
    "avoid_scam", "buy_or_sell_diamonds", "gain_status", "understand_punishment",
    "restore_visibility", "protect_community", "fix_product_flow",
    "customize_identity", "other",
}
out_of_enum = [(r["source_row"], r["job_to_be_done"])
               for r in records if r["job_to_be_done"] not in job_values]
print(f"\nout-of-enum job values: {out_of_enum}")
```

You should see two rows with out-of-enum jobs: row 5990 (job =
`"angry"`, an emotion that leaked into the job slot) and row 2739
(job = `"gain_status_or_privileges"`, the model invented a verbose
synonym for the canonical `gain_status`). Both are real failures
of "the model picked an enum value not in the enum" — and both
were caught by the validator and tagged
`_status: "bad_output"`, not by JSON mode. JSON mode let those
through because both values are valid JSON strings.

That demonstrates the rule: JSON mode is a syntactic floor.
Validation against your schema is the semantic ceiling. You need
both, plus prompt engineering, plus alias normalization. Lessons
03 through 05 build out the rest of that defense.
