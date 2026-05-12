# 04 — Validation and quality flags

The model returned 250 JSON objects. JSON mode guarantees they
all parsed. The schema description and the defensive prompt got
most of them right. But "most of them right" is not "all of them
right", and you can't ship a dataset where 2 of the 250 rows have
`job_to_be_done = "angry"` and pretend everything is fine.

You need a validator. A function that takes a parsed JSON dict
and an expected source_row, runs explicit checks against the
schema, and returns a tag describing the failure (or `None` if
the dict is good).

You also need a policy for what to do with the failures. The
project's policy: *don't throw them away*. Tag them
`_status: "bad_output"` along with the specific
`_quality_flag`, write them to disk, and let the dashboard show
them with a banner. A bad output is a record. A thrown
exception is a missing record.

This lesson walks the eight failure flags in
[`output_quality_flag`](../../scripts/llm_extract_rich_tickets.py),
the per-field validation in
[`is_concrete_phrase`](../../scripts/llm_extract_rich_tickets.py),
and the rationale for the "tag, don't throw" pattern.

## The validator function

[`output_quality_flag`](../../scripts/llm_extract_rich_tickets.py)
takes the parsed dict and the expected source_row and returns
either a flag string or `None`. The body is a sequence of checks
ordered by severity:

```python
def output_quality_flag(result: dict[str, Any], expected_source_row: str) -> str | None:
    if str(result.get("source_row", "")).strip() in {"", "string"}:
        return "source_row_schema_echo"
    if str(result.get("source_row", "")).strip() != expected_source_row:
        return "source_row_mismatch"
    required_text_fields = ["literal_request", "actual_user_want", "support_next_step", "product_opportunity"]
    if any(not str(result.get(field, "")).strip() for field in required_text_fields):
        return "empty_required_fields"
    echoed_needles = [
        "one of:",
        "short string",
        "what the user explicitly asked for",
        "deeper user want",
        "specific next operational action",
        "what product/system should exist",
        "number 0-1",
    ]
    fields = [
        result.get("literal_request"),
        result.get("actual_user_want"),
        result.get("job_to_be_done"),
        result.get("user_emotion"),
        result.get("support_next_step"),
        result.get("product_opportunity"),
        result.get("confidence"),
    ]
    text = " ".join(str(v).lower() for v in fields if v is not None)
    if any(needle in text for needle in echoed_needles):
        return "schema_echo"
    if str(result.get("job_to_be_done", "")).strip() not in JOB_VALUES:
        return "invalid_job"
    if str(result.get("user_emotion", "")).strip() not in EMOTION_VALUES:
        return "invalid_emotion"
    vague_values = {"unknown", "infer_goal", "resolve issue", "analyze", "investigate", "n/a", "none"}
    concrete_fields = ["literal_request", "actual_user_want", "support_next_step", "product_opportunity"]
    vague_count = sum(str(result.get(field, "")).strip().lower() in vague_values for field in concrete_fields)
    if vague_count >= 2:
        return "too_vague"
    return None
```

Seven distinct flags returned by this function, plus an eighth
(`narrative_quality_flag` for hybrid mode). Each is a named
failure mode with a specific code path. Walk them in the order
the validator checks.

## Flag 1: source_row_schema_echo

```python
if str(result.get("source_row", "")).strip() in {"", "string"}:
    return "source_row_schema_echo"
```

The first thing the validator checks is whether the model copied
the schema descriptor into the `source_row` field. The schema
declares `"source_row": "string"`, and a small model under
stress will sometimes return the literal value `"string"` instead
of the actual row ID.

Why is this important to detect early? Because every downstream
join keys on `source_row`. If the model returns `"string"`, the
extracted row can't be merged back to `enriched_tickets.csv` —
the join key is broken. Better to catch this at the validator
than to discover it three stages later.

The `{"", "string"}` set membership covers two cases at once:
empty string (the model returned a JSON object without
populating the field) and the literal `"string"` from the schema
descriptor.

## Flag 2: source_row_mismatch

```python
if str(result.get("source_row", "")).strip() != expected_source_row:
    return "source_row_mismatch"
```

The model returned *some* value for `source_row`, but it isn't
the one we sent in the prompt. This is rare but happens —
usually when a small model confuses itself across the
template-and-overwrite framing and substitutes a different ID.

We pass the expected value into the validator explicitly because
the validator can't know it from the dict alone. The caller
(`run_extraction`) carries the canonical ID and supplies it.

