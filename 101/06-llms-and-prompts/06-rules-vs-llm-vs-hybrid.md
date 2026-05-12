# 06 — Rules vs LLM vs hybrid

You have 6,728 tickets. You have a small local language model.
You have a deterministic regex-based classifier. You have an
optional OpenAI account.

You only need to extract structured meaning from 250 of those
6,728 tickets — the highest-context, highest-risk ones the
sampler picked. But you have a choice on each of the 250: do you
let the LLM read the ticket and produce all thirteen fields? Do
you let only the regexes do it? Do you have both run and merge
their outputs? Do you pay for OpenAI?

The right answer depends on the question you're asking. This
lesson walks the four backends defined in
[`run_extraction`](../../scripts/llm_extract_rich_tickets.py),
the rationale for each, and the design intuition behind the
hybrid backend that has become the project's daily default.

## The four backends

[`run_extraction`](../../scripts/llm_extract_rich_tickets.py)
dispatches on a string:

```python
if backend == "rules":
    result = call_rules(row)
elif backend == "ollama":
    result = call_ollama(row, model=model, ollama_url=ollama_url, timeout=timeout)
elif backend == "ollama_hybrid":
    result = call_ollama_hybrid(row, model=model, ollama_url=ollama_url, timeout=timeout)
elif backend == "openai":
    result = call_openai(row, model=model)
else:
    raise ValueError(f"Unknown backend: {backend}")
```

Four functions, each producing a dict matching
[`SCHEMA`](../../scripts/llm_extract_rich_tickets.py). Each has
different cost, latency, and accuracy properties. Walk them.

## Backend 1: rules

[`call_rules`](../../scripts/llm_extract_rich_tickets.py) is
deterministic regex extraction. No model, no API, no network.

The function runs twelve regex patterns on the ticket text:
`URL_RE`, `IMAGE_RE`, `TIMESTAMP_RE`, `UID_RE`, `ROOM_RE`,
`BAN_REASON_RE`, `MONEY_RE`, `TRANSACTION_RE`,
`SCAM_REPORT_RE`, `BAN_STATE_RE`, `GAME_RE`,
`ABUSE_REPORT_RE`, `STATUS_RE`, `CLAIM_RE`, `URGENT_RE`. Each
match becomes a boolean feature. The booleans feed a priority
cascade that picks `job_to_be_done`, plus a set of formulas that
compute risk levels:

```python
urgency_level = bounded_level(1 + len(URGENT_RE.findall(text)) / 2 + (1 if has_claim else 0) + (1 if has_scam else 0))
trust_risk = bounded_level(1 + 2 * int(has_ban) + 2 * int(has_scam) + int(has_status))
money_risk = bounded_level(1 + 3 * int(has_money) + int(has_scam))
safety_risk = bounded_level(1 + 3 * int(bool(re.search(r"\b(?:pornographic|insult|abuse|scam|fraud|violence|threat)\b", text, re.I))))
```

Each formula is a hand-tuned linear combination of features
clamped to `[1, 5]` by
[`bounded_level`](../../scripts/llm_extract_rich_tickets.py).
The weights aren't learned; they're encoded judgment. "Money
keywords get triple weight; status mention gets single weight;
ban or scam each get double weight" is a value statement about
what the team cares about.

The narrative fields come from a job-keyed lookup table:

```python
actual = {
    "avoid_scam": "User wants protection or redress from a scam/fraud dispute.",
    "buy_or_sell_diamonds": "User wants a safer money/diamonds transaction path.",
    "prove_innocence": "User wants fairness, ban transparency, or an appeal path.",
    ...
}[job]
```

Once the cascade has picked a job, the narrative is fixed. Every
ticket classified as `avoid_scam` gets the same
`actual_user_want` string. This is rigid on purpose. The rules
backend exists for sanity comparison, not nuanced output.

Properties of the rules backend:

- **Free.** No model, no API, no network call.
- **Fast.** Each ticket extracts in roughly one millisecond on
  CPU. For all 6,728 tickets the total is about seven seconds.
- **Reproducible.** Identical input produces identical output
  every run. Useful as a regression baseline.
- **Limited.** The narrative fields are fixed strings per job.
  Two tickets in the same job get the same `support_next_step`,
  even though their actual operational details differ.

Use the rules backend when:

- You're prototyping the pipeline and don't want to wait for
  model calls.
- You need a regression baseline to compare a new prompt or
  model against.