This is one reason the
[`call_openai`](../../scripts/llm_extract_rich_tickets.py) and
[`call_ollama`](../../scripts/llm_extract_rich_tickets.py)
implementations include `result.setdefault("source_row",
str(row.get("source_row", "")))` after the call. If the model
forgot to fill the field, we patch in the truth before the
validator runs. The validator then catches the cases where the
model filled it with something *wrong*, not just empty.

## Flag 3: empty_required_fields

```python
required_text_fields = ["literal_request", "actual_user_want", "support_next_step", "product_opportunity"]
if any(not str(result.get(field, "")).strip() for field in required_text_fields):
    return "empty_required_fields"
```

The four narrative fields must all be non-empty. These are the
fields the rules layer can't produce — the ones we paid for the
LLM call to get. If any is blank, the call was wasted.

Note `not str(result.get(field, "")).strip()` — defensive
coercion to handle missing keys, `None` values, and
whitespace-only strings all in one expression. `str(None)` is
`"None"` which has nonzero strip-length, so we use
`result.get(field, "")` with the empty-string default; that
returns `""` when the key is missing.

The validator returns the first failure it finds — `any(...)`
short-circuits — so you only get one flag per row even if
multiple fields are bad. That's deliberate: one named failure
per row keeps the executive report clean.

## Flag 4: schema_echo (in narrative fields)

```python
echoed_needles = [
    "one of:",
    "short string",
    "what the user explicitly asked for",
    "deeper user want",
    "specific next operational action",
    "what product/system should exist",
    "number 0-1",
]
fields = [
    result.get("literal_request"),
    result.get("actual_user_want"),
    result.get("job_to_be_done"),
    result.get("user_emotion"),
    result.get("support_next_step"),
    result.get("product_opportunity"),
    result.get("confidence"),
]
text = " ".join(str(v).lower() for v in fields if v is not None)
if any(needle in text for needle in echoed_needles):
    return "schema_echo"
```

The model copied schema descriptor text into one or more fields.
The `echoed_needles` list contains substrings drawn directly
from the
[`SCHEMA`](../../scripts/llm_extract_rich_tickets.py) dict's
description values. If any needle appears anywhere in the
concatenated narrative fields, the row is flagged.

The check is a substring match (`in`), not equality. That's
because the model might write something like `"a short string
about my account"` — partial echo, not full echo. The substring
catch is more aggressive but produces fewer false negatives.

`" ".join(str(v).lower() for v in fields if v is not None)`
joins all fields into one lowercase string for cheap searching.
The `if v is not None` filter excludes missing keys (so we don't
get `"None"` substring noise).

## Flag 5: invalid_job

```python
if str(result.get("job_to_be_done", "")).strip() not in JOB_VALUES:
    return "invalid_job"
```

The model returned a `job_to_be_done` value not in the enum.
This is the flag that fired on both bad outputs in our reference
run. Row 5990: `job_to_be_done = "angry"`. Row 2739:
`job_to_be_done = "gain_status_or_privileges"`.

Both passed
[`normalize_result_enums`](../../scripts/llm_extract_rich_tickets.py)
without being rewritten (lesson 05 explains why) and arrived at
the validator with values not in
[`JOB_VALUES`](../../scripts/llm_extract_rich_tickets.py). The
validator caught them.

The `.strip()` handles trailing whitespace from sloppy model
output. `not in JOB_VALUES` is set membership against the
canonical 13-value list.

This check runs *after* the alias normalization, so legitimate
synonyms like `"investigate_fraud"` that the alias map handles
won't trip it. Only un-aliasable invalid values reach the flag.
Lesson 05 walks the alias mechanism in detail.

## Flag 6: invalid_emotion

```python
if str(result.get("user_emotion", "")).strip() not in EMOTION_VALUES:
    return "invalid_emotion"
```

Same idea as `invalid_job`, applied to `user_emotion`. The legal
values are `[neutral, confused, anxious, angry, desperate,
betrayed, urgent, hopeful, unknown]`.

The alias map handles one specific emotion alias —
`"stressed"` rewrites to `"anxious"` in
[`normalize_result_enums`](../../scripts/llm_extract_rich_tickets.py).
Anything else not in the enum trips the flag.

In our reference run no rows tripped this. The emotion enum is
shorter (9 values vs 13 for job) and the model has a strong
prior on it from training, so it tends to stay in-enum.

## Flag 7: too_vague

```python
vague_values = {"unknown", "infer_goal", "resolve issue", "analyze", "investigate", "n/a", "none"}
concrete_fields = ["literal_request", "actual_user_want", "support_next_step", "product_opportunity"]
vague_count = sum(str(result.get(field, "")).strip().lower() in vague_values for field in concrete_fields)
if vague_count >= 2:
    return "too_vague"
```

The narrative fields aren't blank, but two or more of them are
generic placeholders. The threshold is two: one vague field is
acceptable (the model genuinely couldn't infer something), but
two means the model gave up.

Notice the threshold logic: `sum(boolean_expression for x in
seq) >= 2`. Booleans subclass int in Python, so each `True` adds
1 and each `False` adds 0. The sum counts how many of the four
fields are vague. Pythonic and faster than a manual counter.

Why is one vague field acceptable? Because real tickets do
sometimes lack one of the four. A ticket complaining about
unclear ban reasons might not have an obvious
`product_opportunity` — fixing the ticket fundamentally is the
opportunity, but the model can't be expected to articulate
"build a self-service appeal flow" on every weak ticket. One
acceptable miss leaves room for partial output.

Two vague fields is too many. At that point, the row isn't
giving you new information beyond what the rules layer already
produced.

## Flag 8: narrative_quality_flag (hybrid only)

The hybrid backend has its own validator,
[`narrative_quality_flag`](../../scripts/llm_extract_rich_tickets.py),
which runs the same family of checks but only on the narrative
fields the hybrid model is allowed to touch. We'll cover the
hybrid backend in lesson 06.

## is_concrete_phrase

The `too_vague` flag uses a coarse blacklist (just seven words).
The hybrid backend needs a stricter check because it's
specifically gating which fields get merged from the model's
output back into the rules-layer skeleton. That stricter check
is
[`is_concrete_phrase`](../../scripts/llm_extract_rich_tickets.py):

```python
def is_concrete_phrase(value: Any, field: str | None = None) -> bool:
    text = str(value or "").strip()
    if len(text) < 8:
        return False
    normalized = re.sub(r"\s+", " ", text.replace("_", " ")).strip().lower()
    if "_" in text or SNAKE_TOKEN_RE.fullmatch(text):
        return False
    if normalized in GENERIC_PHRASES:
        return False
    if field == "support_next_step" and len(text) < 24:
        return False
    if field == "product_opportunity":
        if len(text) < 36:
            return False
        product_terms = (
            "system", "workflow", "flow", "dashboard", "form", "tool",
            "receipt", "evidence", "appeal", "status", "timeline",
            "validation", "dispute", "self-service", "automation",
        )
        if not any(term in normalized for term in product_terms):
            return False
    return True
```

Five layered checks, in increasing specificity:

1. **Length floor** (≥ 8 chars). Anything shorter is almost
   certainly `"unknown"`, `"n/a"`, or empty.
2. **No underscores / not a snake_case token**. The model is
   supposed to write English; a `snake_case_thing` is an
   enum-token leak. `re.fullmatch` requires the whole string to
   match, so a sentence containing one underscore is OK only if
   it's not *purely* snake_case. The `"_" in text` check is
   stricter — any underscore at all rejects.
3. **Not in the GENERIC_PHRASES blacklist**. The blacklist:

```python
GENERIC_PHRASES = {
    "unknown",
    "infer goal",
    "resolve issue",
    "analyze",
    "investigate",
    "n/a",
    "none",
    "fix issue",
    "block user",
    "unblock user",
    "account restored",
    "ban audit",
    "ban verification",
    "ban resolution",
    "improve user experience",
    "improve dispute resolution process",
    "review rule layer and data integrity",
}
```

   Each phrase is something the model said in production that
   sounded fine in isolation but contributed nothing the rules
   layer didn't already know. "improve user experience" is the
   canonical example: every product opportunity is, in some
   sense, "improve user experience"; the phrase is empty.

4. **Per-field length floor** (`support_next_step ≥ 24 chars`).
   Operational actions need to be specific. "investigate" is 11
   chars and useless. "Check ban history and timestamps" is 32
   chars and actionable. The 24-char threshold rejects the
   former and accepts the latter.

5. **Per-field semantic-term requirement** (`product_opportunity`
   must contain one of: system, workflow, flow, dashboard,
   form, tool, receipt, evidence, appeal, status, timeline,
   validation, dispute, self-service, automation). A real
   product opportunity names a product surface. "implement a
   system to flag suspicious transactions" passes (contains
   "system"). "improve user experience" fails (none of the
   product terms).

The check is built in layers so cheap rejections happen first
(length, snake_case) before expensive ones (substring matching
across blacklists).

## "Tag, don't throw"

The validator returns a flag string. The caller's job is to
decide what to do with it.
[`run_extraction`](../../scripts/llm_extract_rich_tickets.py)
does this:

```python
result = normalize_result_enums(result)
quality_flag = output_quality_flag(result, source_row) if backend in {"ollama", "ollama_hybrid", "openai"} else None
result["_status"] = "bad_output" if quality_flag else "ok"
if quality_flag:
    result["_quality_flag"] = quality_flag
result["_backend"] = backend
result["_model"] = model
```