- You're computing the skeleton for the hybrid backend.

Don't use it when:

- You need narrative output that reflects the specific ticket.
- You're producing the dataset that feeds the dashboard.

## Backend 2: ollama (full local LLM)

[`call_ollama`](../../scripts/llm_extract_rich_tickets.py) sends
the per-ticket prompt to a local Ollama server, asks it to fill
the entire schema, and returns the parsed JSON. The model does
all thirteen fields — classification *and* narrative.

The prompt is the defensive one we walked in lesson 03: full
enum lists inlined, "do not" rules repeated, the
[`local_json_template`](../../scripts/llm_extract_rich_tickets.py)
skeleton with safe defaults appended. The model is asked to
overwrite the skeleton.

Properties:

- **Free.** No paid API. Ollama runs on your laptop.
- **Private.** Ticket text never leaves the machine.
- **Slow.** `gemma3:4b` on Apple Silicon CPU returns one
  extraction in roughly two to four seconds. For 250 tickets
  that's ten to fifteen minutes. For 6,728 tickets that's
  several hours.
- **Variable accuracy.** With our defensive prompt and
  `gemma3:4b`, the failure rate is 0.8% (2 of 250 in the
  reference run). Smaller models do worse — `gemma3:1b` direct
  collapses 9 of 10 tickets into `recover_access`.
- **Includes narrative.** The model writes the four narrative
  fields per-ticket. They're specific, sometimes wrong, but
  always tied to the actual ticket content.

Use the ollama backend when:

- You want the full LLM treatment but can't pay for OpenAI.
- You're benchmarking a local model against rules or hybrid.
- The dataset is small enough that 2-4 seconds per ticket is
  acceptable.

Don't use it when:

- You're running on a 6,728-ticket dataset and need it done
  today.
- The local model you have isn't reliable enough at
  classification (smaller than 4 B parameters in our experience).

## Backend 3: ollama_hybrid (rules skeleton + LLM narrative)

This is the project's daily default. The intuition is in the
docstring of
[`call_ollama_hybrid`](../../scripts/llm_extract_rich_tickets.py):

> Small local models like `gemma3:4b` are unreliable at
> structured classification (they pick wrong job_to_be_done
> values, hallucinate UIDs, or output impossible risk scores)
> but they *are* good at writing one English sentence
> describing what a user wants.

So the hybrid backend splits the work. The rules layer handles
classification and risk levels deterministically. The LLM
handles narrative interpretation only.

The pipeline is six steps:

```python
rules_result = call_rules(row)
rules_snapshot = {
    "job_to_be_done": rules_result["job_to_be_done"],
    "urgency_level": rules_result["urgency_level"],
    "trust_risk_level": rules_result["trust_risk_level"],
    "money_risk_level": rules_result["money_risk_level"],
    "safety_policy_risk_level": rules_result["safety_policy_risk_level"],
    "evidence_present": rules_result["evidence_present"],
    "evidence_missing": rules_result["evidence_missing"],
    "entities": rules_result["entities"],
}
template_text = json.dumps(hybrid_json_template(), ensure_ascii=False, indent=2)
user_prompt = (
    candidate_prompt(row)
    + "\n\nRules layer output that you must respect:\n"
    + json.dumps(rules_snapshot, ensure_ascii=False, indent=2)
    + "\n\nWrite only the interpretation JSON below."
    + "\nDo not include job_to_be_done, risk levels, evidence lists, or entities."
    + ...
)
result = json.loads(json.dumps(rules_result))
try:
    update = ollama_chat_json(model, ollama_url, timeout, HYBRID_OLLAMA_SYSTEM_PROMPT, user_prompt)
except Exception as exc:
    result["_hybrid_model_status"] = "error"
    result["_hybrid_model_error"] = str(exc)
    result["_hybrid_rules_job"] = rules_result["job_to_be_done"]
    return result
```

Step 1: run the rules layer. Get a complete dict.

Step 2: build a snapshot of the rules layer's classification and
evidence. This is the part the model is forbidden from
overriding.

Step 3: build a prompt that includes the snapshot with the
instruction "you must respect this", plus a small skeleton —
[`hybrid_json_template`](../../scripts/llm_extract_rich_tickets.py)
— containing just the eight narrative fields. The system prompt
([`HYBRID_OLLAMA_SYSTEM_PROMPT`](../../scripts/llm_extract_rich_tickets.py))
explicitly says "do not reclassify the ticket".