Three things to notice.

First: failed rows are *not* dropped. They're tagged
`_status: "bad_output"` and `_quality_flag: "<flag name>"`, then
written to the JSONL alongside the good rows.

Second: rows that crashed (model timeout, Ollama down, JSON
unparsable) get `_status: "error"` and `_error: <message>` —
infrastructure failure, not model failure.

Third: every row carries `_backend` and `_model` for provenance.

Why not throw on bad output? Because a bad output is information.
"The model failed on row 5990" is a fact you can count, audit,
and use to drive prompt changes. If you throw, that fact is lost.

## Reproducing 250 / 248 / 2

Our reference run on 2026-05-02 produced exactly 248 ok rows and
2 bad_output rows from 250 candidates. The two bad rows have
specific source_rows and specific bad values.

```python
import json
from pathlib import Path
run_dir = Path("outputs/option2_20260502_150055")

statuses = {"ok": 0, "bad_output": 0, "error": 0}
bad_rows = []
with (run_dir / "ollama_extractions.jsonl").open() as f:
    for line in f:
        r = json.loads(line)
        statuses[r["_status"]] = statuses.get(r["_status"], 0) + 1
        if r["_status"] != "ok":
            bad_rows.append(r)

print(statuses)
# {'ok': 248, 'bad_output': 2, 'error': 0}

for r in bad_rows:
    print(f"row {r['source_row']}: flag={r['_quality_flag']!r}, "
          f"job={r['job_to_be_done']!r}, emotion={r['user_emotion']!r}")
# row 5990: flag='invalid_job', job='angry', emotion='angry'
# row 2739: flag='invalid_job', job='gain_status_or_privileges', emotion='anxious'
```

Read row 5990. The model returned `"job_to_be_done": "angry"` and
also `"user_emotion": "angry"`. The two fields are duplicates —
the model picked the same word for both, treating "angry" as the
answer to both questions. The validator rejected the job
(emotion isn't in `JOB_VALUES`) and accepted the emotion (it *is*
in `EMOTION_VALUES`). One field bad, one good.

Read row 2739. The model returned `"job_to_be_done":
"gain_status_or_privileges"`. That's a verbose synonym for
`gain_status` — sensible English, just not in our enum. The
alias map (lesson 05) doesn't handle it because we hadn't
encountered it before. The validator caught it.

Both rows are in the JSONL. Both have a clean tag. A next-pass
analysis can either re-run those two specific tickets through a
larger model, or extend `JOB_ALIASES` to map
`"gain_status_or_privileges" -> "gain_status"`, or just accept
the failures and move on. The data isn't lost.

## Try it

Reproduce the count and identify the two failures, then write a
report function that summarizes failure flags for any extraction
JSONL.

```python
import json
from collections import Counter
from pathlib import Path

def summarize_extraction(jsonl_path: Path) -> dict:
    statuses = Counter()
    flags = Counter()
    bad_examples = []
    with jsonl_path.open() as f:
        for line in f:
            r = json.loads(line)
            statuses[r["_status"]] += 1
            flag = r.get("_quality_flag")
            if flag:
                flags[flag] += 1
                if len(bad_examples) < 5:
                    bad_examples.append({
                        "source_row": r["source_row"],
                        "_quality_flag": flag,
                        "job_to_be_done": r.get("job_to_be_done"),
                        "user_emotion": r.get("user_emotion"),
                    })
    return {
        "total": sum(statuses.values()),
        "by_status": dict(statuses),
        "by_flag": dict(flags),
        "bad_examples": bad_examples,
    }

run_dir = Path("outputs/option2_20260502_150055")
summary = summarize_extraction(run_dir / "ollama_extractions.jsonl")
print(json.dumps(summary, indent=2))
```

You should see:

```
{
  "total": 250,
  "by_status": {"ok": 248, "bad_output": 2},
  "by_flag": {"invalid_job": 2},
  "bad_examples": [
    {"source_row": "5990", "_quality_flag": "invalid_job",
     "job_to_be_done": "angry", "user_emotion": "angry"},
    {"source_row": "2739", "_quality_flag": "invalid_job",
     "job_to_be_done": "gain_status_or_privileges", "user_emotion": "anxious"}
  ]
}
```

Bonus: extend the function to compare two JSONLs side by side
(say, `ollama_gemma3-1b_extractions.jsonl` versus
`ollama_gemma3-4b_extractions.jsonl`). The smaller model should
have more failures across more flags. That's the underlying
data behind the model-comparison conclusions in lesson 07.