Step 4: copy the rules result. The copy starts as the final
result; the model's output is going to be merged into it.

Step 5: call the model. If it crashes, return the rules result
with an error tag. The ticket still gets a useful extraction
because the rules layer already filled it.

Step 6: if the model succeeded, validate each narrative field
with
[`is_concrete_phrase`](../../scripts/llm_extract_rich_tickets.py)
and merge only the fields that pass:

```python
for field in ["literal_request", "actual_user_want", "support_next_step", "product_opportunity"]:
    if is_concrete_phrase(update.get(field), field):
        result[field] = str(update[field]).strip()
if str(update.get("user_emotion", "")).strip() in EMOTION_VALUES:
    result["user_emotion"] = str(update["user_emotion"]).strip()
if str(update.get("manager_note_quality", "")).strip() in NOTE_QUALITY_VALUES:
    result["manager_note_quality"] = str(update["manager_note_quality"]).strip()
if isinstance(update.get("needs_human_review"), bool):
    result["needs_human_review"] = bool(update["needs_human_review"]) or bool(result["needs_human_review"])
result["confidence"] = round(max(float(result["confidence"]), bounded_confidence(update.get("confidence"), float(result["confidence"]))), 2)
```

Each field is gated. If `is_concrete_phrase` rejects the model's
`literal_request` (too short, snake_case, generic), the rules
layer's value survives. If the model's `user_emotion` isn't in
`EMOTION_VALUES`, the rules layer's emotion survives. The model
can only *improve* the result, not degrade it.

The confidence rule is interesting: `max(rules_confidence,
model_confidence)`. The model can raise confidence when it sees
a coherent story, but it can't drop below the rules layer's
floor of 0.55. This prevents a confused model from making the
extraction look more uncertain than it actually is.

Properties of the hybrid backend:

- **Free** (Ollama-only).
- **Robust to weak models.** A bad model output gets caught at
  validation and the rules layer's deterministic skeleton
  survives.
- **Best of both worlds.** Deterministic structure + narrative
  text that's tied to the specific ticket.
- **Slightly slower than rules alone, similar to direct ollama.**
  Same one model call per ticket.

In our model comparison
([`local_llm_model_comparison.md`](../../outputs/option2_20260502_150055/local_llm_model_comparison.md)),
the hybrid backend with `gemma3:1b` produced 25/25 valid rows
(100%) on a 25-ticket test, where direct `gemma3:1b` would have
produced about 90% valid. The hybrid backend takes a less-capable
model and makes it usable, by limiting what the model has to do.

Use the hybrid backend when:

- The local model you have isn't strong enough to do
  classification reliably but is good at sentence-writing.
- You want narrative quality without trusting a small model on
  enum picking.
- You're running production extraction and need both rigor and
  readability.

This is the default. Almost everything in the dashboard is
populated from hybrid output.

## Backend 4: openai

[`call_openai`](../../scripts/llm_extract_rich_tickets.py) is
the premium fallback. It produces the best output but costs
money and sends ticket text outside the machine.

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

Three details worth memorizing.

`from openai import OpenAI` is *inside* the function. Lazy
import. The OpenAI library is optional, so importing it at
module level would break users who only run the rules or
ollama backends. Lazy import trades a microsecond at first call
for a much friendlier dependency story.

`response_format={"type": "json_object"}` is OpenAI's JSON
mode flag (lesson 02). Same effect as Ollama's `format: "json"`.

`temperature=0` for the same reproducibility reason as the
local backends.

Properties:

- **Best output.** GPT-4-class models follow the schema, the
  prompt, and the enum constraints reliably. Failure rates on
  this kind of task are typically below 0.1%.
- **Costs money.** For 6,728 tickets at GPT-4-class pricing,
  this would have been prohibitive for the project budget.
  We've never run it at scale.
- **Sends data out.** Ticket text leaves the machine and
  reaches OpenAI's servers. For BIGO/IMO support data with
  user IDs and money amounts, this is a privacy consideration.

The script forces dry-run if the OpenAI backend is requested
without an API key:

```python
if args.backend == "openai" and not os.environ.get("OPENAI_API_KEY"):
    dry_run = True
```

Better than crashing later with an authentication error.

Use the OpenAI backend when:

- Budget allows and the data is OK to send out.
- You want a "ground truth" reference set to compare local
  models against.
- You're shipping a final report and need maximum quality on a
  small number of tickets.

Don't use it when:

- The data has user PII or financial details that shouldn't
  leave the machine.
- The dataset is large enough that the cost is a problem.

## Choosing a backend

The decision matrix is short.

| Need | Backend |
|---|---|
| Quick sanity check, no model | rules |
| Best output, willing to pay | openai |
| Free, private, large dataset | ollama_hybrid |
| Free, private, small dataset, want full LLM treatment | ollama |

For the 250-ticket extraction the project actually runs, the
choice is `ollama` with `gemma3:4b` for the dashboard's
"interpreted ticket" page and `ollama_hybrid` with `gemma3:1b`
or smaller for batch processing where reliability matters more
than narrative depth.

The CLI flag in
[`parse_args`](../../scripts/llm_extract_rich_tickets.py)
defaults to rules:

```python
parser.add_argument("--backend", choices=["rules", "ollama", "ollama_hybrid", "openai"], default="rules")
```

Default rules because it's the safest accidental run — no
model, no cost, no waiting. The shell wrapper in production
overrides this to `ollama` or `ollama_hybrid` per the operator's
intent.

## The hybrid as the central design

The hybrid backend deserves a closing remark. The reason it's
the default is that it answers the right question.

A pure-LLM approach asks: "can the model do everything?" For
small models the answer is no. They drift, hallucinate, and
collapse jobs.

A pure-rules approach asks: "can regexes do everything?" For
narrative interpretation the answer is also no. Rules can
extract evidence and pick a job, but they can't write a
sentence specific to one ticket.

The hybrid asks: "can each component do what it's best at?"
Rules do classification and structured extraction. The model
does interpretation. The validator gates the merge so the model
can only contribute when it has something concrete to say.

This is the central insight. Don't ask one component to do
work it's bad at when another component does it better. Don't
ask a small LLM to classify when a regex cascade is reliable.
Don't ask a regex to write prose when an LLM can. Compose them
so each plays to its strength, and validate at the seam.

## Try it

Run all four backends (or the three you have access to) on the
same 5 tickets and compare outputs.

```bash
# Rules backend (free, fast)
python scripts/llm_extract_rich_tickets.py outputs/option2_20260502_150055 \
    --backend rules \
    --limit 5 \
    --output-stem demo_rules

# Local model, full LLM
python scripts/llm_extract_rich_tickets.py outputs/option2_20260502_150055 \
    --backend ollama \
    --model gemma3:4b \
    --limit 5 \
    --output-stem demo_ollama

# Local model, hybrid
python scripts/llm_extract_rich_tickets.py outputs/option2_20260502_150055 \
    --backend ollama_hybrid \
    --model gemma3:4b \
    --limit 5 \
    --output-stem demo_hybrid
```

Then read the JSONLs side by side:

```python
import json
from pathlib import Path

run_dir = Path("outputs/option2_20260502_150055")

def load_jsonl(name):
    rows = {}
    p = run_dir / name
    if not p.exists():
        return rows
    with p.open() as f:
        for line in f:
            r = json.loads(line)
            rows[r["source_row"]] = r
    return rows

rules = load_jsonl("demo_rules.jsonl")
ollama = load_jsonl("demo_ollama.jsonl")
hybrid = load_jsonl("demo_hybrid.jsonl")

for src in rules.keys() & ollama.keys() & hybrid.keys():
    print(f"\n=== row {src} ===")
    print(f"  rules.actual_user_want:  {rules[src]['actual_user_want'][:80]}")
    print(f"  ollama.actual_user_want: {ollama[src]['actual_user_want'][:80]}")
    print(f"  hybrid.actual_user_want: {hybrid[src]['actual_user_want'][:80]}")
    print(f"  rules.job:  {rules[src]['job_to_be_done']}")
    print(f"  ollama.job: {ollama[src]['job_to_be_done']}")
    print(f"  hybrid.job: {hybrid[src]['job_to_be_done']}")
```

You should see:

- Rules `actual_user_want` is the same canonical sentence per
  job (it's a lookup-table string).
- Ollama `actual_user_want` is specific to the ticket.
- Hybrid `actual_user_want` is *also* specific to the ticket
  (the model wrote it), but with classification and entities
  guaranteed to match the rules layer.

For one or two of the rows, ollama and hybrid will pick
different jobs — because the model classifies on its own in
direct ollama, but is forbidden from reclassifying in hybrid.
Read those rows and decide which one you'd trust. That decision
is the one this lesson exists to support.
